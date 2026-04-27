#!/usr/bin/env python3
"""
Sutra terminal dashboard — pure text view of the orchestrator.

Usage:
  ./dashboard.py              # 3s refresh
  ./dashboard.py --once       # print one snapshot and exit
  ./dashboard.py --interval 1 # 1s refresh
  ./dashboard.py --compact    # one-line-per-agent, less detail
  SUTRA_PORT=8901 ./dashboard.py
"""

import argparse
import io
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

PORT = int(os.environ.get("SUTRA_PORT", 8900))
BASE = f"http://localhost:{PORT}"

# ANSI
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
BLUE = "\033[34m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"
GREY = "\033[90m"
# Purple shades (256-color) for agent rows
PURPLE_BRIGHT = "\033[1;38;5;141m"   # bold light purple — agent name
PURPLE = "\033[38;5;135m"            # medium purple — primary info
PURPLE_DIM = "\033[38;5;97m"         # dim purple — secondary info
CLEAR = "\033[2J\033[H"
HOME = "\033[H"            # cursor to top-left, no clear
CLEAR_BELOW = "\033[J"     # clear from cursor to end of screen
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
ALT_SCREEN_ON = "\033[?1049h"
ALT_SCREEN_OFF = "\033[?1049l"

STATUS_DOT = {
    "online": f"{GREEN}●{RESET}",
    "busy": f"{YELLOW}◐{RESET}",
    "offline": f"{GREY}○{RESET}",
    "error": f"{RED}✗{RESET}",
}

WIDTH = 78


def fetch(path, default=None):
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=2) as r:
            return json.loads(r.read())
    except Exception:
        return default


def truncate(s, n):
    s = (s or "").replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def fmt_pct(p, width=4):
    if p is None:
        return f"{GREY}{'  -':>{width}}{RESET}"
    color = GREEN if p < 50 else YELLOW if p < 80 else RED
    return f"{color}{p:>{width-1}}%{RESET}"


def fmt_time(iso_or_epoch):
    try:
        if isinstance(iso_or_epoch, (int, float)):
            dt = datetime.fromtimestamp(iso_or_epoch)
        elif isinstance(iso_or_epoch, str):
            dt = datetime.fromisoformat(iso_or_epoch.replace("Z", "+00:00")).astimezone()
        else:
            return "  -  "
        return dt.strftime("%H:%M")
    except Exception:
        return "  -  "


