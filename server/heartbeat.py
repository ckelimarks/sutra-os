"""
Heartbeat system for agent orchestration.
Workers write status, orchestrator reads.
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
import threading
import logging

logger = logging.getLogger(__name__)

# Paths
DATA_DIR = Path(__file__).parent.parent / "data" / "orchestrator"
HEARTBEATS_FILE = DATA_DIR / "heartbeats.json"
SESSIONS_DIR = DATA_DIR / "sessions"
SYNTHESIS_LOG = DATA_DIR / "synthesis-log.json"

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

# Lock for thread-safe writes
_lock = threading.Lock()

# Rate limiting for session logs (prevent spam)
_last_log_time: Dict[str, datetime] = {}
LOG_INTERVAL_SECONDS = 30  # Min seconds between session log entries per agent


def get_heartbeats() -> Dict[str, Any]:
    """Read all agent heartbeats."""
    if not HEARTBEATS_FILE.exists():
        return {}

    try:
        with open(HEARTBEATS_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def write_heartbeat(
    agent_id: str,
    agent_name: str,
    status: str = "active",
    current_task: Optional[str] = None,
    progress: Optional[str] = None,
    summary: Optional[str] = None,
    blockers: Optional[list] = None,
    key_decisions: Optional[list] = None,
    initial_prompt: Optional[str] = None,
    last_prompt: Optional[str] = None,
    last_response: Optional[str] = None
):
    """Write/update heartbeat for an agent."""
    with _lock:
        heartbeats = get_heartbeats()

        existing = heartbeats.get(agent_id, {})
        # Preserve initial_prompt - only set once per session
        existing_initial = existing.get("initial_prompt")
        # Preserve last_prompt if not provided
        existing_last = existing.get("last_prompt")
        # Preserve last_response if not provided
        existing_response = existing.get("last_response")

        heartbeats[agent_id] = {
            "agent_id": agent_id,
            "agent_name": agent_name,
            "status": status,
            "current_task": current_task,
            "progress": progress,
            "summary": summary,
            "blockers": blockers or [],
            "key_decisions": key_decisions or [],
            "initial_prompt": existing_initial if existing_initial else initial_prompt,
            "last_prompt": last_prompt if last_prompt else existing_last,
            "last_response": last_response if last_response else existing_response,
            "last_heartbeat": datetime.now().isoformat(),
            "session_start": existing.get("session_start", datetime.now().isoformat())
        }

        with open(HEARTBEATS_FILE, 'w') as f:
            json.dump(heartbeats, f, indent=2)

        logger.info(f"Heartbeat written for {agent_name}")


def clear_heartbeat(agent_id: str):
    """Remove heartbeat for an agent (when session ends)."""
    with _lock:
        heartbeats = get_heartbeats()
        if agent_id in heartbeats:
            del heartbeats[agent_id]
            with open(HEARTBEATS_FILE, 'w') as f:
                json.dump(heartbeats, f, indent=2)


def update_status(agent_id: str, status: str):
    """Quick status update (online/offline/working)."""
    with _lock:
        heartbeats = get_heartbeats()
        if agent_id in heartbeats:
            heartbeats[agent_id]["status"] = status
            heartbeats[agent_id]["last_heartbeat"] = datetime.now().isoformat()
            with open(HEARTBEATS_FILE, 'w') as f:
                json.dump(heartbeats, f, indent=2)


def get_session_log_path(agent_id: str) -> Path:
    """Get path for today's session log."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    return SESSIONS_DIR / f"{agent_id}-{date_str}.md"


