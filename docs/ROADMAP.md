# Sutra Roadmap & Development Status

**Consolidated from:** PHASE-1-PLAN.md, TASK.md, and tactical feature plans

**Last updated:** 2026-04-21  
**Current focus:** Phases 1-3 active. Phase 0 complete.

---

## Status Overview

**Shipped (Phases 0-2 complete, Phase 3 partial):**
- All Phase 0 bugfixes (cost panel, queue, approval flow, home dashboard)
- All Phase 1 wiring (router, rate limiter, session writer, Ollama)
- All Phase 2 sandboxing (git workspaces, auto-commit, permission tiers, rollback)
- Most Phase 3 observability (hooks, reports with zoom, WebSocket dashboard, statusline)

**In Progress (Phase 3.5-3.7):**
- REQ-3.5 (Attention queue) — inbound priority sequencing
- REQ-3.6 (Inbound flow) — agent completions in conversation stream
- REQ-3.7 (Agent routing) — Sutra picks the agent, not just the model

**Next (Phases 4-6):**
- Phase 4: Compression and context intelligence (multi-store reads, synthesis logging, knowledge pipeline)
- Phase 5a: Basic input channels (PWA shipped, /sutra skill next)
- Phase 5b: Intelligent input channels (voice, digital twin bridge)
- Phase 6: Session resilience (restart, auto-spoof, orphan recovery, sutra-bypass)

---

## Phase 0: Fix What's Broken

**Status:** COMPLETE ✅  
**Gate:** Cost panel, home dashboard, instruction queue, approval flow all working.

| REQ | Title | Status | Shipped |
|-----|-------|--------|---------|
| 0.1 | Cost dashboard displays real data | DONE | 2026-04-08 |
| 0.2 | Home dashboard renders | DONE | 2026-04-08 |
| 0.3 | Instruction queue drains | DONE | 2026-04-08 |
| 0.4 | Supervised permission tier has approval flow | DONE | 2026-04-08 |

---

## Phase 1: Wire the Unwired

**Status:** COMPLETE ✅  
**Gate:** Router routes 3+ messages to different models. Rate limiter handles 429. Ollama works. Session JSONL exists.

| REQ | Title | Status | Shipped |
|-----|-------|--------|---------|
| 1.1 | Router integration (Haiku classifier, budget-aware) | DONE | 2026-04-08 |
| 1.1.1 | Routing feedback loop (force_model override, events) | DONE | 2026-04-08 |
| 1.2 | Rate limiter integration (429 detection, backoff, reroute) | DONE | 2026-04-08 |
| 1.3 | Universal session writer (dual SQLite+JSONL) | DONE | 2026-04-08 |
| 1.4 | Ollama adapter live path (provider field, dispatch) | DONE | 2026-04-08 |

---

## Phase 2: Sandboxed Agent Workspaces

**Status:** COMPLETE ✅  
**Gate:** Autonomous agent creates + auto-commits. Restricted agent read-only. Rollback works.

**Parallel with Phase 1 — No dependencies.**

| REQ | Title | Status | Shipped |
|-----|-------|--------|---------|
| 2.1 | Git-backed workspace initialization | DONE | 2026-04-08 |
| 2.2 | Auto-commit on task completion | DONE | 2026-04-08 |
| 2.3 | Permission tiers enforced via workspace settings.json | DONE | 2026-04-08 |
| 2.4 | Rollback capability (git revert, not reset) | DONE | 2026-04-08 |

---

## Phase 3: Observability Without Tokens

**Status:** IN PROGRESS (3/7 DONE)  
**Gate:** Dashboard live-updates via WebSocket. Events within 2s. Reports have 3 zoom layers.

**Depends on:** Phases 0 + 1 + 2

| REQ | Title | Status | Shipped | Notes |
|-----|-------|--------|---------|-------|
| 3.1 | Hook-based event capture | DONE | 2026-04-08 | PostToolUse, SubagentStart/Stop, PreCompact, Stop |
| 3.2 | Worker report protocol (summary/context/details) | DONE | 2026-04-08 | zoom=context\|details supported |
| 3.3 | Live dashboard (WebSocket, agent cards, timeline) | DONE | 2026-04-08 | ws://localhost:8891/dashboard |
| 3.4 | Statusline integration (agent count, cost, report) | DONE | 2026-04-21 | sutra_status.py, 5s refresh |
| 3.5 | Attention queue (priority-sorted items, "while you were away") | PENDING | — | Next in Phase 3.5 |
| 3.6 | Inbound flow (agent completions in conversation stream) | PENDING | — | Requires 3.5 first |
| 3.7 | Agent routing (Sutra picks agent, not just model) | PENDING | — | After 3.6 |

---

## Phase 4: Compression and Context Intelligence

**Status:** NOT STARTED  
**Gate:** Domain question uses knowledge base. Prior work uses Continuum. Capture in <60s. Synthesis log has pull_ids.

**Depends on:** Phases 1 + 3

### REQ-4.1: Sutra reads from all knowledge stores
- Loads worker report summaries, /fresh state, synthesis log on session start
- Queries knowledge base for domain questions
- Calls `cx retrieve` against Continuum for prior work
- Queries digital twin for page context
- **Status:** Not started. Deferred until Phase 3 complete.

