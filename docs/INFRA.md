# INFRA.md — Sutra Build

> **SECURITY:** Never log actual secret values. Use variable NAMES only.
> Last updated: 2026-04-16

## Servers

| Service | Port | Command | Purpose |
|---------|------|---------|---------|
| HTTP API | 8900 | `python3 server/bridge.py` | All REST endpoints, ThreadingHTTPServer |
| WebSocket | 8901 | `python3 server/ws_server.py` | Dashboard events, global terminal PTY |

**Start both:** `./start.sh`

## Database

- **Path:** `data/agent-chat.db` (SQLite, auto-creates)
- **Schema:** `server/schema.sql` + migrations in `server/db.py`
- **Reset:** delete file and restart

## Context Management (THE CRITICAL SYSTEM)

### Context Pressure Flagging — REQ-6.2 (2026-04-20, human-in-loop variant)
**Primary trigger: token-based at 70% context.** Catches the "few turns, huge tokens" case that turn-counting misses. Does NOT auto-execute — flags for user review via the existing reset modal.

1. **Every dispatch via `pm.send_message()`** → `_maybe_auto_spoof(config)` runs first
2. **Read session JSONL** → sum last `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`
3. **Compare to model max** → 200K (sonnet/haiku) or 1M (opus)
4. **If ≥ 70%** → set `notification = reset_pending:{json}` on the agent with `reason='context_pressure'`
5. **UI picks up the notification** → existing reset modal pops up with options (spoof / fresh / inject docs / steering prompt)
6. **User picks an action** → `POST /api/agents/{id}/reset` handles the actual spoof/fresh
7. **Dispatch proceeds** normally (not blocked by the flag — user can still send messages)

**De-duplication:** If the agent already has a `reset_pending:` notification, `_maybe_auto_spoof` returns silently (no re-flagging on every dispatch while modal is pending).

**Notification payload:**
```json
{
  "reason": "context_pressure",
  "context_used": 143208,
  "context_max": 200000,
  "context_pct": 71.6,
  "threshold_pct": 70,
  "turn_count": 143208,       // backward-compat (modal reads this)
  "threshold": 140000          // backward-compat
}
```

**UI feedback:** `CompactionWarning` signal emitted alongside the notification so the lane shows a warning pulse.

**Location:** `server/process_manager.py:_maybe_auto_spoof()`. Helpers: `_get_last_usage_tokens()`, `_set_reset_notification()`, `_has_pending_reset()`.

**Turn-based flag (legacy, still runs):**
- At 80 DB-assistant-turns → `bridge.py` writes `data/agents/{name}/state.md` + git commit + sets `reset_pending` notification
- Fires alongside the token-based flag — either trigger raises the same modal

### Reset Progress Visibility — Lane Overlay (2026-04-26)
**Problem:** `POST /api/agents/{id}/reset` ran `spoof_tool.py` synchronously with `subprocess.run(capture_output=True, timeout=120)`. The HTTP request blocked for up to 2 minutes with no intermediate output. From the UI, "Resetting session..." toast → silence → final result. No way to tell if compression was running, hung, or failed.

**Fix:** instrument the reset handler to emit phase signals through the existing `/api/signals` channel and render them as a thin lane overlay.

**Signal contract** (written to `data/signals/reset_<agent_id>_<ts>.signal`, picked up by `/api/signals`):
```json
{
  "agent_id": "...",
  "kind": "reset_phase",
  "phase": "starting | spoof_starting | spoof_running | spoof_log | spoof_success | spoof_failed | spoof_no_session | fresh | complete",
  "detail": "human-readable line",
  "timestamp": 1745700000.0,
  "ok": true | false  // present on terminal phases
}
```

**Phase sequence:**
1. `starting` — fired immediately on entry to `/reset`. Detail: mode + doc count + trigger source
2. `spoof_starting` — fired before `Popen(spoof_tool.py)`. Detail: old session id prefix
3. `spoof_running` — heartbeat every 2s from a daemon thread while the subprocess is alive. Detail: `Compressing... {elapsed}s elapsed`
4. `spoof_log` — one per non-empty stdout line from `spoof_tool.py` (now streamed via `Popen` instead of captured)
5. Terminal: `spoof_success` (with new session id) | `spoof_failed` (with stderr) | `spoof_no_session` | `fresh` (mode='fresh' branch)
6. `complete` — final summary, `ok=true` for success/fresh, `ok=false` for failure-fallback. UI uses this to switch the overlay to green/red and start the 3s fade.

