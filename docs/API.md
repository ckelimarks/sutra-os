# Sutra API — Plain Language Map

This is the front door to Sutra. Everything Sutra does — making agents, sending them work, reading what they did, watching their progress — happens through HTTP calls to one server running on your laptop at `http://localhost:8900`.

If you can run a `curl` command, you can use this API. That's the whole idea.

---

## The Mental Model

Sutra has a small number of "things" you work with:

- **Agents** — workers. Each one is a Claude session running in a folder.
- **Threads** — the conversation history with one agent. Each agent has one thread.
- **Messages** — the back-and-forth inside a thread.
- **Reports** — agents file these when they finish work or get stuck. Like a status report.
- **Approvals** — when a careful agent wants to do something risky, it asks first.
- **Sessions** — the underlying Claude conversation files on disk. Sutra keeps these in sync.

Everything below is a way to read or change one of those things.

---

## Is the server alive?

**`GET /api/health`**

Tells you the server is running and which port it's on.

```bash
curl http://localhost:8900/api/health
# {"status": "ok", "port": 8900}
```

Use this if something feels wrong. If this returns nothing, the server is down — run `./start.sh`.

---

## Agents — the workers

### List all agents

**`GET /api/agents`**

Shows every agent you've made: who they are, what folder they live in, and whether they're online, busy, or offline.

```bash
curl -s http://localhost:8900/api/agents
```

### Look at one agent

**`GET /api/agents/{id}`**

Just the details for one specific agent.

### Make a new agent

**`POST /api/agents`**

Creates a new worker. You give it a name, a folder to work in, and a permission level.

```bash
curl -X POST http://localhost:8900/api/agents \
  -H "Content-Type: application/json" \
  -d '{"name":"MyAgent","cwd":"/path/to/folder","model":"sonnet","permission_tier":"autonomous"}'
```

### Change an agent

**`PUT /api/agents/{id}`**

Edit an agent's settings — rename, change folder, change permission level.

### Delete an agent

**`DELETE /api/agents/{id}`**

Removes the agent. Their session files on disk stick around, but the agent won't show up in the list anymore.

---

## Watching agents work

These are how Sutra (you, or an orchestrator) sees what an agent did **without reading their full conversation**. Cheap to call, doesn't burn context.

### How full is the agent's brain?

**`GET /api/agents/{id}/context`**

Returns the percent of the context window that's used. When this hits ~80%, time to reset that agent.

```bash
curl -s http://localhost:8900/api/agents/AGENT_ID/context
# {"used_tokens": 142000, "max_tokens": 200000, "percent": 71, "model": "sonnet"}
```

### What did this agent just do?

**`GET /api/agents/{id}/recent`**

Last few messages and any errors. **This is the most important read.** Use it before asking an agent anything — see what they're up to first.

```bash
curl -s http://localhost:8900/api/agents/AGENT_ID/recent
```

### What files did this agent touch?

**`GET /api/agents/{id}/files`**

Files the agent has read or written in their session. Useful for "what did they change?"

### What's queued for this agent?

**`GET /api/agents/{id}/queue`**

If you sent multiple instructions while the agent was busy, they line up. This shows the line.

### What did this agent commit to git?

**`GET /api/agents/{id}/commits`**

Workspaces are git repos. This shows the commit log. Easy way to see what work landed.

---

## Talking to agents

### Read the conversation

**`GET /api/threads/{id}/messages`**

Pulls the messages for a thread. Add `?since=ID` to only get new ones.

### Send a message

**`POST /api/threads/{id}/messages`**

Send a message into the thread. Lower-level than `/api/orchestrate` — usually you want orchestrate.

### Cancel what an agent is doing

**`POST /api/agents/{id}/cancel`**

Stops the current dispatch. The agent stops mid-task.

### Reset an agent (clear their memory)

**`GET /api/agents/{id}/reset-options`** — see what reset modes are available
**`POST /api/agents/{id}/reset`** — wipe context and start fresh

Use this when context is over 80%.

#### `GET /reset-options`

Returns an **agent-aware** list of injectable docs. The list and defaults vary by `agent_type`:

