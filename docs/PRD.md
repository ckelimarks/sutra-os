# Sutra — Product Requirements Document

**Consolidated from:** SUTRA-PRD.md, SUTRA-BRIEF.md, SUTRA-PLAN.md, SUTRA-IMPLEMENTATION.md, PROPOSED-SUTRA-PROMPT.md (as appendix)

**Version:** 2.0  
**Author:** Christopher Marks + Claude  
**Date:** 2026-04-08  
**Branch:** `sutra-orchestrator`  
**Audience:** This document briefs Claude Code agents on what to build and in what order. Christopher uses it to track scope and make phase-gate decisions.

---

## Vision

Sutra is a single orchestrator that Christopher talks to — via voice, statusline, or mobile — which manages all AI work across his personal OS. It delegates to sandboxed agents, maintains awareness through compressed worker reports, draws on cross-session memory (Continuum) and domain expertise (knowledge base), and has ambient browser awareness via the digital twin. Christopher never touches agent internals directly. He talks to Sutra; Sutra handles the rest.

**The name:** Sutra (सूत्र) means "thread" — the seed that contains the tree. The orchestrator compresses, routes, and unfolds on demand.

### Why Now

The pieces exist but don't talk to each other. Agent-chat has a working message loop, router, rate limiter, session writer, and Ollama adapter — all built, none wired together. Continuum preserves cross-session memory. The knowledge base stores domain expertise. The digital twin watches the browser. Voice works standalone. Six subsystems, zero integration. Meanwhile, running multiple Claude Code sessions manually burns tokens re-explaining context that the system already has somewhere.

---

## Glossary

| Term | Definition |
|------|-----------|
| **Sutra** (सूत्र) | One-sentence seed. The irreducible outcome. Target: <15 words. |
| **Vritti** (वृत्ति) | One-paragraph unfolding. Why it matters, what changed. Target: 50-150 words. |
| **Bhashya** (भाष्य) | Full commentary. Everything needed to act. Unbounded but structured. |
| **Compaction** | Claude Code's automatic context pruning when the window fills (~80%). Destroys conversation history. |
| **Spoof** | Continuum's session reconstruction — compresses a long session into a clean resumable one with injected identity and retrieved context. |
| **/fresh** | Manual skill to save structured session state (todos, decisions, files) before compaction or context switch. |
| **Digital twin** | Chrome extension that observes browsing, forms memories, and writes captures to `.context/captures/`. |
| **Statusline** | Claude Code's bottom-of-screen status bar. Used as both output (agent status) and input channel (via `/sutra` skill). |
| **Pull Architecture** | Pattern where Sutra reads only summaries; pulls context/details on demand via pull_id references. |
| **Worker report** | Structured JSON with 3 zoom layers that agents write on task completion, blockers, or decisions. |
| **Capture** | Content saved from the browser via digital twin. Three types: explicit (right-click), dwell (>60s on page), passive (<60s visit). |

---

## System Map

```
INPUT CHANNELS                          KNOWLEDGE STORES
  Voice (wake word → STT)                 Continuum corpus (cross-session)
  Statusline (Claude Code)                Knowledge base (domain expertise)
  Mobile (PWA / webhook)                  Digital twin captures (browsing)
  Digital twin (live screen)              /fresh + hooks (episodic state)
           ↓                                        ↓
    ┌──────────────────────────────────────────────────┐
    │                    SUTRA                          │
    │  Reads: worker reports, knowledge, context        │
    │  Routes: by complexity, budget, permission tier   │
    │  Compresses: sutra / vritti / bhashya             │
    │  Tracks: cost, sessions, agent state              │
    └──────────┬───────────────────────────┬────────────┘
               ↓                           ↓
    SANDBOXED AGENTS                 OBSERVABILITY DASHBOARD
      (git-backed, permissioned)       (cost, status, reports, sessions)
```

---

## Six Subsystems

