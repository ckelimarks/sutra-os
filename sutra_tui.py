#!/usr/bin/env python3
"""
sutra_tui.py — TUI port of the Sutra orchestrator.

Quick visual port of web/index.html: header, toolbar, SUTRA dispatch bus,
agent lanes with blocks, chat input. Not wired to the backend — this is
what it *looks* like, not what it *does*.

Run:   python3 sutra_tui.py
Keys:  Tab / 1-4  switch view (Timeline/Chat/Terminal/Ideas)
       q          quit
"""

import curses
import time
from dataclasses import dataclass, field
from typing import List

# ── palette (mapped from web/index.html CSS vars) ────────────────────────────
# curses color indices we'll define via init_color when supported.
# Fallback is the nearest 256-color ANSI.
PAL = {
    "bg":        (10, 10, 12),
    "bg_elev":   (17, 17, 20),
    "border":    (30, 30, 37),
    "text":      (232, 232, 236),
    "dim":       (138, 138, 148),
    "faint":     (74, 74, 84),
    "sutra":     (139, 92, 246),
    "lovenotes": (209, 107, 158),
    "content":   (90, 149, 214),
    "geoint":    (217, 126, 78),
    "coder":     (93, 179, 179),
    "brandywine":(184, 134, 74),
    "designer":  (167, 139, 250),
    "helper":    (107, 107, 120),
    "red":       (239, 68, 68),
    "amber":     (234, 179, 8),
    "green":     (74, 222, 128),
}

PAIR = {}  # name -> curses pair id

# ── fake data (mirrors loadAgents output shape) ──────────────────────────────
@dataclass
class Block:
    start: float       # 0..1 along the lane
    width: float       # 0..1 of lane width
    label: str
    subtitle: str = ""
    state: str = "done"  # done | running | paused

@dataclass
class Agent:
    name: str
    sub: str
    color: str
    blocks: List[Block] = field(default_factory=list)
    context: int = 0
    status: str = "idle"  # running | idle | paused

AGENTS = [
    Agent("LoveNotes",  "claude — sonnet", "lovenotes", context=42, status="running", blocks=[
        Block(0.05, 0.12, "Migrate schema",     "prompts_per_week", "done"),
        Block(0.20, 0.18, "Shadow-mode deploy", "use_inngest flag", "running"),
        Block(0.48, 0.08, "Verify toll-free",   "Twilio — rejected", "paused"),
    ]),
    Agent("ContentWriter", "claude — haiku", "content", context=18, status="running", blocks=[
        Block(0.10, 0.10, "Draft RFP post",     "r/LocalLLaMA", "done"),
        Block(0.30, 0.22, "Speedrun app",       "a16z — May 17", "running"),
    ]),
    Agent("GEOINT",     "claude — opus",   "geoint", context=71, status="paused", blocks=[
        Block(0.02, 0.06, "Pull RSS",           "7 feeds", "done"),
        Block(0.12, 0.14, "Assess macro",       "oil bounce, not spike", "done"),
        Block(0.30, 0.24, "Region classify",    "awaiting permission", "paused"),
    ]),
    Agent("Coder",      "claude — opus",   "coder", context=54, status="running", blocks=[
        Block(0.08, 0.16, "Fix reset shadow",   "bridge.py:1641", "done"),
        Block(0.28, 0.10, "REQ-6.2 wire-up",    "process_manager.py", "done"),
        Block(0.42, 0.20, "Improve-prompt",     "Haiku rewriter", "running"),
    ]),
    Agent("Brandywine", "claude — sonnet", "brandywine", context=22, status="idle", blocks=[
        Block(0.15, 0.08, "K-1 box 13",         "§743(b) codes", "done"),
    ]),
    Agent("Designer",   "claude — opus",   "designer", context=8, status="idle", blocks=[
        Block(0.55, 0.14, "Mockup-l",           "session lifecycle layer", "done"),
    ]),
    Agent("Helper",     "claude — haiku",  "helper", context=3, status="idle", blocks=[]),
]