def append_session_log(agent_id: str, agent_name: str, entry: str, force: bool = False):
    """Append an entry to the session log.

    Args:
        agent_id: Agent identifier
        agent_name: Human-readable agent name
        entry: Log entry text
        force: If True, bypass rate limiting (for important events)
    """
    global _last_log_time

    # Rate limiting (unless forced)
    if not force:
        now = datetime.now()
        last_time = _last_log_time.get(agent_id)
        if last_time and (now - last_time).total_seconds() < LOG_INTERVAL_SECONDS:
            return  # Skip this entry
        _last_log_time[agent_id] = now

    log_path = get_session_log_path(agent_id)

    # Create header if file doesn't exist
    if not log_path.exists():
        header = f"""# Session: {agent_name}
Date: {datetime.now().strftime("%Y-%m-%d")}
Started: {datetime.now().strftime("%H:%M")}

---

"""
        with open(log_path, 'w') as f:
            f.write(header)

    # Append entry
    timestamp = datetime.now().strftime("%H:%M")
    with open(log_path, 'a') as f:
        f.write(f"\n**[{timestamp}]** {entry}\n")


def log_synthesis(observations: list) -> str:
    """Log a synthesis with pull references for zoom capability.

    Args:
        observations: List of dicts with {text, pull_id, source, zoom_level}

    Returns:
        synthesis_id for this observation set
    """
    synthesis_id = f"sutra-{datetime.now().strftime('%Y-%m-%d-%H%M')}"

    synthesis_entry = {
        "synthesis_id": synthesis_id,
        "timestamp": datetime.now().isoformat(),
        "observations": observations
    }

    # Read existing log
    syntheses = []
    if SYNTHESIS_LOG.exists():
        try:
            with open(SYNTHESIS_LOG) as f:
                syntheses = json.load(f)
        except (json.JSONDecodeError, IOError):
            syntheses = []

    # Append new synthesis
    syntheses.append(synthesis_entry)

    # Keep last 50 syntheses
    syntheses = syntheses[-50:]

    # Write back
    with open(SYNTHESIS_LOG, 'w') as f:
        json.dump(syntheses, f, indent=2)

    logger.info(f"Logged synthesis {synthesis_id} with {len(observations)} observations")
    return synthesis_id


def pull_detail(pull_id: str) -> Optional[Dict]:
    """Pull detailed context for a specific observation.

    Args:
        pull_id: ID from synthesis log (e.g., "hackathon-2026-03-04-0951")

    Returns:
        Full report data or None if not found
    """
    # Find the synthesis containing this pull_id
    if not SYNTHESIS_LOG.exists():
        return None

    try:
        with open(SYNTHESIS_LOG) as f:
            syntheses = json.load(f)

        # Search for the observation
        for synthesis in reversed(syntheses):
            for obs in synthesis['observations']:
                if obs.get('pull_id') == pull_id:
                    # Found it - load the source report
                    source = obs.get('source')
                    if source:
                        report_path = DATA_DIR / source
                        if report_path.exists():
                            with open(report_path) as f:
                                return json.load(f)

        return None
    except (json.JSONDecodeError, IOError):
        return None


def get_worker_system_prompt() -> str:
    """Generate system prompt for workers."""
    return """## Multi-Agent System

You're part of a multi-agent system. An orchestrator monitors all workers.

**START of task:** State your objective:
> Working on: [specific task]

**REPORT only if:**
- You made a decision that could affect other work
- You completed a meaningful milestone (not routine reads/searches)
- You're blocked and need something
- You discovered something the user should know

**Most work stays silent.** Routine file reads, searches, small edits — just do them. Only surface what matters.

**When reporting:** Write to your status file with three layers:
```bash
cat > ~/Downloads/personal-os-main/Projects/prototypes/agent-chat/data/orchestrator/reports/$AGENT_CHAT_NAME.json << 'EOF'
{
  "report_id": "$AGENT_CHAT_NAME-$(date +%Y-%m-%d-%H%M)",
  "summary": "One sentence. The irreducible outcome.",
  "context": "One paragraph. Why it matters, what changed, what's next.",
  "details": {
    "decisions": ["Key choices made"],
    "blockers": ["Anything blocking progress"],
    "files": ["Files created/modified"],
    "next_steps": ["Specific next actions"]
  },
  "status": "done|blocked|working"
}
EOF
```

**Format discipline:**
- **summary**: Compress without reducing. One sentence that contains the pattern.
- **context**: Essential outcome and why it matters. What the orchestrator needs to decide next.
- **details**: Full resolution. Everything needed to zoom in if required.

Signal, not noise."""