| # | Subsystem | Current State | Role in Sutra |
|---|-----------|---------------|---------------|
| 1 | **Agent-chat server** | Core message loop works. Router, rate limiter, session writer, Ollama adapter built but unwired. UI has broken cost panel and missing elements. | Orchestration backbone — API, DB, process management |
| 2 | **Continuum** | Ingest, retrieve, spoof, dream all functional. Runs via `cx` CLI. | Cross-session memory. Sutra's long-term recall. |
| 3 | **Knowledge base** | SQLite + JSON, 3-zoom-level entries, domain-queryable. Manual ingest only. | Domain expertise. Sutra queries before answering domain questions. |
| 4 | **/fresh + hooks** | /fresh (manual), pre-compact.sh (automatic), session-start.sh (retrieval). All working. | Episodic state preservation across compactions. |
| 5 | **Digital twin** | Chrome extension functional. Ollama chat, IndexedDB, capture server writes to .context/captures/. No connection to other subsystems. | Browser sensor layer — what Christopher is looking at. |
| 6 | **Voice OS** | Complete standalone module in agent-chat/server/voice/. Porcupine + Whisper + TTS. Not integrated with server startup. | Speech I/O channel. |

---

## Sutra Core Specification

**Runtime form:** Python class instantiated inside agent-chat's bridge.py. Not a separate Claude Code session — Sutra is the server process itself, using `claude --print --output-format json` for its own reasoning when needed.

**Model:** Sutra's own reasoning uses Sonnet by default (fast, cheap for routing/synthesis). Escalates to Opus only for multi-store synthesis (REQ-4.1) or when Christopher explicitly asks for deep analysis. Uses Haiku for classification tasks (routing, report triage).

**Context budget strategy:**

| Slot | Budget | Contents |
|------|--------|----------|
| Identity | ~300 tokens | Sutra prompt/personality (from `data/orchestrator/sutra-identity.md`) |
| Worker state | ~2,000 tokens | Summary layer only from all active agent reports |
| Episodic state | ~1,000 tokens | .context/active-work.md current agent section |
| Knowledge retrieval | ~3,000 tokens | On-demand: knowledge base query results, Continuum retrieval |
| User input + history | ~5,000 tokens | Current conversation (last 5 exchanges) |
| **Total per turn** | **~11,300 tokens** | Well within Sonnet's window; leaves room for response |

**Prompt/identity source:** `data/orchestrator/sutra-identity.md` — checked into the agent-chat repo. Based on existing `get_orchestrator_system_prompt()` in heartbeat.py but extracted to a file for editability.

**Key constraint:** Sutra never reads agent conversation history or raw tool output. It reads only: (a) structured worker reports, (b) hook events, (c) knowledge store query results. This is how observability stays token-free.

---

## Compression Data Model

| Layer | Target Size | Who Writes It | Where Stored | When Generated |
|-------|-------------|---------------|--------------|----------------|
| **Sutra** | 1 sentence, <15 words | Agent (on report) | `reports/{agent}.json` → `.summary` | Task completion, blocker, decision |
| **Vritti** | 1 paragraph, 50-150 words | Agent (on report) | `reports/{agent}.json` → `.context` | Same as sutra |
| **Bhashya** | Full structured detail | Agent (raw output) | `data/sessions/{agent}.jsonl` + `reports/{agent}.json` → `.details` | Real-time (sessions), on report (details) |

**Compression gates (from Vedic tradition):**
- **alpaksaram** (brevity): Sutra must be one sentence max
- **asandigdham** (clarity): One clear meaning, no vague words
- **saravat** (essence): Only what matters for the next decision

**Who reads each layer:**
- Sutra (orchestrator) reads: `.summary` always, `.context` on pull, `.details` never (delegates back to agent)
- Dashboard renders: `.summary` in cards, `.context` on hover/click, `.details` on explicit drill-down
- Continuum ingests: all layers (for cross-session retrieval)

---

## Cost Model