SUTRA_BLOCKS = [
    Block(0.04, 0.06, "dispatch", "LoveNotes", "done"),
    Block(0.18, 0.06, "dispatch", "Coder",     "done"),
    Block(0.35, 0.06, "dispatch", "GEOINT",    "done"),
    Block(0.52, 0.06, "dispatch", "Content",   "running"),
]

VIEWS = ["Timeline", "Chat", "Terminal", "Ideas"]
ATTENTION = [
    ("red",   "GEOINT",        "Region classification review",
                               "Paused — awaiting permission to edit classification file"),
    ("amber", "ContentWriter", "Publish Reddit post 1?",
                               "Draft ready. 312 words, 3 concrete examples."),
]

# ── color setup ──────────────────────────────────────────────────────────────
def _scale(c):
    return int(round(c * 1000 / 255))

def setup_colors():
    curses.start_color()
    curses.use_default_colors()
    can_change = curses.can_change_color() and curses.COLORS >= 16

    # Reserve indices 16..16+len(PAL) if we can change colors.
    base = 16
    slot = {}
    if can_change:
        for i, (name, (r, g, b)) in enumerate(PAL.items()):
            idx = base + i
            try:
                curses.init_color(idx, _scale(r), _scale(g), _scale(b))
                slot[name] = idx
            except curses.error:
                slot[name] = -1
    else:
        # Fallback — rough 256-color approximations
        fallback = {"bg": -1, "bg_elev": 235, "border": 237, "text": 252, "dim": 244,
                    "faint": 240, "sutra": 99, "lovenotes": 168, "content": 74,
                    "geoint": 173, "coder": 109, "brandywine": 137, "designer": 141,
                    "helper": 243, "red": 203, "amber": 220, "green": 120}
        slot = fallback

    # Pairs: fg on default bg. Pair 0 is reserved.
    pid = 1
    for name, idx in slot.items():
        curses.init_pair(pid, idx, -1)
        PAIR[name] = pid
        pid += 1

    # Inverse pairs for blocks (fg on colored bg).
    for name in ("lovenotes", "content", "geoint", "coder", "brandywine",
                 "designer", "helper", "sutra"):
        idx = slot.get(name, 99)
        curses.init_pair(pid, slot.get("text", 252), idx)
        PAIR[f"{name}_bg"] = pid
        pid += 1

def C(name, attr=0):
    return curses.color_pair(PAIR.get(name, 0)) | attr

# ── drawing helpers ──────────────────────────────────────────────────────────
def safe_addstr(win, y, x, s, attr=0):
    h, w = win.getmaxyx()
    if y < 0 or y >= h or x >= w:
        return
    if x < 0:
        s = s[-x:]
        x = 0
    if not s:
        return
    s = s[: max(0, w - x - 1)]
    try:
        win.addstr(y, x, s, attr)
    except curses.error:
        pass

def hr(win, y, x, w, ch="─", attr=0):
    safe_addstr(win, y, x, ch * w, attr)

