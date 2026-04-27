"""
Session Manager for Agent Chat.
Tracks Claude CLI sessions on disk, reconciles with DB,
and enables session recovery after server restarts or agent deletion.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
import logging

import db

logger = logging.getLogger(__name__)

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

# The root of the personal-os workspace — only orchestrator should use this
WORKSPACE_ROOT = str(Path.home() / "Downloads" / "personal-os-main")
PROTOTYPES_DIR = str(Path(WORKSPACE_ROOT) / "Projects" / "prototypes")


def validate_agent_cwd(name: str, cwd: str, role: str = "worker") -> str:
    """Validate and potentially reassign an agent's working directory.

    Rules:
    - Orchestrator can use workspace root
    - Everyone else must be scoped to a subfolder
    - If a worker tries to use root, auto-create Projects/scratch/{name}/

    Returns the (possibly adjusted) cwd.
    """
    # Normalize paths for comparison
    cwd_resolved = str(Path(cwd).resolve())
    root_resolved = str(Path(WORKSPACE_ROOT).resolve())

    # Orchestrator gets root
    if role == "orchestrator":
        return cwd

    # If cwd IS root (not a subfolder), scope it
    if cwd_resolved == root_resolved:
        scratch_dir = Path(PROTOTYPES_DIR) / "scratch" / name.lower().replace(" ", "-")
        scratch_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Agent '{name}' scoped from root to {scratch_dir}")
        return str(scratch_dir)

    return cwd


def cwd_to_mangled(cwd: str) -> str:
    """Convert a working directory path to Claude's mangled project folder name.

    Claude replaces '/' and '.' with '-'.
    /Users/foo.bar/baz → -Users-foo-bar-baz
    """
    return cwd.replace("/", "-").replace(".", "-")


def scan_session_files(cwd: str) -> List[Dict[str, Any]]:
    """Scan Claude's session files on disk for a given working directory.

    Returns list of sessions sorted by last modified (newest first),
    each with: session_id, file_path, last_modified, size_bytes.
    """
    mangled = cwd_to_mangled(cwd)
    project_dir = CLAUDE_PROJECTS_DIR / mangled

    if not project_dir.exists():
        return []

    sessions = []
    for f in project_dir.glob("*.jsonl"):
        session_id = f.stem
        stat = f.stat()
        sessions.append({
            "session_id": session_id,
            "file_path": str(f),
            "last_modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "size_bytes": stat.st_size,
        })

    # Newest first
    sessions.sort(key=lambda s: s["last_modified"], reverse=True)
    return sessions


def get_latest_session(cwd: str) -> Optional[Dict[str, Any]]:
    """Get the most recently modified session file for a working directory."""
    sessions = scan_session_files(cwd)
    return sessions[0] if sessions else None


def peek_session(session_file: str, lines: int = 10) -> Dict[str, Any]:
    """Read metadata from the first few lines of a session file.

    Returns whatever we can extract: sessionId, cwd, entrypoint, agent tags, etc.
    """
    meta = {}
    try:
        with open(session_file) as f:
            for i, line in enumerate(f):
                if i >= lines:
                    break
                try:
                    entry = json.loads(line)
                    # Grab useful fields from any entry
                    if "sessionId" in entry:
                        meta["session_id"] = entry["sessionId"]
                    if "cwd" in entry:
                        meta["cwd"] = entry["cwd"]
                    if "entrypoint" in entry:
                        meta["entrypoint"] = entry["entrypoint"]
                    if "version" in entry:
                        meta["version"] = entry["version"]
                    if "model" in entry:
                        meta["model"] = entry["model"]
                    if "gitBranch" in entry:
                        meta["git_branch"] = entry["gitBranch"]
                    # Agent tags (set via env vars in process_manager)
                    if "agentId" in entry:
                        meta["agent_id"] = entry["agentId"]
                    if "agentName" in entry:
                        meta["agent_name"] = entry["agentName"]
                    # Also check data sub-objects for env var passthrough
                    data = entry.get("data", {})
                    if isinstance(data, dict):
                        env = data.get("env", {})
                        if isinstance(env, dict):
                            if "CLAUDE_AGENT_ID" in env:
                                meta["agent_id"] = env["CLAUDE_AGENT_ID"]
                            if "CLAUDE_AGENT_NAME" in env:
                                meta["agent_name"] = env["CLAUDE_AGENT_NAME"]
                except json.JSONDecodeError:
                    continue
    except (OSError, IOError) as e:
        logger.warning(f"Could not read session file {session_file}: {e}")

    return meta


def count_session_lines(session_file: str) -> int:
    """Count lines in a session file (proxy for message count)."""
    try:
        with open(session_file) as f:
            return sum(1 for _ in f)
    except (OSError, IOError):
        return 0


# =============================================================================
# Registry Operations
# =============================================================================

def register_session(
    session_id: str,
    agent_id: str,
    agent_name: str,
    cwd: str,
    model: Optional[str] = None,
    session_file: Optional[str] = None,
    cost_usd: float = 0.0
):
    """Register a session in the persistent registry.

    Called after every successful agent response.
    Marks previous sessions for this agent as not current.
    """
    with db.get_connection() as conn:
        # Mark previous sessions for this agent as not current
        conn.execute(
            "UPDATE session_registry SET is_current = FALSE WHERE agent_id = ?",
            (agent_id,)
        )

        # Upsert the new session
        conn.execute("""
            INSERT INTO session_registry
                (session_id, agent_id, agent_name, cwd, model, session_file,
                 last_active, total_cost_usd, is_current)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, TRUE)
            ON CONFLICT(session_id) DO UPDATE SET
                agent_id = excluded.agent_id,
                last_active = excluded.last_active,
                total_cost_usd = session_registry.total_cost_usd + excluded.total_cost_usd,
                is_current = TRUE
        """, (
            session_id, agent_id, agent_name, cwd, model,
            session_file, datetime.now().isoformat(), cost_usd
        ))


def get_registered_sessions(agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get sessions from registry, optionally filtered by agent."""
    with db.get_connection() as conn:
        if agent_id:
            rows = conn.execute("""
                SELECT * FROM session_registry
                WHERE agent_id = ?
                ORDER BY last_active DESC
            """, (agent_id,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM session_registry
                ORDER BY last_active DESC
            """).fetchall()
        return [db.row_to_dict(r) for r in rows]


def get_orphaned_sessions() -> List[Dict[str, Any]]:
    """Find sessions whose agent was deleted (agent_id is NULL)."""
    with db.get_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM session_registry
            WHERE agent_id IS NULL
            ORDER BY last_active DESC
        """).fetchall()
        return [db.row_to_dict(r) for r in rows]


def get_current_session(agent_id: str) -> Optional[Dict[str, Any]]:
    """Get the current (most recent) session for an agent."""
    with db.get_connection() as conn:
        row = conn.execute("""
            SELECT * FROM session_registry
            WHERE agent_id = ? AND is_current = TRUE
        """, (agent_id,)).fetchone()
        return db.row_to_dict(row)


# =============================================================================
# Reconciliation
# =============================================================================

def reconcile_on_startup():
    """Reconcile DB session IDs with Claude's session files on disk.

    Called once at server start. For each agent:
    1. If thread has a session_id, verify the file exists on disk
    2. If thread has no session_id AND cwd is unique to this agent,
       scan disk for the latest session
    3. If cwd is shared by multiple agents, only match sessions
       that have agent tags (CLAUDE_AGENT_ID) or are in the registry
    4. Register any found sessions in the registry

    Returns a summary of what was found/fixed.
    """
    agents = db.list_agents()
    summary = {
        "agents_checked": 0,
        "sessions_recovered": 0,
        "sessions_verified": 0,
        "stale_sessions_cleared": 0,
        "skipped_ambiguous": 0,
        "disk_sessions_found": 0,
        "details": []
    }

    # Build cwd→agents map to detect shared cwds
    cwd_agents: Dict[str, List[str]] = {}
    for agent in agents:
        cwd = agent["cwd"]
        cwd_agents.setdefault(cwd, []).append(agent["name"])

    for agent in agents:
        summary["agents_checked"] += 1
        agent_id = agent["id"]
        agent_name = agent["name"]
        cwd = agent["cwd"]
        thread_session_id = agent.get("session_id")  # from JOIN with threads
        cwd_is_shared = len(cwd_agents.get(cwd, [])) > 1

        # Scan disk for this agent's sessions
        disk_sessions = scan_session_files(cwd)
        if disk_sessions:
            summary["disk_sessions_found"] += len(disk_sessions)

        # Case 1: Thread has a session_id — verify it exists on disk
        if thread_session_id:
            matching = [s for s in disk_sessions if s["session_id"] == thread_session_id]
            if matching:
                register_session(
                    session_id=thread_session_id,
                    agent_id=agent_id,
                    agent_name=agent_name,
                    cwd=cwd,
                    model=agent.get("model"),
                    session_file=matching[0]["file_path"]
                )
                summary["sessions_verified"] += 1
                summary["details"].append(
                    f"{agent_name}: verified session {thread_session_id[:8]}..."
                )
            else:
                # Session file is gone — clear stale reference
                thread = db.get_thread_by_agent(agent_id)
                if thread:
                    db.update_thread_session(thread["id"], None)
                summary["stale_sessions_cleared"] += 1
                summary["details"].append(
                    f"{agent_name}: cleared stale session {thread_session_id[:8]}... (file missing)"
                )
            continue

        # Case 2: No session_id — try to recover from disk
        if not disk_sessions:
            continue

        # If cwd is shared, only recover sessions with explicit agent tags
        if cwd_is_shared:
            # Look through sessions for one tagged with this agent's ID/name
            tagged_match = None
            for s in disk_sessions:
                meta = peek_session(s["file_path"])
                if meta.get("agent_id") == agent_id or meta.get("agent_name") == agent_name:
                    tagged_match = s
                    break

            # Also check registry for a previous session assigned to this agent
            if not tagged_match:
                registered = get_current_session(agent_id)
                if registered and registered.get("session_file") and Path(registered["session_file"]).exists():
                    tagged_match = {
                        "session_id": registered["session_id"],
                        "file_path": registered["session_file"],
                        "last_modified": registered.get("last_active", ""),
                    }

            if tagged_match:
                thread = db.get_thread_by_agent(agent_id)
                if thread:
                    db.update_thread_session(thread["id"], tagged_match["session_id"])
                register_session(
                    session_id=tagged_match["session_id"],
                    agent_id=agent_id,
                    agent_name=agent_name,
                    cwd=cwd,
                    model=agent.get("model"),
                    session_file=tagged_match["file_path"]
                )
                summary["sessions_recovered"] += 1
                summary["details"].append(
                    f"{agent_name}: recovered tagged session {tagged_match['session_id'][:8]}..."
                )
            else:
                summary["skipped_ambiguous"] += 1
                others = [n for n in cwd_agents[cwd] if n != agent_name]
                summary["details"].append(
                    f"{agent_name}: skipped — shares cwd with {', '.join(others)}, no tagged session found"
                )
        else:
            # Unique cwd — safe to grab latest
            latest = disk_sessions[0]
            meta = peek_session(latest["file_path"])
            entrypoint = meta.get("entrypoint", "")

            if entrypoint == "agent-chat" or meta.get("cwd") == cwd:
                thread = db.get_thread_by_agent(agent_id)
                if thread:
                    db.update_thread_session(thread["id"], latest["session_id"])

                register_session(
                    session_id=latest["session_id"],
                    agent_id=agent_id,
                    agent_name=agent_name,
                    cwd=cwd,
                    model=agent.get("model"),
                    session_file=latest["file_path"]
                )
                summary["sessions_recovered"] += 1
                summary["details"].append(
                    f"{agent_name}: recovered session {latest['session_id'][:8]}... "
                    f"(last modified {latest['last_modified']})"
                )

    logger.info(
        f"Session reconciliation: {summary['agents_checked']} agents checked, "
        f"{summary['sessions_recovered']} recovered, "
        f"{summary['sessions_verified']} verified, "
        f"{summary['stale_sessions_cleared']} stale cleared, "
        f"{summary['skipped_ambiguous']} skipped (ambiguous), "
        f"{summary['disk_sessions_found']} total disk sessions found"
    )

    return summary


def recover_agent_session(agent_name: str, cwd: str) -> Optional[Dict[str, Any]]:
    """Attempt to recover a session for a recreated agent.

    Useful when an agent was deleted and recreated — checks both
    the registry (by name+cwd) and disk for matching sessions.
    """
    # First check registry for orphaned sessions matching this name+cwd
    with db.get_connection() as conn:
        row = conn.execute("""
            SELECT * FROM session_registry
            WHERE agent_name = ? AND cwd = ? AND agent_id IS NULL
            ORDER BY last_active DESC LIMIT 1
        """, (agent_name, cwd)).fetchone()

    if row:
        session = db.row_to_dict(row)
        # Verify file still exists
        if session.get("session_file") and Path(session["session_file"]).exists():
            return session

    # Fall back to disk scan
    latest = get_latest_session(cwd)
    if latest:
        meta = peek_session(latest["file_path"])
        if meta.get("entrypoint") == "agent-chat" or meta.get("cwd") == cwd:
            return {
                "session_id": latest["session_id"],
                "file_path": latest["file_path"],
                "last_modified": latest["last_modified"],
                "source": "disk_scan"
            }

    return None
