# Sutra

A local-first AI orchestrator for managing multiple Claude Code agents. One entry point, ambient awareness, automatic context management.

## What It Does

Sutra is a single orchestrator that dispatches work to sandboxed Claude Code agents, monitors their progress in real-time, and manages their context windows automatically. You talk to Sutra; Sutra handles the rest.

```
You ──> Sutra (orchestrator) ──> Agent A (LoveNotes)
                              ──> Agent B (GEOINT)
                              ──> Agent C (ContentWriter)
                              ──> Agent D (HG-POV)
```

## Quick Start

```bash
git clone https://github.com/ckelimarks/sutra-build.git
cd sutra-build
./start.sh
```

Open http://localhost:8900

## Setup

1. Python 3.8+ required
2. `pip install websockets psutil` (psutil optional)
3. Claude Code CLI must be installed and authenticated
4. Continuum (optional): install for session compression on auto-reset
5. Copy `CONTEXT-PAYLOAD.md` to personal-os root (read by `heartbeat.py` on every dispatch)

> **CONTEXT-PAYLOAD.md** lives at the personal-os root directory (`../../CONTEXT-PAYLOAD.md` relative to sutra-build). It is read by `heartbeat.py` on every dispatch and injected into the system prompt. Should contain current priorities, blockers, and project status.

## System Architecture

```
                    ┌─────────────────────────────────────────┐
                    │              BROWSER UI                  │
                    │                                         │
                    │  ┌──────────┐ ┌──────┐ ┌──────────┐   │
                    │  │ Timeline │ │ Chat │ │ Terminal │   │
                    │  │ (DAW)    │ │      │ │ (xterm)  │   │
                    │  └──────────┘ └──────┘ └──────────┘   │
                    │         │         │          │         │
                    │    ┌────┴─────────┴──────────┘         │
                    │    │  Drawer (Thread/Files/Tokens)      │
                    │    │  Debug Panel (DBG)                 │
                    │    │  @Target Menu                      │
                    │    └───────────────────────────────     │
                    └─────────────┬───────────────────────────┘
                                  │ HTTP + WebSocket
                    ┌─────────────┴───────────────────────────┐
                    │           SERVER LAYER                   │
                    │                                         │
                    │  bridge.py (:8900)     ws_server.py     │
                    │  ├─ REST API           (:8901)          │
                    │  ├─ Orchestrate        ├─ Dashboard WS  │
                    │  ├─ Auto-reset         └─ Global PTY    │
                    │  ├─ Stream-JSON parse                   │
                    │  └─ Tool signals                        │
                    │                                         │
                    │  ┌──────────────────────────────────┐   │
                    │  │        CONTEXT MANAGEMENT        │   │
                    │  │                                  │   │
                    │  │  Turn 80 → Auto-save state.md    │   │
                    │  │         → Git commit             │   │
                    │  │         → Spoof (Continuum)      │   │
                    │  │         → Resume compressed      │   │
                    │  │         → System prompt fresh     │   │
                    │  │                                  │   │
                    │  │  Per dispatch:                   │   │
                    │  │    CONTEXT-PAYLOAD.md injected   │   │
                    │  │    state.md injected             │   │
                    │  │    Behavioral anchor prepended   │   │
                    │  └──────────────────────────────────┘   │
                    └─────────────┬───────────────────────────┘
                                  │ claude --print --output-format stream-json
                    ┌─────────────┴───────────────────────────┐
                    │          AGENT SUBPROCESSES              │
                    │                                         │
                    │  ┌────────┐ ┌────────┐ ┌────────┐      │
                    │  │ Sutra  │ │ LoveN. │ │ GEOINT │ ...  │
                    │  │ (orch) │ │(worker)│ │(worker)│      │
                    │  └────────┘ └────────┘ └────────┘      │
                    │       │                                 │
                    │       │ curl /api/orchestrate           │
                    │       └──────────────────────>          │
                    └─────────────────────────────────────────┘
                                  │
                    ┌─────────────┴───────────────────────────┐
                    │           DATA LAYER                     │
                    │                                         │
                    │  SQLite (index)     Git (history)       │
                    │  ├─ agents          ├─ [Agent] /save    │
                    │  ├─ threads         ├─ [Agent] /auto-   │
                    │  ├─ messages        │    save            │
                    │  └─ events          └─ commits          │
                    │                                         │
                    │  Filesystem (content)                   │
                    │  ├─ data/agents/{name}/state.md         │
                    │  ├─ data/signals/*.signal               │
                    │  ├─ ~/.claude/projects/*/session.jsonl  │
                    │  └─ CONTEXT-PAYLOAD.md                  │
                    └─────────────────────────────────────────┘
```