# ── header / toolbar ─────────────────────────────────────────────────────────
def draw_header(win, view_idx, tick):
    h, w = win.getmaxyx()
    # Brand
    dot = "●" if (tick // 6) % 2 == 0 else "◉"
    safe_addstr(win, 0, 2, dot, C("sutra", curses.A_BOLD))
    safe_addstr(win, 0, 4, "Sutra", C("text", curses.A_BOLD))
    safe_addstr(win, 0, 10, "orchestrator", C("faint"))

    # View switcher
    switch = ""
    segs = []
    x = 0
    for i, v in enumerate(VIEWS):
        label = f" {v} "
        segs.append((x, label, i == view_idx))
        x += len(label) + 1  # + separator
    total = sum(len(s) for _, s, _ in segs) + (len(segs) - 1)
    start = max(24, w - total - 28)
    for ox, label, active in segs:
        attr = C("text", curses.A_REVERSE) if active else C("dim")
        safe_addstr(win, 0, start + ox, label, attr)
        safe_addstr(win, 0, start + ox + len(label), " ", C("border"))

    # Attention pill
    red = sum(1 for a in ATTENTION if a[0] == "red")
    amber = sum(1 for a in ATTENTION if a[0] == "amber")
    pill = f" ● {red}  ▲ {amber} attention "
    safe_addstr(win, 0, max(0, w - len(pill) - 2), pill, C("amber"))

    hr(win, 1, 0, w, "─", C("border"))

def draw_toolbar(win, y, tick):
    h, w = win.getmaxyx()
    now = time.strftime("%-I:%M %p")
    left = f"Tue · Apr 21  ·  9:00 AM  ──  ◉ NOW {now}"
    safe_addstr(win, y, 2, left, C("dim"))
    right = "[Density 100%]  [+ New Agent]  [⏱ Snap to now]  [⬡ Sub-agents]"
    safe_addstr(win, y, max(2 + len(left) + 4, w - len(right) - 2), right, C("faint"))
    hr(win, y + 1, 0, w, "─", C("border"))

# ── timeline ─────────────────────────────────────────────────────────────────
LABEL_W = 22
LANE_H = 3
SUTRA_H = 3

def draw_ruler(win, y, x0, lane_w):
    # 9 AM → NOW; 6 ticks
    for i in range(7):
        px = x0 + int(lane_w * i / 6)
        hh = 9 + 2 * i
        tag = f"{hh if hh<=12 else hh-12}{'A' if hh<12 else 'P'}"
        safe_addstr(win, y, px, tag, C("faint"))
    hr(win, y + 1, x0, lane_w, "·", C("border"))

def render_block(win, y, x0, lane_w, block: Block, color_name: str, tick: int):
    bx = x0 + int(lane_w * block.start)
    bw = max(3, int(lane_w * block.width))
    if block.state == "running":
        # pulsing glyph fill
        fills = ["▓", "█", "▓", "▒"]
        ch = fills[tick % len(fills)]
        attr = C(f"{color_name}_bg", curses.A_BOLD)
    elif block.state == "paused":
        ch = "░"
        attr = C(color_name, curses.A_DIM)
    else:
        ch = "█"
        attr = C(f"{color_name}_bg")
    safe_addstr(win, y, bx, ch * bw, attr)

    # label on block (truncated)
    inner = bw - 2
    if inner > 4:
        lbl = block.label[:inner]
        lbl_attr = C(f"{color_name}_bg", curses.A_BOLD) if block.state != "paused" else C(color_name)
        safe_addstr(win, y, bx + 1, lbl, lbl_attr)
    # subtitle below
    if bw > 6 and block.subtitle:
        sub = block.subtitle[: bw]
        safe_addstr(win, y + 1, bx, sub, C("dim"))

def draw_sutra_bus(win, y, x0, lane_w, tick):
    # Label
    safe_addstr(win, y, 2, "╭─╮", C("sutra"))
    safe_addstr(win, y + 1, 2, "│S│", C("sutra", curses.A_BOLD))
    safe_addstr(win, y + 2, 2, "╰─╯", C("sutra"))
    safe_addstr(win, y + 1, 6, "SUTRA", C("sutra", curses.A_BOLD))
    safe_addstr(win, y + 2, 6, "dispatch bus", C("faint"))

    # Bus track
    track = "─" * lane_w
    safe_addstr(win, y + 1, x0, track, C("sutra", curses.A_DIM))

    for b in SUTRA_BLOCKS:
        render_block(win, y + 1, x0, lane_w, b, "sutra", tick)

def draw_agent_lane(win, y, x0, lane_w, agent: Agent, tick: int):
    # Label column
    dotmap = {"running": "green", "paused": "red", "idle": "faint"}
    dot_color = dotmap.get(agent.status, "faint")
    safe_addstr(win, y, 2, "●", C(dot_color))
    safe_addstr(win, y, 4, agent.name[:LABEL_W - 6], C(agent.color, curses.A_BOLD))
    safe_addstr(win, y + 1, 4, agent.sub[:LABEL_W - 6], C("faint"))
    ctx = f"ctx {agent.context:>2}%"
    safe_addstr(win, y + 2, 4, ctx, C("dim"))

    # Lane track
    track = "·" * lane_w
    safe_addstr(win, y + 1, x0, track, C("border"))

    for b in agent.blocks:
        render_block(win, y + 1, x0, lane_w, b, agent.color, tick)

# ── views ────────────────────────────────────────────────────────────────────
def draw_timeline(win, tick):
    h, w = win.getmaxyx()
    lanes_y = 5
    x0 = LABEL_W + 2
    lane_w = w - x0 - 2

    draw_ruler(win, lanes_y - 1, x0, lane_w)
    draw_sutra_bus(win, lanes_y, x0, lane_w, tick)

    y = lanes_y + SUTRA_H + 1
    hr(win, y - 1, 0, w, "─", C("border"))
    for a in AGENTS:
        if y + LANE_H >= h - 3:
            break
        draw_agent_lane(win, y, x0, lane_w, a, tick)
        y += LANE_H

    # Playhead at ~90% of lane (NOW)
    ph_x = x0 + int(lane_w * 0.92)
    for yy in range(lanes_y, min(y, h - 3)):
        safe_addstr(win, yy, ph_x, "│", C("sutra", curses.A_DIM))

def draw_chat(win, tick):
    h, w = win.getmaxyx()
    y = 4
    # Sidebar (agent list)
    safe_addstr(win, y, 2, "AGENTS", C("faint", curses.A_BOLD))
    for i, a in enumerate(AGENTS):
        yy = y + 2 + i
        if yy >= h - 4:
            break
        safe_addstr(win, yy, 2, "●", C(a.color))
        safe_addstr(win, yy, 4, a.name, C("text"))
        safe_addstr(win, yy, 20, a.status, C("dim"))

    # Thread
    tx = 30
    safe_addstr(win, y, tx, "Thread · Coder", C("text", curses.A_BOLD))
    safe_addstr(win, y + 1, tx, "claude — opus · session active", C("faint"))

    msgs = [
        ("you",  "ship REQ-6.2 human-in-loop, not auto-execute"),
        ("Coder", "touched process_manager.py:_maybe_auto_spoof. At 70% I set"),
        ("",      "reset_pending:{reason:context_pressure}. Modal auto-opens; you pick."),
        ("you",  "good. also delete the legacy /reset handler at :1641"),
        ("Coder", "done. handler at :1763 now owns the path. spoof events enriched."),
        ("you",  "show me the spoof event shape"),
        ("Coder", "outcome, trigger, context_pct_before, old→new session_id, error"),
    ]
    yy = y + 3
    for who, msg in msgs:
        if yy >= h - 4:
            break
        who_attr = C("sutra", curses.A_BOLD) if who == "you" else C("coder", curses.A_BOLD)
        if who:
            safe_addstr(win, yy, tx, f"{who:>6}", who_attr)
        safe_addstr(win, yy, tx + 8, msg, C("text" if who else "dim"))
        yy += 1

    # Detail panel
    dx = w - 30
    safe_addstr(win, y, dx, "FILES · TOKENS · SESSIONS", C("faint", curses.A_BOLD))
    files = ["server/process_manager.py", "server/bridge.py", "web/index.html",
             "INFRA.md", "TASK.md"]
    for i, f in enumerate(files):
        safe_addstr(win, y + 2 + i, dx, f"  {f}", C("dim"))

def draw_terminal(win, tick):
    h, w = win.getmaxyx()
    lines = [
        ("$ ./start.sh",                                      "sutra"),
        ("bridge.py listening on :8900",                      "dim"),
        ("process_manager: 7 agents registered",              "dim"),
        ("session_manager: reconciling...",                   "dim"),
        ("[hook] pre-prompt-submit  agent=Coder  bytes=1842", "faint"),
        ("[hook] tool-use           agent=Coder  tool=Edit",  "faint"),
        ("[signal] Coder · Edit · bridge.py:1763",            "coder"),
        ("[report] Coder · REQ-6.2 shipped",                  "green"),
        ("[attn]   GEOINT · paused · needs permission",       "red"),
        ("[spoof]  Coder  68% → 12%  old→new_session",        "sutra"),
        ("$ _",                                               "sutra"),
    ]
    for i, (line, c) in enumerate(lines):
        if 4 + i >= h - 4:
            break
        safe_addstr(win, 4 + i, 4, line, C(c))

def draw_ideas(win, tick):
    h, w = win.getmaxyx()
    safe_addstr(win, 4, 4, "Ideas", C("text", curses.A_BOLD))
    safe_addstr(win, 4, 12, "4 items", C("faint"))

    items = [
        "Chaos vs Control — LinkedIn piece on agent orchestration UX",
        "Per-block token-usage waveform (spoof markers overlay)",
        "Sidebar-as-Atlas: generated, not maintained",
        "One composite signal over N money numbers (MACRO pattern)",
    ]
    for i, it in enumerate(items):
        safe_addstr(win, 7 + i * 2, 4, "▸", C("sutra"))
        safe_addstr(win, 7 + i * 2, 6, it, C("text"))

    safe_addstr(win, h - 6, 4, "Drop an idea...", C("faint"))
    hr(win, h - 5, 4, w - 8, "─", C("border"))

# ── chat bar (global) ────────────────────────────────────────────────────────
def draw_chat_bar(win):
    h, w = win.getmaxyx()
    y = h - 3
    hr(win, y, 0, w, "─", C("border"))
    safe_addstr(win, y + 1, 2, "❯", C("sutra", curses.A_BOLD))
    safe_addstr(win, y + 1, 4, "Dispatch to Sutra — @ to target an agent", C("faint"))
    hint = "[Shift+↵ improve]  [Tab switch view]  [q quit]"
    safe_addstr(win, y + 1, max(4, w - len(hint) - 2), hint, C("faint"))

# ── main loop ────────────────────────────────────────────────────────────────
def main(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.keypad(True)
    setup_colors()

    view_idx = 0
    tick = 0
    last = time.time()

    while True:
        # input
        try:
            ch = stdscr.getch()
        except curses.error:
            ch = -1
        if ch in (ord("q"), ord("Q")):
            break
        elif ch in (9,):  # Tab
            view_idx = (view_idx + 1) % len(VIEWS)
        elif ch in (ord("1"), ord("2"), ord("3"), ord("4")):
            view_idx = int(chr(ch)) - 1

        stdscr.erase()
        h, w = stdscr.getmaxyx()
        if h < 18 or w < 80:
            safe_addstr(stdscr, 0, 0, "Terminal too small (need 80×18+)", C("amber"))
        else:
            draw_header(stdscr, view_idx, tick)
            draw_toolbar(stdscr, 2, tick)
            view = VIEWS[view_idx]
            if view == "Timeline":
                draw_timeline(stdscr, tick)
            elif view == "Chat":
                draw_chat(stdscr, tick)
            elif view == "Terminal":
                draw_terminal(stdscr, tick)
            elif view == "Ideas":
                draw_ideas(stdscr, tick)
            draw_chat_bar(stdscr)

        stdscr.refresh()

        # ~8fps animation
        now = time.time()
        dt = now - last
        if dt < 0.12:
            time.sleep(0.12 - dt)
        last = time.time()
        tick += 1


if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