**What's counted:**
- Claude API calls: per-message cost from response JSON (`total_cost_usd`)
- Sutra's own reasoning: tracked separately as `orchestrator_cost`
- Classification calls (Haiku for routing): tracked as `routing_cost`

**What's not counted (but tracked as $0.00):**
- Ollama calls (local, free)
- Hook executions
- File I/O, git operations

**Budget scope:** Rolling 24-hour window per agent. Configurable via `PUT /api/agents/{id}` with `daily_budget_usd` field. Default: $5.00/agent/day. Sutra itself: $10.00/day.

**Budget enforcement:**
- At 80% of daily budget: dashboard alert, route new requests to haiku/ollama
- At 100%: block new requests, notify Christopher via dashboard + statusline
- Override: `force_model` param on any request bypasses budget routing (but still tracks cost)

**Where budgets are configured:** `PUT /api/agents/{id}` for per-agent, `PUT /api/settings` for global defaults.

---

## Security Model

**Authentication:** Bearer token in `Authorization` header. Token stored in `data/.sutra-token` (generated on first server start, never committed). Same token used by all clients (PWA, digital twin, CLI, voice).

**Endpoints requiring auth:** All `/api/sutra`, `/api/orchestrate`, `/api/threads/*/messages` (write). Read-only endpoints (`/api/agents`, `/api/events`, `/api/usage`) are unauthenticated (localhost only).

**Network scope:** Server binds to `0.0.0.0:8890` (local network accessible for mobile PWA). Home network only — no internet exposure. Optional: Cloudflare Tunnel or Tailscale for remote access (not in v1 scope).

**Agent sandboxing:** See Phase 2. Permissions enforced via workspace `.claude/settings.json`, not runtime checks.

---

## Two-Way Relay and the Attention Queue

Sutra is not a filter — it's a **two-way relay with intelligent sequencing**.

**Outbound:** Christopher sends commands → Sutra routes to the right agent → agent works.
**Inbound:** Agents complete work → results flow back through Sutra → Sutra sequences them for Christopher.

Christopher can only focus on one thing at a time. Sutra's job is to present the right thing next.

### Attention Queue

Every inbound agent event is classified into one of four states:

| State | Indicator | Meaning | Action required |
|-------|-----------|---------|-----------------|
| **Needs input** | Red dot | Agent is blocked on a decision only Christopher can make | Surfaces immediately. Question preview shown. |
| **Needs permission** | Amber dot | Agent knows what to do, needs a yes/no | Inline Approve/Reject. One tap. |
| **Completed** | Green dot | Work finished, ready for review | Click to view in conversation stream. |
| **Working** | Blue pulse | In progress, no action needed | Ambient. Just a status indicator. |

**Sequencing rules:**
1. Needs-input items surface first (blocking = highest priority)
2. Needs-permission items surface second (quick to resolve)
3. Completed items surface third (review when ready)
4. Working items are never surfaced — they're ambient awareness only

**"While you were away" synthesis:** If Christopher is AFK or focused on a direct agent chat, completions accumulate. When he returns to Sutra, it presents a summary: "While you were away: 3 tasks completed, 1 needs your input, App Factory built 2 more apps." Individual items expand on click.

**Queue lifecycle:** Items enter the queue when agents report. Items leave when Christopher acknowledges them (click, approve/reject, or reply). When the queue is empty: "All clear."

**Inbound completions in the conversation stream:** Agent results don't just appear in the queue — they also flow into the main conversation as cards that slide in, distinct from Christopher's outbound messages (different visual treatment: left-side glow, "completed" badge). These auto-collapse after acknowledgment.

**Agent routing (inbound):** Sutra doesn't just relay — it adds context. "ContentWriter finished 20 Reddit posts" becomes "ContentWriter finished 20 Reddit posts. 3 are ready to publish, 2 need your review. App Factory is still cooking — no action needed." Sutra synthesizes, not just forwards.

---

## Principles

