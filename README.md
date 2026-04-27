# sutra-os

A local-first AI orchestrator for managing multiple Claude Code agents. One entry point, ambient awareness, automatic context management.

## What it does

You talk to **Sutra** — one orchestrator. Sutra dispatches work to sandboxed Claude Code agents, monitors their progress in real time on a DAW-style timeline, and manages their context windows automatically. Each Claude session shows up as a block on the timeline; when context gets too full, Sutra spoofs the session (compresses history into a fresh start) and the new block opens with a visible seam linking it to its parent.

Run as many specialized agents as you like — a **CPA**, a **Legal** researcher, a **Designer**, a **Marketing** writer, a **VirtualAdmin** — each in their own sandboxed working directory. They report back through hooks (zero-cost observability), and you see everything from a single browser tab.

```
You ──> Sutra (orchestrator) ──> Agent A (CPA)
                              ──> Agent B (Legal)
                              ──> Agent C (Designer)
                              ──> Agent D (Marketing)
```

## Quick start

```bash
git clone https://github.com/ckelimarks/sutra-os.git
cd sutra-os
cp .env.example .env
# Edit .env to set SUTRA_PROJECT_ROOT to a directory where you want
# agents to work. Example: ~/Code/my-project

pip install -r requirements.txt
./start.sh
```

Open http://localhost:8900

You'll need:
- Python 3.8+
- Claude Code CLI installed and authenticated (`claude auth login`)
- (Optional) [Continuum](https://github.com/your-org/continuum) for session compression on auto-reset

## Architecture

```
                    ┌─────────────────────────────────────────┐
                    │              BROWSER UI                  │
                    │                                         │
                    │  Timeline (DAW)  Chat  Terminal  Ideas  │
                    │  Drawer (Thread/Files/Tokens)           │
                    └─────────────┬───────────────────────────┘
                                  │ HTTP + WebSocket
                    ┌─────────────┴───────────────────────────┐
                    │           SERVER LAYER                  │
                    │  bridge.py (:8900)     ws_server.py     │
                    │  ├─ REST API           (:8901)          │
                    │  ├─ /api/orchestrate   ├─ Dashboard WS  │
                    │  ├─ Auto-reset         └─ Global PTY    │
                    │  ├─ Stream-JSON parse                   │
                    │  └─ Tool/reset signals                  │
                    └─────────────┬───────────────────────────┘
                                  │ claude --print --output-format stream-json
                    ┌─────────────┴───────────────────────────┐
                    │          AGENT SUBPROCESSES             │
                    │  ┌────────┐ ┌────────┐ ┌────────┐       │
                    │  │ Sutra  │ │ Agent  │ │ Agent  │  ...  │
                    │  │ (orch) │ │   A    │ │   B    │       │
                    │  └────────┘ └────────┘ └────────┘       │
                    └─────────────┬───────────────────────────┘
                                  │
                    ┌─────────────┴───────────────────────────┐
                    │           DATA LAYER                    │
                    │  SQLite (index)     Git (history)       │
                    │  Filesystem (state.md, signals, JSONL)  │
                    └─────────────────────────────────────────┘
```

## Configuration

Set in `.env` or shell:

| Variable | Default | Purpose |
|---|---|---|
| `SUTRA_PROJECT_ROOT` | `~/sutra-project` | Where agent workspaces live and where the orchestrator looks for `CONTEXT.md`, `TASKS.md`, etc. |
| `SUTRA_PORT` | `8900` | HTTP API port |
| `SUTRA_WS_PORT` | `8901` | WebSocket port |

## Design Philosophy

A few principles that shape the codebase:

- **Observability without tokens.** Hooks and signal files surface what agents are doing without the orchestrator reading their output. Tool calls, file edits, and reset progress all stream through `data/signals/` to a polling `/api/signals` endpoint — zero context cost.
- **Permissive by default, git for safety.** Agents can do anything non-destructive. Workspaces are git-backed sandboxes. If something goes wrong, roll back.
- **Compression without reduction.** When a session approaches its context limit, it gets spoofed (compressed via an LLM into a fresh narrative) rather than truncated. Identity and decisions persist; debugging dead-ends drop.
- **Sessions are blocks.** The lane timeline visualizes each Claude session as a region — like an audio clip in a DAW. A spoof closes one region and opens a new one with a visible seam connecting them. You can scroll back through the day's session lineage at a glance.
- **Structured JSON, no PTY.** Agents run via `claude --print --output-format stream-json --verbose` and emit NDJSON events. No terminal emulation, no fragile screen-scraping.

## Status

Early open-source release. The orchestration loop, session timeline, reset visibility, and DAW-style block view all work. Several modules in `server/` are scaffolded but not yet wired (router, rate_limiter, schema, session_writer, adapters/*, voice/*) — see the comments in those files.

Expect rough edges. PRs and issues welcome.

## License

MIT — see `LICENSE`.
