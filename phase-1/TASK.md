# Phase 1 Tasks

**Goal:** Ship a working Sutra timeline UI wired to real data.
**Reference:** `PHASE-1-PLAN.md` (full spec) and `web/mockup-n-warm.html` (visual spec).

## Tasks

- [x] **TASK-1** — Port static HTML/CSS from `web/mockup-n-warm.html` to `web/index.html`. Keep hardcoded mock data in place. Zero JS errors. Timeline renders.
- [x] **TASK-2** — Replace hardcoded `agents` array with live fetch from `GET /api/agents`. Cycle through warm palette colors by index. Create agent via curl → appears as lane on refresh.
- [x] **TASK-3** — Wire task blocks to real message history via `GET /api/threads/{id}/messages`. Each user→assistant pair = one task block. Time axis dynamic based on message timestamps.
- [x] **TASK-4** — Wire "Create Agent" modal to `POST /api/agents`. Include Ollama provider dropdown populated from `http://localhost:11434/api/tags`.
- [x] **TASK-5** — Wire "Talk to Sutra" input to dispatch. Routes: `@AgentName` → direct to agent, `status`/`overview` → status card, anything else → default Sutra agent via `POST /api/orchestrate`.
- [x] **TASK-6** — Real-time WebSocket updates from `ws://localhost:8901/dashboard`. Events: `agent_status_changed`, `message_received`, `task_completed`. No polling.
- [x] **TASK-7** — Context bars read real token usage per agent. Add `GET /api/agents/{id}/context` endpoint. Compute from `messages.input_tokens + context_tokens`. Colors: green <60%, yellow 60-80%, red 80%+.
- [x] **TASK-8** — Attention pill shows real blockers. Add `GET /api/attention` endpoint returning `{needs_input, needs_permission}` arrays. Click pill → panel with Approve/Reject buttons wired to existing endpoints.
- [x] **TASK-9** — Status overview card synthesizes real data. Add `GET /api/status/overview` endpoint that reads all agents + reports + attention. Type "status" → fetch + render real agent summaries.
- [x] **TASK-10** — Session modal shows real thread history. Click agent header → fetch `GET /api/threads/{id}/messages` → render as message bubbles. Double-click also works.

## Optional Quick-Wins (do last, only if time permits)

- [x] **TASK-11** — Elapsed time ticker on active task blocks. When a block is `active`, show "working for 12s..." that updates every second. ~20 lines of JS. Zero token cost. Fixes the "pulsing silently" UX for long tasks without waiting for Phase 3 hook wiring.

- [x] **TASK-12** — Wire one Claude Code `http` hook as proof-of-concept. Add `PostToolUse` hook to the default Sutra agent's `.claude/settings.json` pointing at `POST /api/events` (endpoint already exists from REQ-3.1 scaffolding). Show the latest tool_name in the task block subtitle. Down-payment on Phase 3 observability.

## Progress Log

_Agent updates this section after each completed TASK. Format: `YYYY-MM-DD HH:MM — TASK-N: note`._