### REQ-4.2: Automatic synthesis logging
- Wire `log_synthesis()` into Sutra's response path
- Log observations with pull_ids for "tell me more" follow-ups
- Rotate synthesis log when >1000 entries
- **Status:** Not started.

### REQ-4.3: Digital twin → knowledge pipeline
- Filesystem watcher on `.context/captures/`
- Explicit captures → knowledge base ingestion (sutra/vritti/bhashya)
- Dwell captures → Continuum corpus
- Dashboard "Captures" panel with promote/demote
- **Status:** Not started.

### REQ-4.4: Continuum auto-ingest on /fresh
- Post `ready_for_ingest` event on /fresh completion
- Batch ingest every 5 min or when agents idle
- Deduplicate concurrent requests
- Content available to `cx retrieve` within 5 min
- **Status:** Not started.

---

## Phase 5a: Basic Input Channels

**Status:** PARTIAL (1/2 DONE)  
**Gate:** PWA sends/receives over local WiFi. `/sutra` skill returns inline.

**Depends on:** Phase 1 only. Can ship independently.

| REQ | Title | Status | Shipped | Notes |
|-----|-------|--------|---------|-------|
| 5.2 | Mobile PWA (POST /api/sutra, token auth, installable) | DONE | 2026-04-21 | /mobile.html, manifest.json, service worker |
| 5.4 | Statusline /sutra skill (curl wrapper) | PENDING | — | Trivial after 5.2, execute when requested |

---

## Phase 5b: Intelligent Input Channels

**Status:** NOT STARTED  
**Gate:** Voice round-trip works end-to-end. Digital twin toggles Ollama/Sutra. Page context in responses.

**Depends on:** Phase 4

| REQ | Title | Status | Notes |
|-----|-------|--------|-------|
| 5.1 | Voice integration (wake word, STT, TTS) | NOT STARTED | Porcupine + Whisper + say/OpenAI TTS. Latency SLA <2s. |
| 5.1.1 | Voice latency SLA | NOT STARTED | Progress earcon if >500ms. |
| 5.3 | Digital twin bridge (Sutra mode toggle, page context) | NOT STARTED | Sidebar toggle, context payload to /api/sutra |

---

## Phase 6: Session Resilience

**Status:** PARTIAL (1/4 DONE)  
**Gate:** Kill-restart with continuity. Auto-spoof at 70%. sutra-bypass CLI works headless.

**Depends on:** Phases 1 + 2

| REQ | Title | Status | Shipped | Notes |
|-----|-------|--------|---------|-------|
| 6.1 | Session resume on server restart | PENDING | — | session_manager.py exists but not fully tested. |
| 6.2 | Context pressure flagging & auto-spoof | PARTIAL | 2026-04-20/21 | Flag-only (no auto-execute). Token check at 70%. `reset_pending` modal → user picks spoof/fresh. Needs: live test, dashboard context bar, PreCompact hook backup. |
| 6.3 | Orphaned session recovery | PENDING | — | Reconnect UI, 7-day archival. |
| 6.4 | sutra-bypass CLI (headless status, send, reports) | PENDING | — | Reads SQLite directly. Dispatches via process_manager. |

---

## Known Architectural Gaps (Not Blocking)

### Gap 0: Filesystem Access Control

**Problem:** Workers have effectively unrestricted filesystem access. A hallucinating Sutra or misinterpreted instruction could cause real damage before being caught.

**Current Mitigation:** Permissive by default, git for safety. Every workspace is git-init'd. Every task auto-commits. Rollback always possible.

**Short-term fix (Gap 0a):** Add Bash denylist to process_manager via `--allowedTools`. Block `rm -rf`, `sudo`, `git push --force`, external curl.

**Medium-term (Gap 0b):** Claude Code sandbox with `filesystem.allowWrite` scoped to agent CWD.

**Long-term (Gap 0c):** Per-agent permission profiles (deploy, read-only, scratch).

### Gap 1: JSONL Session Growth

**Problem:** Long-lived agents (weeks of history) hit cold-start latency as session file balloons.

**Current Mitigation:** Prompt caching (10% of uncached cost). Auto-compaction at ~80% context.

**Planned (Phase 6, REQ-6.2):** Auto-spoof at 70% via `cx spoof --compress`.

**Phase 2 enhancement:** Per-agent turn cap config. Visible turn count + compress button. Cost delta warning.

### Gap 2: No Streaming

**Problem:** JSON print is all-or-nothing. For >3s tasks, user sees no progress signal.

**Current Mitigation (Phase 3, REQ-3.1):** Hook-based heartbeats post tool descriptions to `/api/events`. Active block subtitle updates live.

**Phase 1 workaround:** Elapsed-time counter in UI ("working for 12s...").

### Gap 3: Agent Routing

**Problem:** Currently routes model (Haiku/Sonnet/Opus) but not which AGENT. User types `@AgentName` or uses dropdown.

**Deferred to:** REQ-3.7 (intent → agent selection via keyword + metadata + recent activity).

---