1. **Permissive by default, git for safety.** Agents can create, edit, and run — but every workspace is git-initialized. Destructive operations (delete, force-push, production writes) require explicit approval. The backup IS the permission model.
2. **Compression without reduction.** The seed contains the tree. Sutra reads summaries; pulls context on demand; never loads full detail unless a decision requires it.
3. **Observability without tokens.** Hooks and structured reports, not orchestrator reading every message. Sutra knows agent state without paying for it.
4. **Local-first.** Everything runs on Christopher's machine. No cloud dependencies except API calls to Claude/OpenAI.
5. **Single entry point.** Christopher talks to Sutra. Sutra talks to agents. Christopher never manages agents directly.
6. **Two-way relay.** Sutra routes commands out AND sequences results back. Christopher deals with one thing at a time. Sutra decides what's next.

---

## Phased Requirements

(See original SUTRA-PRD.md sources in archive/ or CONSOLIDATION-PLAN.md for complete detailed acceptance criteria per requirement)

### Phase 0: Fix What's Broken

_Goal: The existing agent-chat works end-to-end without silent failures._

**Phase gate:** All REQ-0.x acceptance tests pass. Dashboard loads with zero JS console errors. Cost figures are non-zero after real message exchange.

- **REQ-0.1:** Cost dashboard displays real data
- **REQ-0.2:** Home dashboard renders
- **REQ-0.3:** Instruction queue drains
- **REQ-0.4:** Supervised permission tier has approval flow

### Phase 1: Wire the Unwired

_Goal: Modules that are built but disconnected become part of the live path._

**Phase gate:** Router routes 3 different messages to different models. Rate limiter handles a simulated 429. Ollama agent sends/receives. Session JSONL files exist for all agents.

- **REQ-1.1:** Router integration + REQ-1.1.1 (routing feedback loop)
- **REQ-1.2:** Rate limiter integration
- **REQ-1.3:** Universal session writer
- **REQ-1.4:** Ollama adapter live path

### Phase 2: Sandboxed Agent Workspaces

_Goal: Agents run in isolated, git-backed workspaces. Permissive by default, safe by design._

**Phase gate:** Autonomous agent creates/edits/auto-commits files. Restricted agent is read-only. Rollback restores prior state.

- **REQ-2.1:** Git-backed workspace initialization
- **REQ-2.2:** Auto-commit on task completion
- **REQ-2.3:** Permission tiers enforced via workspace settings
- **REQ-2.4:** Rollback capability

### Phase 3: Observability Without Tokens

_Goal: See what every agent is doing without the orchestrator reading their output._

**Phase gate:** Dashboard live-updates via WebSocket. Events appear within 2s of tool use. Reports have three zoom layers.

- **REQ-3.1:** Hook-based event capture
- **REQ-3.2:** Worker report protocol (Pull Architecture)
- **REQ-3.3:** Live dashboard
- **REQ-3.4:** Statusline integration
- **REQ-3.5:** Attention queue
- **REQ-3.6:** Inbound flow (agent → Christopher)
- **REQ-3.7:** Agent routing (intent → agent selection)

### Phase 4: Compression and Context Intelligence

_Goal: Sutra stays context-efficient by reading compressed state, pulling detail on demand, and leveraging all knowledge stores._

**Phase gate:** Sutra answers domain questions using knowledge base. Answers "what did we do?" using Continuum. Browser capture appears in context within 60s. Synthesis log has valid pull_ids.

- **REQ-4.1:** Sutra reads from all knowledge stores
- **REQ-4.2:** Automatic synthesis logging
- **REQ-4.3:** Digital twin → knowledge pipeline
- **REQ-4.4:** Continuum auto-ingest on /fresh

### Phase 5a: Basic Input Channels

_Goal: Christopher can reach Sutra from phone and Claude Code sessions._

**Phase gate:** PWA sends message and gets response over local WiFi. `/sutra` skill returns inline results.

- **REQ-5.2:** Mobile access (PWA)
- **REQ-5.4:** Statusline as conversational input

### Phase 5b: Intelligent Input Channels

_Goal: Voice and browser context enrich Sutra's awareness._