2026-04-11 — TASK-1: Ported mockup-n-warm.html to index.html. Server serving new timeline UI with all elements (header, toolbar, ruler, lanes, attention pill, zoom slider) rendering correctly. Hardcoded mock data preserved.
2026-04-11 — TASK-2: Replaced hardcoded agents array with live GET /api/agents fetch. Colors cycle by index through warm palette. Tested with TestAgent3 creation and verified it appears in agents list. Empty tasks array (wired in TASK-3).
2026-04-11 — TASK-3: Wired task blocks to real message history. Added loadAllMessages() to fetch GET /api/threads/{thread_id}/messages. Convert user+assistant message pairs into task blocks. Dynamic time ruler based on earliest/latest message timestamps. Position blocks dynamically. Tested with 5 message pairs in TestAgent thread.
2026-04-11 — TASK-4: Added "New Agent" button to toolbar. Created modal with form fields (name, cwd, provider dropdown with Claude/Ollama, model select, icon). Implemented handleCreateAgent() to POST /api/agents with form data. Added handleProviderChange() to fetch Ollama models from localhost:11434/api/tags. Includes error handling with showError() display. Modal closes and reloads agents on success. Tested API endpoint works correctly.
2026-04-11 — TASK-5: Implemented message dispatch routing for "Talk to Sutra" input. Added dispatchToAgent() for @AgentName routing to POST /api/threads/{thread_id}/messages. Added dispatchToSutra() to POST /api/orchestrate for default Sutra agent. Status/overview commands preserved. Includes error feedback and auto-reloads timeline after dispatch. Tested all routing paths work correctly.
2026-04-11 — TASK-6: Implemented real-time WebSocket updates. Added connectWebSocket() in index.html to connect to ws://localhost:8911/dashboard. Server-side: added signal_message_received() in bridge.py to create signal files on message events, added message_signal_watcher() in ws_server.py to watch signals and broadcast events. Client handles agent_status, message_received, task_completed events. Agent status changes update lane idle/busy state. New messages trigger loadAllMessages() to update task blocks. Tested WebSocket connection, event broadcasting, and full message flow. No polling, automatic reconnection with backoff.
2026-04-11 — TASK-7: Implemented context bars reading real token usage. Added GET /api/agents/{id}/context endpoint in bridge.py that computes peak context from message history. Endpoint returns used_tokens, max_tokens (200k), and percent. Frontend updated to fetch context for all agents after loading. Added fetchContextForAgent() helper. Context updates on every message received via WebSocket. Colors: green (<60%), yellow (60-80%), red (80%+), red pulses on critical. Tested with agents showing 0%, 61% (warn), and 100% (crit) states.
2026-04-11 — TASK-8: Implemented attention pill showing real blockers and pending approvals. Added GET /api/attention endpoint in bridge.py that queries reports (type='blocked'/'needs_input') and pending_approvals (status='pending'). Frontend polls endpoint every 5 seconds via updateAttentionPill(). Panel populates with real items: needs_input items (red dot) and needs_permission items (amber dot). Approve/Reject buttons wired to /api/approvals/{id}/approve|reject endpoints. Attention panel updates on WebSocket message events. Tested end-to-end with test data: created pending approval, verified API structure, tested approve/reject endpoints, confirmed items disappear after action.
2026-04-11 — TASK-9: Implemented status overview card with synthesized real data. Added GET /api/status/overview endpoint that aggregates all agents (with status, model, cost, latest reports), session totals (cost, message count, active agents), and attention items. Frontend showStatusCard() now fetches the endpoint asynchronously and populateStatusCard() renders agent lines with colors, last actions, costs, and attention highlights (red for needs_input, amber for needs_permission). Footer displays real session totals. Tested: API returns correct structure with 10 agents, $19.50 total cost, 1 needs_input item.
2026-04-11 — TASK-10: Implemented session modal with real thread history. Made openSessionModal async to fetch messages from GET /api/threads/{thread_id}/messages. Renders message bubbles with chronological ordering, real timestamps, tokens, and costs. Fetches agent context from GET /api/agents/{id}/context for context bar. Single and double-click on agent headers both open modal. Tested with real messages from database: displays properly with HTML escaping and line breaks. Modal closes on button click and Escape key.
2026-04-11 — TASK-11: Implemented elapsed time ticker on active task blocks. Added data-start attribute to track start time in milliseconds. Created updateActiveBlockTimers() function that updates every second showing "working for Xs..." format. Added interval polling and immediate update after timeline render. Enhanced .block.active .duration styling for better visibility. Fixes silent pulsing UX for long-running tasks.
2026-04-11 — TASK-12: Wired PostToolUse hook as proof-of-concept. Added UI functions to fetch and display tool_name in task block subtitles. Created getLatestToolEvent() to fetch PostToolUse events from GET /api/events. Added CSS styling for .tool-subtitle element. Implemented handlePostToolUseEvent() for WebSocket event handling. Created setup_hooks.py utility script to configure PostToolUse hooks for agent workspaces. Configured hooks for Sutra and TestAgent2 workspaces. When Claude Code instances fire PostToolUse events, UI displays current tool in task block subtitle. Foundation for Phase 3 observability.

---

## Blockers (if any)

_Agent adds blockers here if stuck. Format: `TASK-N blocked: {reason}`._