## Critical Path

```
Phase 0 (fix broken)
  ↓
Phase 1 (wire unwired) ← COMPLETE
  ↓
Phase 2 (parallel) ← COMPLETE
  ↓
Phase 3 (observability) ← IN PROGRESS (3/7 of observability done)
  ↓
Phase 4 (compression)
  ↓
Phase 5b (intelligent channels)
```

**Early wins:** Phase 5a (PWA + skill) ships right after Phase 1. Phase 6 can run after Phases 1+2.

---

## What's Built But Not Yet Wired

These modules exist in the codebase but aren't yet part of the live path:

- `heartbeat.py` — log_synthesis() and pull_detail() functions exist but never called
- `server/sutra_core.py` — Knowledge store orchestration (started, not complete)
- Continuum integration — Scripts exist but not auto-triggered
- Knowledge base pipeline — Manual ingest only, no capture watcher
- Digital twin connection — Extension works standalone, no Sutra bridge
- Voice client — `server/voice/voice_client.py` exists but not started by server
- capture_watcher.py — Not yet implemented

---

## Phase 1 Implementation (Ralph Loop)

**Note:** Phase 1 scope is UI wiring, not new features. The backend (router, rate limiter, session writer, Ollama) is already live.

### Task Breakdown

Each task sized for Haiku agent (~1000 lines, one clear goal, testable).

1. **TASK-1:** Port static HTML/CSS from mockup to live index
   - Reference: `web/mockup-n-warm.html`
   - Replace entire `web/index.html` with layout from mockup
   - Keep styling, animations, static markup
   - Keep hardcoded data (will wire in later tasks)

2. **TASK-2:** Wire agent lanes to real API data
   - Fetch `GET /api/agents` on load
   - Render agent cards dynamically (one lane per agent)
   - Status indicators from API (idle/working/error)

3. **TASK-3:** Wire task blocks to real message data
   - Fetch messages for each agent from `GET /api/threads/{id}/messages`
   - Render task blocks with real timestamps, models, costs
   - Show working state (blue pulse) until message completes

4. **TASK-4:** Wire create-agent modal
   - POST to `POST /api/agents` with name, model, provider
   - Add new lane to dashboard on creation
   - Validate fields before submit

5. **TASK-5:** Wire "Talk to Sutra" input
   - POST input to `POST /api/threads/{id}/messages` or `POST /api/orchestrate`
   - Show input processing state
   - New task block appears in active agent lane

6. **TASK-6:** Real-time updates via WebSocket
   - Connect to ws://localhost:8891/dashboard
   - Subscribe to agent status, message events
   - Auto-update agent status, add new task blocks without reload
   - Auto-reconnect with "Reconnecting..." banner on disconnect

7. **TASK-7:** Working task popup
   - Click task block → modal with vritti layer (context)
   - Show summary, full message text, files touched
   - Reply affordance

8. **TASK-8:** Working session modal
   - Click agent header → modal with full conversation
   - Filter to agent's messages only
   - Continue conversation in modal if desired

9. **TASK-9:** Attention pill
   - Show pending approvals + needs-input blockers
   - Approve/Reject buttons inline
   - Red/amber dots for priority

10. **TASK-10:** Status overview card
    - Type "status" in chat → Sutra synthesizes summary
    - Show cost today, agents working, top blockers
    - Routed to Sutra, not to an individual agent

(Tasks 11+ deferred: elapsed-time counter, context bar, zoom slider port)

---

## Release Timeline

| Release | Target | What Ships | Dependencies |
|---------|--------|-----------|--------------|
| **R1** | 2026-04-08 | Fix Phase 0 bugs, wire Phase 1 modules (router, rate limiter, session writer, Ollama) | Nothing |
| **R2** | 2026-04-08 | Git sandboxes, auto-commit, permission enforcement, rollback (Phase 2) | Parallel with R1 |
| **R3** | 2026-04-21 | WebSocket dashboard, hook events, reports with zoom, statusline (Phase 3.1-3.4) | R1 + R2 |
| **R3.5** | Requested | Mobile PWA + /sutra skill (Phase 5a early access) | R1 only |
| **R4** | TBD | Multi-store reads, synthesis logging, capture pipeline (Phase 4) | R1 + R3 |
| **R5** | TBD | Voice, digital twin bridge, page-context routing (Phase 5b) | R4 |
| **R6** | TBD | Restart resilience, auto-spoof, orphan recovery, sutra-bypass (Phase 6) | R1 + R2 |

---

## Success Criteria

Christopher says "sutra, status" and gets a compressed summary of all work, costs, and blockers in under 3 seconds — without any agent reading each other's output. Monthly API cost goes down even as agent usage goes up.

**Measurable metrics (tracked over 30 days):**
- Routing accuracy: >90% no-override
- Context survival: 100% of /fresh sessions indexed
- Approval friction: <2 clicks to resolve supervised action
- Capture-to-query latency: <60s from explicit save to Sutra query
- Voice TTFW: <2.0s for status queries
- Monthly API cost: Lower than pre-Sutra baseline
- Agent uptime: >99% of working hours

---

*Last updated: 2026-04-21*