| `agent_type` | How it's classified | Default-on docs |
|---|---|---|
| `sutra` | `name == "Sutra"` | `sutra_identity`, `context_payload`, `telos`, `state`, `recent_reports` |
| `project` | `cwd` contains `/Projects/` | `project_claude`, `project_infra`, `state` |
| `utility` | `role == "utility"` | `state` |
| `worker` | everything else | `state` |

Project workers also get auto-derived options for `<cwd>/CLAUDE.md`, `<cwd>/INFRA.md`, `<cwd>/context/last-session.md`, `<cwd>/.context/active-work.md`. If a doc's source file is missing, `default` is forced to `false` so the modal never shows a default-on-but-disabled checkbox.

Response shape:

```json
{
  "agent_id": "6cbd167a",
  "agent_name": "Sutra",
  "agent_type": "sutra",
  "model_max_tokens": 1000000,
  "turn_count": 64,
  "threshold": 80,
  "current_session_id": "556681a6-...",
  "available_docs": [
    {
      "key": "sutra_identity",
      "name": "SUTRA-IDENTITY.md",
      "path": "/Users/.../SUTRA-IDENTITY.md",
      "tokens": 1820,
      "last_modified": "2026-04-20T10:00:00",
      "default": true,
      "exists": true,
      "synthetic": false
    },
    {
      "key": "recent_reports",
      "name": "Recent worker reports",
      "path": "<synthetic:recent_reports>",
      "tokens": 4200,
      "last_modified": null,
      "default": true,
      "exists": true,
      "synthetic": true
    }
    // …
  ]
}
```

`synthetic: true` docs are computed on demand server-side (e.g., `recent_reports` renders the last 10 rows from the reports table as markdown) — they don't correspond to a file on disk.

#### `POST /reset`

The request body picks the mode and which doc keys to inject into the next session:

```json
{
  "mode": "spoof",                                  // or "fresh"
  "inject_docs": ["sutra_identity", "context_payload", "state", "recent_reports"],
  "steering_prompt": "Preserve dispatch patterns. Drop hallucinated tool calls.",
  "custom_note": ""
}
```

`inject_docs` accepts any `key` returned by `/reset-options` for that agent. Keys not valid for the agent's type (e.g., asking for `project_claude` on Sutra) are silently dropped. `steering_prompt` is only used in `spoof` mode.

`mode: "spoof"` runs Continuum's `spoof_tool.py` to compress the existing session JSONL into a much shorter narrative, preserving identity and decisions. `mode: "fresh"` clears the session id entirely.

The response (returned **after** spoof finishes — can take 30–90s):

```json
{
  "status": "reset",
  "agent_id": "6cbd167a",
  "agent_name": "Sutra",
  "mode": "spoof",
  "session_id": "556681a6-40ef-4cad-8197-ce3bab1341cf",  // null if fresh / fallback
  "injected_docs": ["sutra_identity", "context_payload", "state", "recent_reports"]
}
```

**While the request is in flight**, the server emits live progress to `/api/signals` (see *Reset progress signals* below). Poll that endpoint to render a progress UI instead of staring at a blocking request. The `events` table also gets two rows per reset (`spoof` and `session_reset`) with the full outcome — query those for an audit trail after the fact.

### Roll back an agent

**`POST /api/agents/{id}/rollback`**

Undo recent work. Uses git underneath.

### See what sub-agents an agent spawned

**`GET /api/agents/{id}/subagents`**

If an agent used the `Agent` tool to spawn a helper, this shows those spans (prompt + result preview).

---

## Dispatching work — the main verb

**`POST /api/orchestrate`**

This is **the** way to tell an agent to do something. Sutra (the orchestrator) uses this constantly.

```bash
curl -s -X POST http://localhost:8900/api/orchestrate \
  -H "Content-Type: application/json" \
  -d '{"agent":"AgentName","instruction":"Fix the broken test in src/foo.py"}'
```

What happens:
1. Sutra finds the agent by name
2. Checks their permission level
3. Either sends the instruction immediately (autonomous), or files an approval request (careful)
4. Returns right away — you watch progress via `/recent`

**Don't use this from inside Sutra to spawn a new Claude subprocess.** This sends to *running* agents. To create one, use `POST /api/agents`.

---

## Reports — what agents tell you when they're done

Agents file reports when they finish, get blocked, or need input. You see these as notifications.

### List reports

**`GET /api/reports`**