def fmt_relative(epoch_or_iso):
    try:
        if isinstance(epoch_or_iso, str):
            dt = datetime.fromisoformat(epoch_or_iso.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                epoch = dt.timestamp()
            else:
                epoch = dt.astimezone().timestamp()
        else:
            epoch = float(epoch_or_iso)
        if epoch <= 0:
            return "?"
        delta = time.time() - epoch
        if delta < 0:
            return "now"
        if delta < 60:
            return f"{int(delta)}s ago"
        if delta < 3600:
            return f"{int(delta // 60)}m ago"
        if delta < 86400:
            return f"{int(delta // 3600)}h ago"
        return f"{int(delta // 86400)}d ago"
    except Exception:
        return "?"


def visible_len(s):
    # strip ANSI escape codes for accurate width
    import re
    return len(re.sub(r"\033\[[0-9;]*m", "", s))


def pad_visible(s, width):
    return s + " " * max(0, width - visible_len(s))


def progress_bar(used, total, width=20):
    if not total or total <= 0:
        return f"{GREY}{'─' * width}{RESET}"
    pct = min(1.0, used / total)
    filled = int(pct * width)
    color = GREEN if pct < 0.6 else YELLOW if pct < 0.85 else RED
    return f"{color}{'█' * filled}{GREY}{'░' * (width - filled)}{RESET}"


def hr(char="─", color=GREY):
    print(f"{color}{char * WIDTH}{RESET}")


def gather(compact=False):
    """Fetch everything in parallel into a single dict. Render reads only from this."""
    overview = fetch("/api/status/overview", {}) or {}
    agents = overview.get("agents", [])

    # First, the cheap top-level calls in parallel
    paths = {
        "health": "/api/health",
        "budget": "/api/budget",
        "rate": "/api/rate-limits",
        "attention": "/api/attention",
        "signals": "/api/signals",
        "heartbeats": "/api/orchestrator/heartbeats",
    }
    # Plus per-agent calls
    for a in agents:
        aid = a.get("agent_id")
        if aid:
            paths[f"recent:{aid}"] = f"/api/agents/{aid}/recent?n=4"
            paths[f"queue:{aid}"] = f"/api/agents/{aid}/queue"

    results = {"overview": overview}
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = {pool.submit(fetch, p, {}): k for k, p in paths.items()}
        for fut, key in futures.items():
            try:
                results[key] = fut.result() or {}
            except Exception:
                results[key] = {}
    return results


def header(data):
    health = data.get("health", {}) or {}
    overview = data.get("overview", {}) or {}
    budget = data.get("budget", {}) or {}
    rate = data.get("rate", {}) or {}

    totals = overview.get("session_totals", {})
    cost = totals.get("cost_usd", 0.0)
    msgs = totals.get("message_count", 0)
    active = totals.get("active_agents", 0)
    total_agents = totals.get("total_agents", 0)

    daily_limit = budget.get("daily_limit") or budget.get("daily_budget") or 0
    monthly_limit = budget.get("monthly_limit") or budget.get("monthly_budget") or 0

    status = "online" if health.get("status") == "ok" else "DOWN"
    color = GREEN if status == "online" else RED
    now = datetime.now().strftime("%H:%M:%S")

    # Rate limit warning
    rl_warn = ""
    for prov, s in (rate.get("rate_limits") or {}).items():
        if s.get("is_limited"):
            rl_warn = f"  {RED}⚠ {prov} rate-limited{RESET}"
            break

    inner = WIDTH - 2
    print(f"{CYAN}┌{'─' * WIDTH}┐{RESET}")
    line1 = f"{BOLD}SUTRA{RESET}  {DIM}·{RESET}  localhost:{PORT}  {DIM}·{RESET}  {color}{status}{RESET}  {DIM}·{RESET}  {DIM}{now}{RESET}{rl_warn}"
    print(f"{CYAN}│{RESET} {pad_visible(line1, inner)} {CYAN}│{RESET}")
    line2 = f"agents {BOLD}{active}/{total_agents}{RESET} active   messages {BOLD}{msgs}{RESET}   spend {BOLD}${cost:.2f}{RESET}"
    if daily_limit:
        bar = progress_bar(cost, daily_limit, 18)
        line2 += f"   {bar} {DIM}/${daily_limit:.0f} day{RESET}"
    print(f"{CYAN}│{RESET} {pad_visible(line2, inner)} {CYAN}│{RESET}")
    print(f"{CYAN}└{'─' * WIDTH}┘{RESET}")


def section_header(title, count=None, hint=None):
    """Consistent section header with a purple accent bar."""
    parts = [f"\n{PURPLE_BRIGHT}▍{RESET} {BOLD}{title}{RESET}"]
    if count is not None:
        parts.append(f"  {DIM}{count}{RESET}")
    if hint:
        parts.append(f"  {DIM}{hint}{RESET}")
    print("".join(parts))


def agents_section(data, compact=False):
    overview = data.get("overview", {}) or {}
    agents = overview.get("agents", [])
    section_header("AGENTS", count=len(agents))
    if not agents:
        print(f"  {DIM}no agents — POST /api/agents to create one{RESET}")
        return

    for idx, a in enumerate(agents):
        agent_id = a.get("agent_id") or ""
        dot = STATUS_DOT.get(a.get("status"), "?")
        name = truncate(a.get("agent_name", ""), 16)
        model = truncate(a.get("model", "-"), 7)
        cost = a.get("cost_usd", 0)
        msg_count = a.get("message_count", 0)

        recent = data.get(f"recent:{agent_id}", {}) or {}
        pct = recent.get("context_percent")
        messages = recent.get("recent_messages", []) or []
        last_error = recent.get("last_error")

        q = data.get(f"queue:{agent_id}", {}) or {}
        queue_depth = len(q.get("queue", []) or [])
        qbadge = f" {YELLOW}[+{queue_depth} queued]{RESET}" if queue_depth else ""

        # Container left-bar binds the agent block visually
        bar = f"{PURPLE}┃{RESET}"
        bar_dim = f"{PURPLE_DIM}┃{RESET}"

        # main line — name + raw agent_id + model + ctx + cost + msgs
        line = (
            f"{bar} {dot}  "
            f"{PURPLE_BRIGHT}{name:<16}{RESET} "
            f"{PURPLE}{agent_id:<10}{RESET} "
            f"{PURPLE_DIM}{model:<7}{RESET} "
            f"{PURPLE_DIM}ctx{RESET} {fmt_pct(pct)}  "
            f"{PURPLE_DIM}${cost:>5.2f}{RESET}  "
            f"{PURPLE_DIM}{msg_count} msgs{RESET}{qbadge}"
        )
        print(line)

        if compact:
            continue

        # find most recent user prompt and most recent assistant reply
        last_user = next((m for m in reversed(messages) if m.get("role") == "user"), None)
        last_asst = next((m for m in reversed(messages) if m.get("role") == "assistant"), None)

        if last_user:
            content = truncate(last_user.get("content", ""), WIDTH - 22)
            ts = fmt_relative(last_user.get("created_at"))
            print(f"{bar_dim}    {CYAN}▸ user{RESET}  {DIM}{ts:>7}{RESET}  {content}")
        if last_asst:
            content = truncate(last_asst.get("content", ""), WIDTH - 22)
            ts = fmt_relative(last_asst.get("created_at"))
            print(f"{bar_dim}    {GREEN}◂ asst{RESET}  {DIM}{ts:>7}{RESET}  {DIM}{content}{RESET}")
        # last_error is a noisy keyword match — only show if it's distinct from the visible reply
        if last_error and last_asst and last_error[:80] != (last_asst.get("content", "") or "")[:80]:
            err = truncate(last_error, WIDTH - 22)
            print(f"{bar_dim}    {RED}! err{RESET}             {RED}{err}{RESET}")
        if not last_user and not last_asst:
            la = truncate(a.get("last_action") or "", WIDTH - 18)
            if la and la != "idle":
                print(f"{bar_dim}    {DIM}↳ {la}{RESET}")


def attention_section(data):
    att = data.get("attention", {}) or {}
    needs_input = att.get("needs_input", [])
    needs_perm = att.get("needs_permission", [])
    completed = att.get("completed", [])
    reset_pending = att.get("reset_pending", [])
    total = len(needs_input) + len(needs_perm) + len(completed) + len(reset_pending)
    section_header("ATTENTION", count=total)
    if total == 0:
        print(f"  {DIM}all clear{RESET}")
        return
    for item in needs_input:
        tag = f"{RED}▌BLOCK{RESET}"
        msg = truncate(item.get("message", ""), 60)
        print(f"  {tag} {BOLD}{item.get('agent_name', '?'):<14}{RESET} {msg}")
    for item in needs_perm:
        tag = f"{YELLOW}▌APPRV{RESET}"
        instr = truncate(item.get("instruction", ""), 55)
        print(f"  {tag} {BOLD}{item.get('agent_name', '?'):<14}{RESET} {instr}")
        print(f"         {DIM}approve: POST /api/approvals/{item.get('approval_id')}/approve{RESET}")
    for item in completed:
        tag = f"{GREEN}▌DONE {RESET}"
        summary = truncate(item.get("summary") or item.get("instruction", ""), 55)
        print(f"  {tag} {BOLD}{item.get('agent_name', '?'):<14}{RESET} {summary}")
    for item in reset_pending:
        tag = f"{YELLOW}▌CTX  {RESET}"
        print(f"  {tag} {BOLD}{item.get('agent_name', '?'):<14}{RESET} context {item.get('turn_count')}/{item.get('threshold')} turns — needs reset")


def signals_section(data, name_lookup):
    sig = data.get("signals", {}) or {}
    items = (sig.get("signals") or [])[:8]
    section_header("ACTIVITY", hint="recent tool calls")
    if not items:
        print(f"  {DIM}quiet{RESET}")
        return
    for s in items:
        ts = fmt_relative(s.get("timestamp", 0))
        aid = s.get("agent_id", "")
        name = s.get("agent_name") or name_lookup.get(aid) or (aid[:8] if aid else "?")
        agent = truncate(name, 14)
        tool = truncate(s.get("tool", s.get("event", "?")), 12)
        detail = truncate(s.get("file") or s.get("command") or s.get("detail") or s.get("input", ""), WIDTH - 40)
        color = CYAN if "Read" in tool or "Glob" in tool else MAGENTA if "Edit" in tool or "Write" in tool else BLUE
        print(f"  {DIM}{ts:>7}{RESET}  {PURPLE_DIM}{agent:<14}{RESET}  {color}{tool:<12}{RESET}  {DIM}{detail}{RESET}")


def heartbeats_section(data):
    hb_resp = data.get("heartbeats", {}) or {}
    hbs = hb_resp.get("heartbeats")
    if not hbs:
        return
    items = list(hbs.values()) if isinstance(hbs, dict) else list(hbs)
    if not items:
        return
    # only show recent heartbeats (last 24h)
    fresh = []
    for hb in items:
        if not isinstance(hb, dict):
            continue
        last = hb.get("last_heartbeat") or hb.get("timestamp") or 0
        try:
            if isinstance(last, str):
                ts = datetime.fromisoformat(last.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=datetime.now().astimezone().tzinfo)
                age = time.time() - ts.timestamp()
            else:
                age = time.time() - float(last)
            if age < 86400:
                fresh.append(hb)
        except Exception:
            pass
    if not fresh:
        return
    fresh = fresh[:5]
    section_header("HEARTBEATS", hint="last 24h")
    for hb in fresh:
        ts = fmt_relative(hb.get("last_heartbeat") or hb.get("timestamp") or 0)
        worker = truncate(hb.get("agent_name") or hb.get("worker_name", "?"), 14)
        task = hb.get("current_task") or hb.get("status", "")
        last_prompt = hb.get("last_prompt") or ""
        detail = truncate(last_prompt or task, WIDTH - 30)
        print(f"  {DIM}{ts:>7}{RESET}  {PURPLE_DIM}{worker:<14}{RESET}  {DIM}{detail}{RESET}")


def footer(interval):
    print()
    hr()
    print(f"{DIM}refresh {interval}s   ctrl+c to quit   --compact for slim view{RESET}")


def render_to_buffer(compact, interval, show_footer):
    """Build the full frame as a string. All fetches happen here, in parallel."""
    data = gather(compact=compact)
    overview = data.get("overview", {}) or {}
    name_lookup = {a.get("agent_id"): a.get("agent_name") for a in overview.get("agents", [])}

    buf = io.StringIO()
    saved = sys.stdout
    sys.stdout = buf
    try:
        header(data)
        agents_section(data, compact=compact)
        attention_section(data)
        signals_section(data, name_lookup)
        if not compact:
            heartbeats_section(data)
        if show_footer:
            footer(interval)
    finally:
        sys.stdout = saved
    return buf.getvalue()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true", help="print one snapshot and exit")
    p.add_argument("--interval", type=float, default=3.0, help="refresh seconds")
    p.add_argument("--compact", action="store_true", help="slim view")
    p.add_argument("--no-alt-screen", action="store_true", help="don't switch to alt screen buffer")
    args = p.parse_args()

    if args.once:
        sys.stdout.write(render_to_buffer(args.compact, args.interval, show_footer=False))
        sys.stdout.flush()
        return

    use_alt = not args.no_alt_screen
    try:
        if use_alt:
            sys.stdout.write(ALT_SCREEN_ON)
        sys.stdout.write(HIDE_CURSOR)
        sys.stdout.flush()

        while True:
            frame = render_to_buffer(args.compact, args.interval, show_footer=True)
            # One atomic write per frame: clear → frame → flush
            if use_alt:
                # Alt-screen: home + frame + clear-below
                sys.stdout.write(HOME + frame + CLEAR_BELOW)
            else:
                # Main screen: full clear then frame
                sys.stdout.write(CLEAR + frame)
            sys.stdout.flush()
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write(SHOW_CURSOR)
        if use_alt:
            sys.stdout.write(ALT_SCREEN_OFF)
        sys.stdout.flush()
        print(f"{DIM}bye.{RESET}")


if __name__ == "__main__":
    main()