**Phase gate:** Voice round-trip works end-to-end. Digital twin sidebar toggles between Ollama and Sutra. Page context influences response.

- **REQ-5.1:** Voice integration + REQ-5.1.1 (Voice latency SLA)
- **REQ-5.3:** Digital twin as input channel

### Phase 6: Session Resilience

_Goal: Agents survive crashes, restarts, and context loss without manual intervention._

**Phase gate:** Kill-and-restart test passes with full continuity. Auto-spoof triggers. `sutra-bypass` works with Sutra killed.

- **REQ-6.1:** Session resume on server restart
- **REQ-6.2:** Automatic spoof on context pressure
- **REQ-6.3:** Orphaned session recovery
- **REQ-6.4:** Headless recovery mode (sutra-bypass)

---

## Dependency Graph

```
Phase 0 (fix broken)
  ├── REQ-0.1 Cost panel
  ├── REQ-0.2 Home dashboard
  ├── REQ-0.3 Instruction queue
  └── REQ-0.4 Approval flow
       ↓
Phase 1 (wire unwired)              Phase 2 (sandboxes) ← parallel
  ├── REQ-1.1 Router + 1.1.1         ├── REQ-2.1 Git workspaces
  ├── REQ-1.2 Rate limiter           ├── REQ-2.2 Auto-commit
  ├── REQ-1.3 Session writer         ├── REQ-2.3 Permissions
  └── REQ-1.4 Ollama adapter         └── REQ-2.4 Rollback
       ↓                                  ↓
Phase 3 (observability) ←─────────────────┘
  ├── REQ-3.1 Hook events
  ├── REQ-3.2 Worker reports
  ├── REQ-3.3 Live dashboard
  └── REQ-3.4 Statusline
       ↓                         Phase 5a (basic channels) ← after Phase 1
Phase 4 (compression)              ├── REQ-5.2 Mobile PWA
  ├── REQ-4.1 Multi-store reads    └── REQ-5.4 Statusline skill
  ├── REQ-4.2 Synthesis logging
  ├── REQ-4.3 Twin → knowledge     Phase 6 (resilience) ← after Phase 1+2
  └── REQ-4.4 Continuum ingest       ├── REQ-6.1 Restart resume
       ↓                              ├── REQ-6.2 Auto-spoof
Phase 5b (intelligent channels)       ├── REQ-6.3 Orphan recovery
  ├── REQ-5.1 Voice + 5.1.1          └── REQ-6.4 sutra-bypass
  └── REQ-5.3 Digital twin bridge
```

**Critical path:** 0 → 1 → 3 → 4 → 5b  
**Early wins:** Phase 5a (mobile + statusline skill) can ship right after Phase 1  
**Parallel tracks:** Phase 2 runs alongside Phase 1. Phase 6 runs after Phase 1+2.

---

## Data Model

### agent-chat.db tables

| Table | Status | Purpose |
|-------|--------|---------|
| `agents` | Exists | Agent registry with status, permission_tier, role, model, cwd, daily_budget_usd |
| `threads` | Exists | 1:1 with agents, holds session_id, unread_count |
| `messages` | Exists | Message log with cost_usd, tokens, duration. **Add:** route_reason column |
| `reports` | Exists | Manager inbox with acknowledge lifecycle. **Add:** zoom layer storage |
| `session_registry` | Exists | Persistent session tracking, survives agent deletion |
| `agent_interactions` | Exists | Orchestration edge log |
| `events` | **New** | Hook events: agent_id, event_type, timestamp, metadata JSON |
| `pending_approvals` | **New** | Supervised tier approval queue |
| `instruction_queue` | **New** | Persistent instruction queue per agent |

### Filesystem