All reports. Add `?acknowledged=false` to see only unread ones.

Reports come in three "zoom" levels:
- `?zoom=summary` (default) — just the headline
- `?zoom=context` — headline + context
- `?zoom=details` — everything

### Read one report

**`GET /api/reports/{id}?zoom=details`**

Full story.

### File a new report

**`POST /api/reports`**

Agents post here when they finish work (usually triggered by hooks, not by you).

### Mark a report as read

**`POST /api/reports/{id}/acknowledge`**

Clears it from the unread count.

### Mark them all as read

**`POST /api/reports/acknowledge-all`**

For when you have a pile and don't want to click each one.

---

## Completions — separate from reports

Some completions live on their own track (the green "DONE" notifications).

### Acknowledge one

**`POST /api/completions/{id}/acknowledge`**

### Acknowledge all

**`POST /api/completions/acknowledge-all`**

---

## Approvals — agents asking permission

When an agent has the `careful` permission tier, it stops before doing anything risky and asks. You answer via this API.

### See what's waiting on you

**`GET /api/approvals`**

List of pending approval requests.

### Approve or reject

**`POST /api/approvals/{id}/approve`** — let it proceed
**`POST /api/approvals/{id}/reject`** — say no

The agent picks up and continues (or stops). Note: it's `reject`, not `deny`.

---

## The dashboard view

### Everything that needs your eyes

**`GET /api/attention`**

The most useful single endpoint for "what should I look at?" Returns:
- Agents that are blocked or asking for input
- Approvals waiting on you
- Recent completions you haven't acknowledged
- Agents whose context is full and want a reset

This is what powers the notification dot in the UI.

### Big-picture status

**`GET /api/status/overview`**

How many agents online, how much money spent today, etc.

### Cost tracking

**`GET /api/usage`** — money spent across all agents
**`GET /api/budget`** — your daily/monthly limits and where you stand

### Token tracking

**`GET /api/tokens`**

How many tokens each agent has used. Useful for spotting context bloat.

---

## Sessions — the files behind the scenes

Every agent has a session file on disk (`~/.claude/projects/...`). Sutra reads these to figure out what's really going on.

### List session files

**`GET /api/sessions`** or **`GET /api/session-files?agent_id=X`**

Shows the JSONL files belonging to each agent.

### Read a raw session file

**`GET /api/session-file/{id}`**

Gives you the raw JSONL — the unprocessed conversation log Claude wrote.

### Find orphaned sessions

**`GET /api/sessions/orphaned`**

Sessions whose agent was deleted. Good for cleanup.

### Re-sync sessions

**`GET /api/sessions/reconcile`**

Manually triggers Sutra to re-scan disk and update its database. Sutra does this automatically on startup, but call this if things look weird.

---

## Heartbeats and orchestrator brain

### Worker heartbeats

**`GET /api/orchestrator/heartbeats`**

Each agent sends a periodic "I'm alive, here's what I'm doing" beat. This shows the latest from each.

### Briefing

**`GET /api/orchestrator/briefing`**

A summary of all worker activity — Sutra reads this to understand what's happening across the team.

### Interactions (for the visualization)

**`GET /api/interactions?hours=24`**

Who talked to whom, when. Powers the "neural net" graph in the UI.

---

## Settings & configuration

### Read settings

**`GET /api/settings`**

Cron interval, orchestrator on/off, etc.

### Slack agent

**`GET /api/slack-agent/config`**

If you have the Slack agent wired up, this shows its config.

---

## Canvas — the scratchpad

### Read the canvas

**`GET /api/canvas`** (returns JSON) or **`GET /canvas-view`** (renders HTML)

A shared HTML scratchpad agents can write to. Good for visual outputs.

---

## Browse the file system

**`GET /api/browse?path=/some/dir`**

Lists folders under a path. Used by the UI to let you pick a working directory when creating an agent.

**`GET /api/file?path=/absolute/path/to/file`**

Read a single file and return its content. Read-only. Text files only, max 500KB.

```bash
curl "http://localhost:8900/api/file?path=/Users/you/personal-os/CLAUDE.md"
# {"path": "/Users/you/personal-os/CLAUDE.md", "name": "CLAUDE.md", "content": "..."}
```

Returns `404` if not found, `400` if path is a directory, `413` if file exceeds 500KB.