**Files touched:**
- `server/bridge.py` — added `emit_reset_signal()` helper (alongside the other signal helpers near the top of the file). Reset handler at `/api/agents/{id}/reset` now uses `Popen` instead of `subprocess.run`, with a heartbeat thread and per-line stdout emission. Final `complete` signal emitted just before `send_json`.
- `web/index.html` —
  - CSS block `.lane-reset-overlay` (animated stripe + success/error states)
  - JS: `applyResetSignal()` renders/updates the overlay; `window._activeResets` Set keeps the signal poller awake during reset (the agent isn't `busy` while spoofing)
  - `pollToolSignals()` filters `kind === 'reset_phase'` out of the tool-subtitle grouping
  - `executeReset()` no longer hides the modal silently — it seeds an immediate `starting` overlay client-side, kicks `pollToolSignals()`, and re-polls right after `renderAgents()` so the terminal state lands on the rebuilt lane DOM
  - Signal poll cadence dropped from 3s → 1.5s and now also fires when `_activeResets.size > 0`

**Why disk-signal channel (not WebSocket):** zero new infrastructure. `/api/signals` is already polled, already cleaned up (5min TTL), and already handles tool-call streaming for live UI. New phase signals reuse all of it.

**Rollback:** the change is two files, all additive except for the spoof subprocess block. To revert in one commit:
```bash
git log --oneline server/bridge.py web/index.html | head
git revert <commit-sha>
```
Or manually:
- `server/bridge.py` — remove `emit_reset_signal()` def; replace the `Popen` + heartbeat-thread + line-streaming block in the reset handler with the prior `subprocess.run([...], capture_output=True, text=True, timeout=120)` form (the `result.returncode` / `result.stdout` / `result.stderr` parsing is unchanged in shape — the diff is purely in how output is collected). Remove the four `emit_reset_signal(...)` call sites (`starting`, `spoof_starting`, terminal phase, `complete`).
- `web/index.html` — remove the `.lane-reset-overlay` CSS block, the `applyResetSignal()` function and `_activeResets`/`_resetSignalState` globals, the `kind === 'reset_phase'` filter inside `pollToolSignals`, and revert `executeReset()` to the toast-on-completion form. Restore the 3s poll interval and the busy-only predicate in `bootPolling()`.

**Risk surface:** the reset handler still has the same 120s timeout and same DB writes. Failure modes are unchanged — only the UX during the wait differs. If the heartbeat thread or signal writes fail, they're swallowed (`logger.debug`) and the reset still completes.

### Persistent Session-ID Chip on Lane (2026-04-26)
**Problem:** the reset overlay shows the new session id in its `DONE` line but fades after 3s. After that the user has no quick way to verify "what session am I currently in?" without opening the Sessions tab in the drawer.

**Fix:** added an always-visible `.lane-session-chip` on each lane label showing `s:<first-8-chars>` of the agent's active `threads.session_id`. Source of truth: `/api/agents` already returns `session_id` from the join with `threads`. Click to copy full id to clipboard (`copySessionId(agentId, sessionId)`).

**Reset feedback:** when `applyResetSignal` receives a successful terminal phase, it:
- Updates the chip text to the new session id immediately (don't wait for the next `/api/agents` poll)
- Adds `.flash-success` class — green tint + " ← compressed" suffix + pulse animation for 4s

**Files touched:**
- `web/index.html` — `.lane-session-chip` CSS block; `copySessionId()` function; chip element added to lane HTML in `renderAgents()` (placed as a sibling of `.lane-actions` so it stays visible — the actions div is hover-only); flash-success branch added to `applyResetSignal()` terminal-phase block.

**Rollback:**
- `web/index.html` — remove the `.lane-session-chip` CSS rules, the `copySessionId()` function, the chip `<span>` from the lane HTML in `renderAgents()`, and the `if (signal.ok) { ... flash-success ... }` block inside the terminal-phase branch of `applyResetSignal()`.

### System Prompt Injection (per dispatch)
Every orchestrator dispatch gets:
- Full Sutra identity + capabilities from `heartbeat.py:get_orchestrator_system_prompt()`
- **CONTEXT-PAYLOAD.md** → live priorities, blockers, project status (read from disk each time)
- **state.md** → agent's last saved state
- **Worker status** → heartbeat data from all agents
- **Behavioral anchor** → `[DISPATCH CONTEXT]` block prepended to instruction with curl syntax

### Why This Exists
- Context rot degrades behavior even at 15% usage (156k/1M)
- Root cause: behavioral pattern accumulation (not token count)
- System prompt loses influence against 100+ turns of mixed good/bad behavior
- Auto-reset at 80 turns prevents drift before it compounds
- Spoof with steering drops hallucinated turns, preserves good patterns

## Agent Dispatch

- **Mode:** `claude --print --output-format stream-json --verbose`
- **Process:** `subprocess.Popen` with NDJSON line-by-line parsing
- **Session resume:** `--resume {session_id}` if thread has session_id
- **Permissions:**
  - `Projects/prototypes/*`: `--dangerously-skip-permissions`
  - All other: explicit `--allowedTools` list
- **Cancel:** SIGTERM → wait 3s → SIGKILL
- **Tool signals:** written to `data/signals/` as JSON, polled by UI every 3s

## Key Endpoints

### Agents
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/agents` | List all agents |
| POST | `/api/agents` | Create agent |
| GET | `/api/agents/{id}/context` | Context % from session JSONL (last usage, not max) |
| GET | `/api/agents/{id}/recent` | Last N messages + signals + errors (observability) |
| GET | `/api/agents/{id}/files` | Files touched in current session |
| POST | `/api/agents/{id}/cancel` | SIGTERM the running dispatch |

### Threads
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/threads/{id}/messages` | Get messages |
| POST | `/api/threads/{id}/messages` | Send message (async, returns 202) |

### Orchestration
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/orchestrate` | Dispatch instruction to agent (permission-gated) |

### Sessions
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/session-files?agent_id=X` | List all JSONL sessions for agent |
| GET | `/api/session-file/{id}?cwd=X` | Serve raw JSONL content |
| GET | `/session-viewer` | Standalone session JSONL viewer |

### System
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/debug` | Raw system state: processes, tokens, costs, sessions |
| GET | `/api/signals` | Recent tool signals (60s TTL) |
| POST | `/api/open-file` | Open file in macOS default app |

For complete route map, see `bridge.py` `do_GET` and `do_POST` handlers.

## UI Views

| View | Access | Purpose |
|------|--------|---------|
| **Timeline** | Default | DAW-style horizontal lanes, blocks grow in real-time |
| **Chat** | Header tab | Sidebar + thread + detail panel (Files/Tokens/Sessions) |
| **Terminal** | Header tab | Global zsh PTY at project root via xterm.js |
| **Session Viewer** | `/session-viewer` | Standalone JSONL conversation viewer |
| **Debug Panel** | DBG button | Raw process state, token totals, agent costs |

## Key Directories

| Path | Purpose |
|------|---------|
| `data/agent-chat.db` | Main database |
| `data/signals/` | Tool signal files (ephemeral). Polled by UI every 3s. TTL 60s for display, cleaned up after 5min. |
| `data/agents/{name}/state.md` | Per-agent state snapshots |
| `../../CONTEXT-PAYLOAD.md` | Live priorities (personal-os root), injected into Sutra system prompt per dispatch |
| `data/workspaces/{name}/` | Git-backed agent workspaces |
| `web/index.html` | Main SPA (single file, no build step) |
| `web/session-viewer.html` | Standalone session viewer |

## Environment Variables

| Var | Default | Purpose |
|-----|---------|---------|
| `SUTRA_PORT` | 8900 | HTTP server port |
| `SUTRA_WS_PORT` | 8901 | WebSocket server port |
| `CLAUDE_AGENT_NAME` | (per agent) | Set on dispatched agents |

## GitHub

- **Repo:** github.com/ckelimarks/sutra-build
- **Branches:** `main` (stable). Check `git branch` for current work.

## Gotchas (DO NOT REPEAT)

1. **Port is 8900/8901** — old code says 8890 or 8910. Current is 8900/8901.
2. **Server restart resets all statuses to `offline`** — recovers on next dispatch. Status is set to offline on startup via db reset. Self-corrects to busy/online on next dispatch. No manual recovery needed.
3. **Session poisoning** → agent hallucinating tool success. Fix: auto-reset (now automatic at 80 turns).
4. **CC auto-compaction at ~80%** — silent, lossy. Our auto-reset at 80 turns triggers BEFORE this.
5. **Context % reads session JSONL, not DB** — DB has all sessions mixed. JSONL has current only. Uses LAST usage entry, not MAX.
6. **`forEach` + `continue` = JS crash** — use `return` inside forEach.
7. **stream-json events** — `system`, `assistant` (content blocks), `rate_limit_event`, `result`.
8. **SendMessage/Agent tools don't reach Sutra API agents** — only `curl /api/orchestrate` works.
9. **busyPoll wipes thinking placeholder** — skip reload when thinking placeholder exists.
10. **Behavioral drift is turn-count, not token-count** — 100 turns at 15% context is worse than 20 turns at 40%.
11. **Spoof carries behavioral patterns** — steering prompt must explicitly say "drop hallucinated tool calls."
12. **`--append-system-prompt` on resume is correct** — CC re-sends system prompt per API call, doesn't accumulate in JSONL.
13. **New agents inherit stale session_id → "Process failed"** — Session recovery (`recover_agent_session`) can link a session_id whose JSONL doesn't exist in the new agent's cwd. `--resume` then fails with empty stderr → generic "Process failed". Fix (2026-04-18): added `Path(session_file).exists()` guard before linking + try/except around recovery block in bridge.py:1347. If you see "Process failed" on a new agent, check `threads.session_id` — set to NULL to start fresh.

## Voice Client (2026-04-19)

Local voice interface to Claude Code CLI via Porcupine wake word + Whisper STT + persistent Haiku session.

### Architecture

```
Porcupine wake word → mic record (silence detection 0.8s) → instant ack (pre-cached WAV)
  → local Whisper STT → claude --print --resume (persistent Haiku session) → macOS say TTS
```

### Files

| Path | Purpose |
|------|---------|
| `server/voice/voice_client.py` | Main client — wake word, recording, STT, LLM, TTS |
| `server/voice/config.py` | Configuration dataclass + env var loading |
| `server/voice/start.sh` | Launcher script |
| `data/.voice-session-id` | Persistent Haiku session ID (survives restarts) |

### How to Run

```bash
cd Projects/prototypes/sutra-build
source .env
python3 -m server.voice.voice_client              # full voice mode
python3 -m server.voice.voice_client --keyboard-only  # text mode
python3 -m server.voice.voice_client --orchestrator   # route through Sutra server
```

### Dependencies

| Package | Purpose | Install |
|---------|---------|---------|
| `pvporcupine` | Wake word detection | `pip install pvporcupine` |
| `pyaudio` | Mic input | `brew install portaudio && pip install pyaudio` |
| `whisper` | Local STT (OpenAI Whisper, runs on-device) | `pip install openai-whisper` |
| `piper` | TTS for ack phrases (pre-cached) | `brew install piper` |

### Environment Variables

| Var | Default | Purpose |
|-----|---------|---------|
| `PICOVOICE_API_KEY` | (required) | Porcupine wake word engine |
| `SUTRA_WAKE_WORD` | `computer` | Built-in Porcupine keyword |
| `SUTRA_AGENT` | `WorkerAgent` | Default agent for orchestrator mode |
| `SUTRA_URL` | `http://localhost:8900/api/orchestrate` | Orchestrator endpoint |
| `SUTRA_WHISPER_MODEL` | `base` | Whisper model size (tiny/base/small/medium/large) |
| `SUTRA_TTS` | `say` | TTS engine (piper/say/none) |
| `SUTRA_SAY_VOICE` | `Samantha` | macOS say voice |
| `SUTRA_PROJECT_CWD` | sutra-build root | Working directory for Claude sessions |

### Key Design Decisions

- **Persistent Haiku session** — `claude --print --model haiku --resume SESSION_ID`. Session ID saved to `data/.voice-session-id`. Reads CLAUDE.md, has conversation history. Resumes across restarts.
- **Pre-cached ack WAVs** — 6 acknowledgment phrases synthesized to WAV at startup (`/tmp/sutra-voice-acks/`). Instant `afplay` playback (~0ms) instead of runtime TTS synthesis.
- **macOS `say` for responses** — Piper sounds better but has 2-3s synthesis delay. `say` starts speaking within ~100ms. Piper reserved for pre-cached acks only.
- **Response cleaning** — `clean_for_speech()` strips markdown, code blocks, URLs, bullets before TTS. System prompt also instructs Haiku to never use markdown.
- **Silence detection** — RMS amplitude threshold (200) with 0.8s silence duration. Speech must start before silence timer activates.
- **Self-dispatch guard** — cannot dispatch to agent "Sutra" via orchestrator (empty response). Default agent is WorkerAgent.
- **stream-json requires --verbose** — `claude --print --output-format stream-json` fails without `--verbose` flag.

### Current Latency Profile

| Stage | Time |
|-------|------|
| Silence detection | 0.8s |
| Pre-cached ack plays | ~0ms |
| Whisper base transcription | 1.2-1.5s |
| Haiku response | 2-3s |
| macOS say starts speaking | ~100ms |
| **Total (end of speech → first words)** | **~4-5s** |

### Known Limitations

- Interrupt detection disabled — mic picks up speaker audio (echo cancellation needed, or headphones)
- Whisper `base` is slow (1.2s); Moonshine would be ~150ms
- RMS silence detection is crude; Silero VAD would be more accurate
- `pyaudio` required portaudio brew install; `sounddevice` would be simpler
- No asyncio pipeline — all stages run sequentially except ack playback