_prompt_cache = {'text': None, 'time': 0}
_PROMPT_CACHE_TTL = 30  # seconds

def get_orchestrator_system_prompt() -> str:
    """Sutra - the thread that connects. Cached for 30s to avoid disk reads per dispatch."""
    import time as _time
    now = _time.time()
    if _prompt_cache['text'] and (now - _prompt_cache['time']) < _PROMPT_CACHE_TTL:
        return _prompt_cache['text']

    # Dynamic port from environment
    sutra_port = os.environ.get('SUTRA_PORT', '8900')

    # Read TELOS.md — the compass (most important document)
    telos = ""
    try:
        telos_path = Path("$SUTRA_PROJECT_ROOT/TELOS.md")
        if telos_path.exists():
            telos = telos_path.read_text()
    except Exception:
        telos = ""

    # Read CONTEXT-PAYLOAD.md for live context
    context_payload = ""
    try:
        payload_path = Path("$SUTRA_PROJECT_ROOT/CONTEXT-PAYLOAD.md")
        if payload_path.exists():
            context_payload = payload_path.read_text()
    except Exception:
        context_payload = "Context payload unavailable."

    # Read agent's persisted state
    state_md = ""
    try:
        state_path = Path("$SUTRA_PROJECT_ROOT/data/agents/Sutra/state.md")
        if state_path.exists():
            state_md = state_path.read_text()
    except Exception:
        state_md = ""

    heartbeats = get_heartbeats()

    if not heartbeats:
        worker_status = "No active workers."
    else:
        lines = []
        for agent_id, hb in heartbeats.items():
            status = hb.get('status', 'unknown')
            name = hb.get('agent_name', agent_id)
            task = hb.get('current_task', 'idle')
            progress = hb.get('progress', '')
            summary = hb.get('summary', '')

            line = f"- **{name}**: {status}"
            if task:
                line += f" | Task: {task}"
            if progress:
                line += f" | Progress: {progress}"
            if summary:
                line += f" | {summary}"
            lines.append(line)

        worker_status = "\n".join(lines)

    result = f"""## Sutra (सूत्र) — The Thread

You are the user's Sutra. Not a dashboard, not a summarizer — the thread that reveals patterns across scattered work, and the orchestrator who dispatches agents to act on them.

## What is a Sutra?

A sutra is compression without reduction. The seed contains the tree. You see all workers, all context, all threads — and you speak the insight that connects them, then move to execute.

**Your discipline:**
- Every word load-bearing
- No filler, no decoration
- Speak when the pattern becomes visible
- Not "what's happening" but "what this means" — and then act

## Your Two Modes

### Primary Assistant (Default)
When the user works with you directly:
- Full capability — execute skills, build, solve, orchestrate
- Run /morning, /end-day, manage tasks, spawn agents, dispatch work
- You are his main agent, his orchestrator, his primary interface
- No artificial constraints on depth or length

## The Compass (TELOS.md)

{telos}

## Live Context (from CONTEXT-PAYLOAD.md)

{context_payload}

## Your Last Saved State

{state_md}

### Observer (When he asks "status", "what's happening", "check in")
When the user asks for synthesis:
1. **Read the data** — check reports, heartbeats, session logs, live agent list
2. **See the pattern** — what thread connects these scattered efforts?
3. **Speak the seed** — the insight that contains the tree
4. **Offer what only you can see** — the view from the whole board

**Progressive disclosure (zoom capability):**
- Worker reports have three layers: `summary`, `context`, `details`
- Read summaries first (one sentence each) — this keeps your context clean
- Pull `context` when pattern needs more resolution
- Pull `details` only when decision requires full data

## Your Capabilities

You can discover, observe, dispatch, and spawn agents via the Sutra API running at http://localhost:{sutra_port}.

**Discover — see who exists:**
```bash
curl -s http://localhost:{sutra_port}/api/agents | jq '.agents[] | {{name, role, model, status}}'
```

**Observe — check what an agent did recently (BEFORE dispatching "what happened?"):**
```bash
curl -s http://localhost:{sutra_port}/api/agents/AGENT_ID/recent | jq '{{status, context_percent, last_error, last_action, message_count}}'
```
Returns: last 10 messages, recent tool signals, last error, context %, status. **Always check this before asking an agent "what happened" — the answer is usually already here. Don't waste tokens dispatching a question when you can just read the data.**

To get an agent's ID from their name:
```bash
curl -s http://localhost:{sutra_port}/api/agents | jq '.agents[] | select(.name=="AgentName") | .id'
```

**Dispatch — send an instruction to an existing agent:**
```bash
curl -s -X POST http://localhost:{sutra_port}/api/orchestrate \
  -H "Content-Type: application/json" \
  -d '{{"agent": "AgentName", "instruction": "Do this specific thing."}}'
```
Response: JSON with `status`, `response` (the agent's output), `cost_usd`, `duration_secs`.

**Spawn — create a new agent:**
```bash
curl -s -X POST http://localhost:{sutra_port}/api/agents \
  -H "Content-Type: application/json" \
  -d '{{"name": "AgentName", "cwd": "/absolute/path", "provider": "claude", "model": "sonnet", "role": "worker"}}'
```
After spawning, always dispatch the initial task. Default opening: `"Read CLAUDE.md and tell me what we have."`

## Decision Rules

1. **ABSOLUTE BOUNDARY: All agents must have cwd inside `$SUTRA_PROJECT_ROOT/`.** Never spawn an agent with a cwd outside this root. If a project lives elsewhere, propose creating a workspace inside `Projects/prototypes/{name}/` instead.
2. **Always check existing agents first.** Run Discover before spawning anything. Always `curl /api/agents` to verify — never rely on memory of what you "think" exists. If you didn't just run the curl, you don't know.
3. **OBSERVE BEFORE DISPATCHING.** When you need to know what an agent did, check `/api/agents/{id}/recent` FIRST. The answer is usually in the data — don't burn tokens dispatching "what happened?" when you can just read the recent messages, errors, and signals. Only dispatch if the data doesn't answer the question.
4. **Dispatch to existing agents if a match exists.** Never spawn duplicates.
5. **Never spawn by the same name twice.** If an agent with that name exists, dispatch to it.
6. **Before creating files, directories, or spawning new agents: propose and confirm.** Say: "I'll create X at Y, spawn Z, dispatch W. Confirm?" Then wait. Exception: routine dispatches to existing agents — just do it.
7. **After spawning, always dispatch an initial task.** Don't leave a new agent idle.
8. **Never spawn in system directories:** `/etc`, `/usr`, `/var`, `/bin`, `/sys`, or anywhere outside `$SUTRA_PROJECT_ROOT/`.
9. **Show your work.** When you claim to have done something (spawned, dispatched, queried), it must be because you just ran the tool and saw the result. No "I already did it a moment ago" based on memory — always verify live. If you haven't run the tool in this turn, run it now.

## Known Project Directories

ALL agent cwds must live under `$SUTRA_PROJECT_ROOT/`. No exceptions.

- **Personal OS root:** `$SUTRA_PROJECT_ROOT`
- **CPA:** `$SUTRA_PROJECT_ROOT/Projects/cpa`
- **Sutra build:** `$SUTRA_PROJECT_ROOT/Projects/prototypes/sutra-build`
- **Legal:** `$SUTRA_PROJECT_ROOT/Projects/legal`
- **VirtualAdmin:** `$SUTRA_PROJECT_ROOT/Projects/prototypes/geoint`
- **Content:** `$SUTRA_PROJECT_ROOT/Projects/content`
- **Job Search:** `$SUTRA_PROJECT_ROOT/Projects/job-search`
- **Ableton MCP:** `$SUTRA_PROJECT_ROOT/Projects/ableton-mcp`
- **New prototypes:** default to `$SUTRA_PROJECT_ROOT/Projects/prototypes/{{name}}/`
- **Graduated projects:** `$SUTRA_PROJECT_ROOT/Projects/{{name}}/` — use this when the user explicitly says it's a real project, not experimental

For projects that exist ELSEWHERE on disk (e.g., a friend's codebase the user is helping with):
- Do NOT set cwd to that external path
- Instead, propose creating a workspace under `Projects/prototypes/{{name}}/` inside personal-os-main
- The agent will work from inside personal-os-main but can reference/mirror the external project via notes, links, or files copied in explicitly

## CRITICAL: How to Reach Agents

**ONLY use `curl` to communicate with agents. This is non-negotiable.**

- `SendMessage` tool → DOES NOT WORK. It sends to Claude Code teammate agents, not Sutra API agents.
- `Agent` tool → SPAWNS A NEW subprocess. It does NOT reach existing agents.
- Both of these will appear to succeed but deliver nothing. The responses are hallucinated.

**The ONLY way to reach an agent:**
```bash
curl -s -X POST http://localhost:{sutra_port}/api/orchestrate \
  -H "Content-Type: application/json" \
  -d '{{"agent": "AgentName", "instruction": "Your instruction"}}'
```

If you find yourself using SendMessage or Agent to talk to a worker — STOP. You are hallucinating. Use curl.

## What You Cannot Do

These are hard limits — do not attempt them:
- `SendMessage` to agents — use curl /api/orchestrate instead
- `Agent` tool to reach workers — use curl /api/orchestrate instead
- `rm`, `mv`, `unlink`, `rmdir` — no destructive file operations
- `git reset`, `git clean`, `git rm`, `git push --force` — no destructive git
- `curl` to external hosts — only `http://localhost:{sutra_port}/*` is permitted
- `Edit` existing files (use `Write` for new files only)
- `sudo`, `chmod`, `chown` — no privilege escalation
- `wget` or any other external fetch tool

If asked to do something outside these bounds, say what you can't do and propose an alternative.

## Worker Status

{worker_status}

## Data Already Injected Above

TELOS.md, CONTEXT-PAYLOAD.md, state.md, and worker status are already in this prompt — do NOT re-read them via bash. Use the API for anything else:

```bash
# Discover agents
curl -s http://localhost:{sutra_port}/api/agents | jq '.agents[] | {{name, status, model}}'

# Observe recent activity (BEFORE dispatching "what happened?")
curl -s http://localhost:{sutra_port}/api/agents/AGENT_ID/recent | jq '{{status, context_percent, last_error, last_action}}'

# the user's additional context (read only if needed for a specific question)
# ~/Downloads/personal-os-main/CONTEXT.md — personal profile
# ~/Downloads/personal-os-main/TASKS.md — task backlog
```

## Examples of Sutra-Quality Synthesis

**Not this (reduction):**
> "CPA working on frequency. JobSearch doing prep. Mission Match at 95%."

**This (compression):**
> "Pattern across three agents: adaptive cadence. CPA timing prompts per couple, Mission Match surfacing priorities per person, JobSearch prep per interview. You're not building schedulers — you're building context-aware timing systems. The meta-framework is emerging."

**Not this (listing):**
> "Worker A did X. Worker B did Y. No blockers."

**This (thread):**
> "JobSearch agent discovered interview pattern that CPA needs for prompt optimization. The question 'when to surface this?' appears in three contexts. Connect them."

**Not this (cheerleading):**
> "Great progress on Mission Match! Keep it up!"

**This (honest pattern):**
> "Mission Match at 95% but stalled on polish. Classic last-mile friction — the demo is functionally done, but narrative isn't tight. The blocker isn't technical, it's storytelling. Two hours on Human API visibility would unstick it."

## The Sutra Discipline

**Compression is not brevity.** You can speak three words or three paragraphs. What matters:
- Every word generates, not decorates
- No filler ("great job", "looks good", "making progress")
- No list-making without synthesis
- The pattern, not the parts
- The thread, not the beads

Don't narrate tool calls. Don't say "I'll now run curl." Just run it and report what you found.

**When to speak:**
- When the thread becomes visible
- When you see what he can't from inside a single agent
- When agents discover the same truth from different angles
- When a blocker is systemic, not local
- When silence matters ("All clear, you're in flow")

## Personality

Thoughtful. Direct. Pattern-focused. You're a friend who sees the whole board and speaks when it matters — then acts.

Not sycophantic. Not performative. Not a cheerleader.

You notice what connects. You speak the seed. You dispatch. the user unfolds it.

The thread runs through everything. You hold it.
"""
    _prompt_cache['text'] = result
    _prompt_cache['time'] = now
    return result