---

## Debug — when something is weird

### Raw state dump

**`GET /api/debug`**

Everything Sutra knows, dumped as JSON. Long. Use when troubleshooting.

### Tool signals

**`GET /api/signals`**

Recent ephemeral events from agents. Two flavors share this stream:

**Tool-use signals** — emitted while an agent is running a tool. Shape:

```json
{
  "agent_id": "...",
  "tool": "Bash",
  "status": "started",          // or "completed", "subagent_start", "subagent_end"
  "detail": "ls -la",
  "timestamp": 1745700000.0
}
```

**Reset progress signals** — emitted by `POST /api/agents/{id}/reset` while spoof/fresh is running, so callers can show a progress UI without waiting on the (blocking) reset response. Distinguish with `kind === "reset_phase"`:

```json
{
  "agent_id": "6cbd167a",
  "kind": "reset_phase",
  "phase": "spoof_running",     // see phase list below
  "detail": "Compressing... 14s elapsed",
  "timestamp": 1745700014.0,
  "ok": true                     // present on terminal phases (success/failure)
}
```

Phase sequence on a successful spoof:

| phase | when | terminal? |
|---|---|---|
| `starting` | request received, docs read | no |
| `spoof_starting` | just before `spoof_tool.py` Popen | no |
| `spoof_running` | every 2s while subprocess alive (heartbeat) | no |
| `spoof_log` | one per non-empty stdout line from `spoof_tool.py` | no |
| `spoof_success` / `spoof_failed` / `spoof_no_session` | subprocess finished | no |
| `fresh` | `mode: "fresh"` branch instead of spoof | no |
| `complete` | DB updated, response about to send | yes — `ok: bool` |

On `spoof_success` and `complete` the payload includes `new_session_id`. The signal files live at `data/signals/reset_<agent_id>_<ts>.signal` and are auto-cleaned after 5 minutes by the `/api/signals` GET handler.

Useful for "is this agent actually doing anything?" and "did the spoof actually succeed?"

### Event log (filtered)

**`GET /api/events?agent_id=X&type=Y&limit=50`**

Filtered event history. Useful for replaying what happened.

### Rate limit state

**`GET /api/rate-limits`**

Whether Claude or Ollama are currently throttling you, and how long until backoff clears.

### Routing override history

**`GET /api/routing/overrides`**

If you forced a specific model for an instruction, those decisions are logged here.

### Auth token

**`GET /api/sutra/token`**

The bearer token for protected endpoints. Localhost only.

---

## Lower-level helpers

### Mark a thread as read

**`POST /api/threads/{id}/read`**

Clears the unread badge on a thread.

### Send a heartbeat (used by workers)

**`POST /api/heartbeat`**

Workers ping this to say "I'm alive, here's what I'm doing." You don't usually call it manually.

### Sutra control endpoint

**`POST /api/sutra`**

The orchestrator's own control input.

### Improve a prompt

**`POST /api/improve-prompt`**

Sends a draft instruction back through Claude to tighten it before dispatching.

### Open a file in your editor

**`POST /api/open-file`**

Convenience: opens a path in your default editor (used by the UI).

---

## Trying it from your terminal — copy/paste examples

Open Terminal. Make sure Sutra is running (`./start.sh` from the `sutra-build` folder, then check `http://localhost:8900`).

### 1. Is the server alive?

```bash
curl -s http://localhost:8900/api/health
```

You should see: `{"status": "ok", "port": 8900}`

If you see nothing or a connection error — server isn't running.

### 2. List your agents (pretty-printed)

Pipe through `python3 -m json.tool` to make the JSON readable:

```bash
curl -s http://localhost:8900/api/agents | python3 -m json.tool
```

Or just the names and statuses:

```bash
curl -s http://localhost:8900/api/agents | \
  python3 -c "import sys,json; [print(f\"{a['name']:20} [{a['status']}]  {a['cwd']}\") for a in json.load(sys.stdin)['agents']]"
```

You'll see something like:
```
LegalAgent           [online]   /Users/.../job-search/hg-contract
HGOnboarding         [busy]     /Users/.../hg-onboarding
LoveNotes            [online]   /Users/.../lovenotes
```

### 3. Grab an agent's ID (you need this for the next calls)

