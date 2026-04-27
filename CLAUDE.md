# sutra-os

Single AI orchestrator for managing multiple Claude Code agents. You're working inside the orchestrator codebase itself.

## CRITICAL: If You Are Sutra (the orchestrator agent)

You dispatch to other agents via **curl only**. Never use SendMessage or Agent tools — they spawn new subprocesses and don't reach running agents.

```bash
# Discover agents
curl -s http://localhost:${SUTRA_PORT:-8900}/api/agents | python3 -c "import sys,json; [print(f\"{a['name']} [{a['status']}]\") for a in json.load(sys.stdin)['agents']]"

# Observe what an agent did (BEFORE asking it)
curl -s http://localhost:${SUTRA_PORT:-8900}/api/agents/AGENT_ID/recent

# Dispatch to an agent
curl -s -X POST http://localhost:${SUTRA_PORT:-8900}/api/orchestrate \
  -H "Content-Type: application/json" \
  -d '{"agent":"NAME","instruction":"..."}'
```

If you find yourself narrating what you would do instead of running curl — STOP. Execute the curl command.

## Quick Start

```bash
./start.sh
# Open http://localhost:8900
```

## Architecture

```
server/bridge.py          — HTTP API server (port 8900)
server/process_manager.py — Claude CLI subprocess spawning (stream-json)
server/session_manager.py — Session reconciliation (DB ↔ filesystem)
server/db.py              — SQLite (data/agent-chat.db)
server/heartbeat.py       — Worker status + report format
server/cost_tracker.py    — Cost aggregation
server/cost_routes.py     — /api/usage endpoint
server/router.py          — Complexity routing (UNWIRED)
server/rate_limiter.py    — Rate limit backoff (UNWIRED)
server/schema.py          — Universal Turn dataclass (UNWIRED)
server/session_writer.py  — JSONL append (UNWIRED)
server/adapters/          — Claude CLI + Ollama adapters (UNWIRED)
server/voice/             — Porcupine + Whisper + TTS (STANDALONE)
web/index.html            — Full SPA, no build step
```

## Key Rules

- **No PTY/terminal emulation.** Everything is structured JSON via `claude --print --output-format stream-json --verbose`.
- **Observability without tokens.** Hooks and signal files (in `data/signals/`), not the orchestrator reading agent output.
- **Permissive by default, git for safety.** Agents can do anything non-destructive. Workspaces are git-backed sandboxes inside `$SUTRA_PROJECT_ROOT`.
- **Lucide icons, never emojis** in the UI.

## Code Conventions

- Python: small modules, prefer composition over inheritance, type-hint at module boundaries (not everywhere).
- JS: vanilla, no build step. The SPA is one HTML file plus `web/lib/*.js`.
- HTML: minimal templates, dark mode default, light mode tokenized via `body.light-mode`.
- SQL: schema in `server/schema.sql`; migrations in `server/db.py:init_db()`.

## Files Touched Policy

- `data/` is gitignored — runtime state, never commit.
- `web/index.html` is the main SPA — single file, ~7000 lines. Edit in place; no build step.
- `web/agent-dispatch-ui/01-21/` are design exploration wireframes. Reference, don't ship behavior.
- `server/voice/` is standalone — runs separately from the main server.

## Security Policy

- Never log secret values. Use variable NAMES only.
- Never commit `.env`.
- Never expose API keys or tokens in code, comments, or examples.
- When in doubt, ask before executing destructive operations.

## API Endpoints

### Agents
- `GET /api/agents` — List all agents
- `POST /api/agents` — Create agent
- `PUT /api/agents/{id}` — Update agent
- `DELETE /api/agents/{id}` — Delete agent
- `GET /api/agents/{id}/context` — Context window %
- `GET /api/agents/{id}/recent` — Last N messages + errors
- `GET /api/agents/{id}/files` — Files touched in session
- `GET /api/agents/{id}/sessions` — Per-agent session timeline (DAW blocks)
- `POST /api/agents/{id}/cancel` — Cancel running dispatch
- `POST /api/agents/{id}/reset` — Spoof or fresh-start a session (streams progress to /api/signals)

### Messages
- `GET /api/threads/{id}/messages` — Get messages
- `POST /api/threads/{id}/messages` — Send message

### Orchestration
- `POST /api/orchestrate` — Sutra sends instruction to agent (permission-gated)

### Sessions
- `GET /api/session-files?agent_id=` — List session JSONL files
- `GET /api/session-file/{id}` — Serve raw JSONL

### Debug / Observability
- `GET /api/debug` — Raw system state
- `GET /api/signals` — Recent tool + reset_phase signals
- `GET /api/usage` — Cost tracking

## Database

SQLite at `data/agent-chat.db`. Schema in `server/schema.sql`. Migrations run on startup in `server/db.py`.

Reset: delete `data/agent-chat.db` and restart.