| Path | Purpose |
|------|---------|
| `data/orchestrator/sutra-identity.md` | Sutra's prompt/personality |
| `data/orchestrator/reports/{agent}.json` | Worker reports (3 zoom layers) |
| `data/orchestrator/synthesis-log.json` | Sutra's observation log with pull_ids |
| `data/orchestrator/heartbeats.json` | Real-time agent activity |
| `data/sessions/{agent_id}.jsonl` | Universal session format (Turn records) |
| `data/workspaces/{agent_name}/` | Git-backed agent sandboxes |
| `data/.sutra-token` | Auth token (never committed) |
| `.context/captures/` | Digital twin browser captures |
| `.context/active-work.md` | /fresh episodic state |
| `.context/knowledge-base/knowledge.db` | Domain expertise (sutra/vritti/bhashya) |

---

## Metrics

### Launch Criteria (testable on day 1)

- [ ] Send "status" via voice/text → compressed summary returned in <3s (voice) or <1s (text)
- [ ] Route 10 mixed queries → 90%+ routed to correct model without override
- [ ] Kill and restart server → all agents resume with conversation continuity
- [ ] Autonomous agent creates files → auto-committed to git within 60s of report
- [ ] Right-click save article → queryable by Sutra within 5 minutes

### Health Metrics (measured over 30 days)

| Metric | Target | Measurement |
|--------|--------|-------------|
| Routing accuracy | >90% no-override | `routing_override` events ÷ total routes |
| Context survival | 100% of /fresh sessions indexed | Timestamp diff: /fresh → `cx retrieve` success |
| Approval friction | <2 clicks to resolve supervised action | UI interaction count |
| Capture-to-query latency | Explicit captures queryable in <60s | Timestamp diff: capture write → Sutra query success |
| Voice TTFW | <2.0s for status queries | `total_ms` from voice latency log |
| Monthly API cost | Lower than pre-Sutra baseline | Billing comparison (first full month vs. prior month) |
| Agent uptime | >99% of working hours | Session crash events ÷ total session hours |

---

## Migration Path

**Phase 0-1:** Christopher continues using independent Claude Code sessions as today. Agent-chat server runs alongside. No disruption.

**Phase 2-3:** New work starts going through Sutra. Existing projects remain independent. Gradual migration: one project at a time gets an agent in Sutra.

**Phase 4+:** Sutra becomes the default entry point. Independent Claude Code sessions are the fallback (always available via `sutra-bypass` or just opening a terminal).

**Never a hard cutover.** The old way always works. Sutra earns adoption by being better, not by being mandatory.

---

## Agent Lifecycle

| State | Description | Transitions |
|-------|-------------|-------------|
| `active` | Agent has a workspace, session, and is available for work | → `idle`, `working`, `archived` |
| `idle` | Agent is active but not processing a message | → `working`, `archived` |
| `working` | Agent is processing a message | → `idle`, `error` |
| `error` | Agent encountered an unrecoverable error | → `idle` (retry), `archived` |
| `archived` | Agent is retired. Workspace preserved (read-only). Session files kept. Not routable. | → `active` (reactivate) |

**Archival:** `PUT /api/agents/{id}` with `status: "archived"`. Workspace moves to `data/workspaces/_archived/{agent_name}/`. Session JSONL preserved. Agent hidden from dashboard by default (toggle to show archived).

**Reactivation:** `PUT /api/agents/{id}` with `status: "active"`. Workspace restored. Session resumed if valid.

---

## What NOT to Build

- Multi-user support (Christopher only)
- Cloud deployment (local only, Cloudflare Tunnel is a future option)
- Custom model fine-tuning
- Mobile native app (PWA is sufficient)
- Embedding-based search in digital twin (Continuum handles semantic search)
- Real-time streaming for orchestrator responses (batch is fine for v1)
- Internet-accessible endpoints without VPN/tunnel

---

## Appendix A: Proposed System Prompt (2026-04-08)

_Not yet implemented. Scheduled check-in alternative documented for future exploration._

See archive/handoff-2026-04.md for full draft prompt including dual-capability system (primary assistant + observer modes) and scheduled check-in alternative to continuous observation.

---

*Created: 2026-04-08 | Last updated: 2026-04-28 (consolidated)*