```bash
AGENT_ID=$(curl -s http://localhost:8900/api/agents | \
  python3 -c "import sys,json; print(next(a['id'] for a in json.load(sys.stdin)['agents'] if a['name']=='LegalAgent'))")
echo $AGENT_ID
```

Now `$AGENT_ID` holds that agent's UUID for the rest of your session.

### 4. The most important call — what is this agent doing?

```bash
curl -s http://localhost:8900/api/agents/$AGENT_ID/recent | python3 -m json.tool
```

Returns the last few messages and any errors. **Run this before talking to an agent.** It tells you whether they're mid-task, idle, or stuck.

### 5. How full is the agent's context?

```bash
curl -s http://localhost:8900/api/agents/$AGENT_ID/context | python3 -m json.tool
```

```json
{"used_tokens": 142000, "max_tokens": 200000, "percent": 71, "model": "sonnet"}
```

If `percent` is over 80, time to reset that agent.

### 6. Send the agent some work

```bash
curl -s -X POST http://localhost:8900/api/orchestrate \
  -H "Content-Type: application/json" \
  -d '{"agent":"LegalAgent","instruction":"Summarize the non-compete clause in plain English."}'
```

The call returns immediately. The agent does the work in the background.

### 7. Watch progress

Wait a few seconds, then check `/recent` again:

```bash
curl -s http://localhost:8900/api/agents/$AGENT_ID/recent | python3 -m json.tool
```

Or watch the dashboard view — what needs your attention right now:

```bash
curl -s http://localhost:8900/api/attention | python3 -m json.tool
```

This is the single best "what should I look at?" call.

### 8a. The pre-built terminal dashboard

Skip writing your own loop — there's a script for this:

```bash
./dashboard.py              # live, refreshes every 3 seconds
./dashboard.py --once       # print one snapshot and exit
./dashboard.py --interval 1 # refresh every 1 second
```

Shows: server status, all agents with context %, anything needing your attention, and recent activity. Pure ASCII with ANSI colors. `Ctrl+C` to quit.

### 8b. Live monitoring (loops every 5 seconds)

```bash
while true; do
  clear
  echo "=== Agents ==="
  curl -s http://localhost:8900/api/agents | \
    python3 -c "import sys,json; [print(f\"  {a['name']:20} [{a['status']}]\") for a in json.load(sys.stdin)['agents']]"
  echo ""
  echo "=== Needs attention ==="
  curl -s http://localhost:8900/api/attention | python3 -m json.tool
  sleep 5
done
```

Hit `Ctrl+C` to stop. Poor man's dashboard, but it works.

### 9. Read a finished report in full

```bash
# List unread reports
curl -s "http://localhost:8900/api/reports?acknowledged=false" | python3 -m json.tool

# Read one in detail (replace 42 with a real report id)
curl -s "http://localhost:8900/api/reports/42?zoom=details" | python3 -m json.tool

# Mark it read
curl -s -X POST http://localhost:8900/api/reports/42/acknowledge
```

### Tip: save common calls as shell aliases

Add these to your `~/.zshrc`:

```bash
alias sutra-agents='curl -s http://localhost:8900/api/agents | python3 -m json.tool'
alias sutra-attention='curl -s http://localhost:8900/api/attention | python3 -m json.tool'
alias sutra-health='curl -s http://localhost:8900/api/health'
```

Now `sutra-agents` from any terminal shows you the team.

---

## How everything fits together — a typical flow

You want an agent to fix a bug:

1. **`POST /api/agents`** — make an agent in your repo folder
2. **`POST /api/orchestrate`** — tell it to fix the bug
3. **`GET /api/agents/{id}/recent`** — check on it (call as often as you want)
4. **`GET /api/attention`** — eventually it appears here as "completed"
5. **`GET /api/reports/{id}?zoom=details`** — read the full report
6. **`POST /api/reports/{id}/acknowledge`** — mark as read
7. **`GET /api/agents/{id}/commits`** — see what it actually committed

That's the loop. Everything else in this doc is for special cases.

---

## The one rule for Sutra (the orchestrator)

When Sutra dispatches work, it uses **`curl` against this API** — not `Agent` or `SendMessage` tools. Those would spawn fresh Claude processes that don't know about the running agents. The API is the one source of truth.