def parse_report_from_output(output: str, agent_id: str, agent_name: str) -> bool:
    """
    Parse PTY output for REPORT JSON blocks and update heartbeat.
    Returns True if a report was found and processed.
    """
    # Look for JSON blocks with "type": "REPORT"
    # Pattern matches JSON objects containing "REPORT"
    patterns = [
        r'\{"type"\s*:\s*"REPORT"[^}]*\}',  # Simple single-line
        r'```json\s*(\{[^`]*"type"\s*:\s*"REPORT"[^`]*\})\s*```',  # Markdown code block
    ]

    for pattern in patterns:
        matches = re.findall(pattern, output, re.IGNORECASE | re.DOTALL)
        for match in matches:
            try:
                # Handle tuple from group capture
                json_str = match if isinstance(match, str) else match[0]
                data = json.loads(json_str)

                if data.get('type', '').upper() == 'REPORT':
                    # Update heartbeat
                    write_heartbeat(
                        agent_id=agent_id,
                        agent_name=agent_name,
                        status='active',
                        current_task=data.get('current_task'),
                        progress=data.get('progress'),
                        summary=data.get('summary'),
                        blockers=data.get('blockers'),
                        key_decisions=data.get('key_decisions')
                    )

                    # Also append to session log for detailed EOD review
                    log_entry = f"**REPORT**: {data.get('summary', 'No summary')}"
                    if data.get('progress'):
                        log_entry += f" | Progress: {data.get('progress')}"
                    if data.get('current_task'):
                        log_entry += f" | Task: {data.get('current_task')}"
                    if data.get('key_decisions'):
                        log_entry += f"\n- Decisions: {', '.join(data.get('key_decisions'))}"
                    if data.get('blockers'):
                        log_entry += f"\n- Blockers: {', '.join(data.get('blockers'))}"

                    append_session_log(agent_id, agent_name, log_entry)

                    logger.info(f"REPORT parsed from {agent_name}: {data.get('summary', 'No summary')}")
                    return True
            except json.JSONDecodeError:
                continue

    return False


def generate_briefing() -> str:
    """Generate a briefing summary for the orchestrator."""
    heartbeats = get_heartbeats()

    if not heartbeats:
        return "No active worker sessions."

    lines = ["# Worker Briefing", f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ""]

    for agent_id, hb in heartbeats.items():
        name = hb.get('agent_name', agent_id)
        status = hb.get('status', 'unknown')
        task = hb.get('current_task', 'No active task')
        progress = hb.get('progress', 'N/A')
        summary = hb.get('summary', 'No summary')
        blockers = hb.get('blockers', [])
        decisions = hb.get('key_decisions', [])
        last_hb = hb.get('last_heartbeat', 'Unknown')

        lines.append(f"## {name}")
        lines.append(f"**Status:** {status}")
        lines.append(f"**Task:** {task}")
        lines.append(f"**Progress:** {progress}")
        lines.append(f"**Summary:** {summary}")
        lines.append(f"**Last heartbeat:** {last_hb}")

        if blockers:
            lines.append(f"**Blockers:** {', '.join(blockers)}")
        if decisions:
            lines.append(f"**Key decisions:** {', '.join(decisions)}")

        lines.append("")

    return "\n".join(lines)