## Request Lifecycle

1. User sends message via chat input or `curl`
2. `bridge.py` receives `POST /api/orchestrate` (for Sutra) or `POST /api/threads/{id}/messages` (direct)
3. Auto-reset check: if agent has 80+ assistant turns, save state + spoof + reset
4. Route instruction via `router.py` (complexity -> model selection)
5. Dispatch via `process_manager.py`: `claude --print --output-format stream-json --verbose`
6. NDJSON events parsed line-by-line: `tool_use` events -> signal files, `text` -> accumulated
7. On completion: response saved to DB + JSONL, agent status updated, WebSocket broadcast
8. UI polls `/api/signals` every 3s for live tool display

## Key Concepts

### Three Systems, One Job Each
- **SQLite** = the index (who exists, current status)
- **Git** = the history (what changed, when, by whom)
- **Filesystem** = the content (state.md, session JSONL, signals)

### Context Management (The Hard Problem)
Agents degrade after ~80 turns due to behavioral pattern accumulation — not context window size. The system automatically:
1. Counts assistant turns per agent
2. At 80 turns: saves state, spoofs session via Continuum, resumes compressed
3. System prompt re-injected with fresh CONTEXT-PAYLOAD.md + state.md
4. Behavioral anchor prepended to every orchestrator dispatch

### Dispatch Model
Agents run via `claude --print --output-format stream-json --verbose`. NDJSON events are parsed line-by-line for real-time tool call display. Sutra dispatches via `curl /api/orchestrate` (not SendMessage or Agent tools — those spawn new subprocesses and don't reach existing agents).

Agents in `Projects/prototypes/*` get `--dangerously-skip-permissions`. All others get explicit `--allowedTools`.

### Observability Without Tokens
- Tool signals written to disk during dispatch (zero-cost)
- `/api/agents/{id}/recent` returns last N messages + errors (no agent dispatch needed)
- Debug panel shows raw process state, token totals, costs
- System prompt says "OBSERVE BEFORE DISPATCHING"

## UI Views

| View | Purpose |
|------|---------|
| **Timeline** | DAW-style horizontal lanes. Blocks grow in real-time. Playhead advances. |
| **Chat** | Sidebar + thread + detail panel. Classic chat interface. |
| **Terminal** | Global zsh shell at project root via xterm.js. Persists across view switches. |
| **Session Viewer** | Standalone JSONL conversation viewer at `/session-viewer`. |

## Features

- Stream-JSON parsing with live tool call display (Bash: ls -la, Read: file.py)
- Thinking dots animation with tool streaming
- Cancel dispatch (Escape key → SIGTERM → graceful shutdown)
- Agent target menu (dropdown, not cycle)
- Files tab (modified/read, timestamps, click-to-open)
- Tokens tab (circle meter for context %, in/out totals)
- Sessions tab (browse all JSONL files, tagged CURRENT/SPOOFED)
- Light mode (warm/muted organic palette)
- Debug panel (costs, processes, rate limits, session detection)
- Color-coded agent names in message content
- Per-agent Lucide icons (hash-based assignment)
- Context bars on timeline lanes and chat sidebar

## File Structure

```
server/
  bridge.py              HTTP API + orchestration + auto-reset
  ws_server.py           WebSocket + global terminal PTY
  process_manager.py     Claude CLI dispatch (stream-json, Popen)
  heartbeat.py           System prompt generation + worker reports
  db.py                  SQLite operations
  session_manager.py     Session reconciliation (DB ↔ filesystem)
  router.py              Complexity-based model routing
  cost_tracker.py        Cost aggregation
  workspace.py           Git-backed workspace init

web/
  index.html             Main SPA (single file, no build step)
  session-viewer.html    Standalone session JSONL viewer

data/
  agent-chat.db          SQLite database
  agents/{name}/state.md Per-agent state snapshots
  signals/               Ephemeral tool signal files
  workspaces/{name}/     Git-backed agent sandboxes
```

## Dependencies

- Python 3.8+
- Claude Code CLI (authenticated)
- Continuum (optional, for session spoofing): `~/.continuum/.install_path`
- psutil (optional, for CPU/memory in debug panel)

## License

MIT
