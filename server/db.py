"""
Database operations for Agent Chat.
SQLite-based storage for agents, threads, messages, and reports.
"""

import sqlite3
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

DB_PATH = Path(__file__).parent.parent / "data" / "agent-chat.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


@contextmanager
def get_connection():
    """Context manager for database connections."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Initialize database with schema."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        with open(SCHEMA_PATH) as f:
            conn.executescript(f.read())

    # Run migrations for existing databases
    _run_migrations()


def _run_migrations():
    """Run database migrations for existing databases."""
    with get_connection() as conn:
        # Check agent columns
        cursor = conn.execute("PRAGMA table_info(agents)")
        agent_cols = [row['name'] for row in cursor.fetchall()]

        if 'notification' not in agent_cols:
            conn.execute("ALTER TABLE agents ADD COLUMN notification TEXT DEFAULT NULL")

        if 'permission_tier' not in agent_cols:
            conn.execute("ALTER TABLE agents ADD COLUMN permission_tier TEXT DEFAULT 'autonomous'")

        # Check message columns
        cursor = conn.execute("PRAGMA table_info(messages)")
        msg_cols = [row['name'] for row in cursor.fetchall()]

        if 'cost_usd' not in msg_cols:
            conn.execute("ALTER TABLE messages ADD COLUMN cost_usd REAL DEFAULT 0.0")

        if 'duration_secs' not in msg_cols:
            conn.execute("ALTER TABLE messages ADD COLUMN duration_secs REAL DEFAULT 0.0")

        if 'input_tokens' not in msg_cols:
            conn.execute("ALTER TABLE messages ADD COLUMN input_tokens INTEGER DEFAULT 0")

        if 'output_tokens' not in msg_cols:
            conn.execute("ALTER TABLE messages ADD COLUMN output_tokens INTEGER DEFAULT 0")

        if 'context_tokens' not in msg_cols:
            conn.execute("ALTER TABLE messages ADD COLUMN context_tokens INTEGER DEFAULT 0")

        if 'route_reason' not in msg_cols:
            conn.execute("ALTER TABLE messages ADD COLUMN route_reason TEXT DEFAULT NULL")

        # Create session_registry if it doesn't exist
        conn.execute("""
            CREATE TABLE IF NOT EXISTS session_registry (
                session_id TEXT PRIMARY KEY,
                agent_id TEXT,
                agent_name TEXT NOT NULL,
                cwd TEXT NOT NULL,
                model TEXT,
                session_file TEXT,
                last_active DATETIME,
                message_count INTEGER DEFAULT 0,
                total_cost_usd REAL DEFAULT 0.0,
                is_current BOOLEAN DEFAULT TRUE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE SET NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_session_registry_agent ON session_registry(agent_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_session_registry_cwd ON session_registry(cwd)")

        # Add tags and last_session_summary to agents (for neural-net visualization)
        if 'tags' not in agent_cols:
            conn.execute("ALTER TABLE agents ADD COLUMN tags TEXT DEFAULT '[]'")

        if 'last_session_summary' not in agent_cols:
            conn.execute("ALTER TABLE agents ADD COLUMN last_session_summary TEXT DEFAULT NULL")

        # Create events table (REQ-1.1.1)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                agent_id TEXT,
                payload JSON,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)")

        # Create instruction_queue table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS instruction_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                instruction TEXT NOT NULL,
                priority TEXT DEFAULT 'normal',
                status TEXT DEFAULT 'pending',
                error TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                dispatched_at DATETIME,
                FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_queue_agent ON instruction_queue(agent_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_queue_status ON instruction_queue(status)")

        # Create pending_approvals table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pending_approvals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                instruction TEXT NOT NULL,
                requesting_agent_id TEXT,
                status TEXT DEFAULT 'pending',
                rejection_reason TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                resolved_at DATETIME,
                FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_approvals_status ON pending_approvals(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_approvals_agent ON pending_approvals(agent_id)")

        # Completion notifications — when a dispatch returns, mark for user review
        conn.execute("""
            CREATE TABLE IF NOT EXISTS completions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                message_id INTEGER,
                instruction TEXT,
                summary TEXT,
                cost_usd REAL DEFAULT 0.0,
                acknowledged INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                acknowledged_at DATETIME,
                FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_completions_ack ON completions(acknowledged)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_completions_agent ON completions(agent_id)")

        # Create agent_interactions table (tracks orchestration edges)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_agent_id TEXT NOT NULL,
                to_agent_id TEXT NOT NULL,
                interaction_type TEXT DEFAULT 'orchestrate',
                instruction_summary TEXT,
                cost_usd REAL DEFAULT 0.0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (from_agent_id) REFERENCES agents(id) ON DELETE CASCADE,
                FOREIGN KEY (to_agent_id) REFERENCES agents(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_interactions_from ON agent_interactions(from_agent_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_interactions_to ON agent_interactions(to_agent_id)")

        # Composite index for turn count queries (auto-reset)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_thread_role ON messages(thread_id, role)")


def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert sqlite Row to dictionary."""
    if row is None:
        return None
    return dict(row)


# =============================================================================
# Agent Operations
# =============================================================================

def create_agent(
    name: str,
    cwd: str,
    display_name: Optional[str] = None,
    emoji: str = "🤖",
    model: str = "sonnet",
    provider: str = "claude",
    system_prompt: Optional[str] = None,
    role: str = "worker"
) -> Dict[str, Any]:
    """Create a new agent and its associated thread."""
    agent_id = str(uuid.uuid4())[:8]
    thread_id = str(uuid.uuid4())[:8]

    with get_connection() as conn:
        conn.execute("""
            INSERT INTO agents (id, name, display_name, emoji, provider, model, cwd, system_prompt, role)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (agent_id, name, display_name or name, emoji, provider, model, cwd, system_prompt, role))

        conn.execute("""
            INSERT INTO threads (id, agent_id, last_activity)
            VALUES (?, ?, ?)
        """, (thread_id, agent_id, datetime.now().isoformat()))

    return get_agent(agent_id)


def get_agent(agent_id: str) -> Optional[Dict[str, Any]]:
    """Get agent by ID with thread info."""
    with get_connection() as conn:
        row = conn.execute("""
            SELECT a.*, t.id as thread_id, t.session_id, t.unread_count, t.last_activity
            FROM agents a
            LEFT JOIN threads t ON t.agent_id = a.id
            WHERE a.id = ?
        """, (agent_id,)).fetchone()
        return row_to_dict(row)


def list_agents() -> List[Dict[str, Any]]:
    """List all agents with thread info."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT a.*, t.id as thread_id, t.session_id, t.unread_count, t.last_activity
            FROM agents a
            LEFT JOIN threads t ON t.agent_id = a.id
            ORDER BY t.last_activity DESC NULLS LAST
        """).fetchall()
        return [row_to_dict(r) for r in rows]


def update_agent(agent_id: str, **kwargs) -> Optional[Dict[str, Any]]:
    """Update agent fields."""
    allowed = {'name', 'display_name', 'avatar_path', 'emoji', 'provider', 'model', 'cwd', 'system_prompt', 'role', 'status', 'notification', 'permission_tier'}
    updates = {k: v for k, v in kwargs.items() if k in allowed}

    if not updates:
        return get_agent(agent_id)

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [agent_id]

    with get_connection() as conn:
        conn.execute(f"UPDATE agents SET {set_clause} WHERE id = ?", values)

    return get_agent(agent_id)


def delete_agent(agent_id: str) -> bool:
    """Delete an agent and its thread/messages (cascading)."""
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
        return cursor.rowcount > 0


def set_agent_status(agent_id: str, status: str):
    """Update agent status (offline/online/busy)."""
    with get_connection() as conn:
        conn.execute("UPDATE agents SET status = ? WHERE id = ?", (status, agent_id))


def set_notification(agent_id: str, state: str):
    """Set notification state: 'attention', 'done', or None to clear."""
    with get_connection() as conn:
        conn.execute("UPDATE agents SET notification = ? WHERE id = ?", (state, agent_id))


def clear_notification(agent_id: str):
    """Clear notification for an agent."""
    set_notification(agent_id, None)


# =============================================================================
# Thread Operations
# =============================================================================

def get_thread(thread_id: str) -> Optional[Dict[str, Any]]:
    """Get thread by ID."""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
        return row_to_dict(row)


def get_thread_by_agent(agent_id: str) -> Optional[Dict[str, Any]]:
    """Get thread for an agent."""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM threads WHERE agent_id = ?", (agent_id,)).fetchone()
        return row_to_dict(row)


def update_thread_activity(agent_id: str):
    """Update thread last_activity timestamp for an agent."""
    with get_connection() as conn:
        conn.execute("""
            UPDATE threads SET last_activity = ? WHERE agent_id = ?
        """, (datetime.now().isoformat(), agent_id))


def update_thread_session(thread_id: str, session_id: Optional[str]):
    """Update thread session ID for --resume."""
    with get_connection() as conn:
        conn.execute("""
            UPDATE threads SET session_id = ?, last_activity = ? WHERE id = ?
        """, (session_id, datetime.now().isoformat(), thread_id))


def increment_unread(thread_id: str):
    """Increment unread count for a thread."""
    with get_connection() as conn:
        conn.execute("UPDATE threads SET unread_count = unread_count + 1 WHERE id = ?", (thread_id,))


def clear_unread(thread_id: str):
    """Clear unread count for a thread."""
    with get_connection() as conn:
        conn.execute("UPDATE threads SET unread_count = 0 WHERE id = ?", (thread_id,))


# =============================================================================
# Message Operations
# =============================================================================

def add_message(
    thread_id: str,
    role: str,
    content: str,
    cost_usd: float = 0.0,
    duration_secs: float = 0.0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    context_tokens: int = 0,
    route_reason: Optional[str] = None
) -> Dict[str, Any]:
    """Add a message to a thread."""
    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO messages (thread_id, role, content, cost_usd, duration_secs, input_tokens, output_tokens, context_tokens, route_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (thread_id, role, content, cost_usd, duration_secs, input_tokens, output_tokens, context_tokens, route_reason))

        # Update thread activity
        conn.execute("""
            UPDATE threads SET last_activity = ? WHERE id = ?
        """, (datetime.now().isoformat(), thread_id))

        row = conn.execute("SELECT * FROM messages WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return row_to_dict(row)


def get_messages(thread_id: str, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    """Get the most recent N messages for a thread, returned in chronological order."""
    with get_connection() as conn:
        # Grab the last N messages (newest first), then flip to chronological order
        rows = conn.execute("""
            SELECT * FROM (
                SELECT * FROM messages
                WHERE thread_id = ?
                ORDER BY id DESC
                LIMIT ? OFFSET ?
            ) ORDER BY id ASC
        """, (thread_id, limit, offset)).fetchall()
        return [row_to_dict(r) for r in rows]


def get_messages_since(thread_id: str, since_id: int) -> List[Dict[str, Any]]:
    """Get messages newer than a given ID."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM messages
            WHERE thread_id = ? AND id > ?
            ORDER BY created_at ASC
        """, (thread_id, since_id)).fetchall()
        return [row_to_dict(r) for r in rows]


# =============================================================================
# Report Operations
# =============================================================================

def add_report(
    agent_id: str,
    agent_name: str,
    report_type: str,
    title: str,
    summary: str,
    payload: Optional[Dict] = None
) -> Dict[str, Any]:
    """Add a report to the manager inbox."""
    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO reports (agent_id, agent_name, type, title, summary, payload)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (agent_id, agent_name, report_type, title, summary, json.dumps(payload) if payload else None))

        row = conn.execute("SELECT * FROM reports WHERE id = ?", (cursor.lastrowid,)).fetchone()
        result = row_to_dict(row)
        if result and result.get('payload'):
            result['payload'] = json.loads(result['payload'])
        return result


def get_reports(acknowledged: Optional[bool] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """Get reports, optionally filtered by acknowledged status."""
    with get_connection() as conn:
        if acknowledged is None:
            rows = conn.execute("""
                SELECT * FROM reports ORDER BY created_at DESC LIMIT ?
            """, (limit,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM reports WHERE acknowledged = ? ORDER BY created_at DESC LIMIT ?
            """, (acknowledged, limit)).fetchall()

        results = []
        for row in rows:
            d = row_to_dict(row)
            if d.get('payload'):
                d['payload'] = json.loads(d['payload'])
            results.append(d)
        return results


def get_unacknowledged_count() -> int:
    """Get count of unacknowledged reports."""
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) as count FROM reports WHERE acknowledged = FALSE").fetchone()
        return row['count'] if row else 0


def acknowledge_report(report_id: int) -> bool:
    """Mark a report as acknowledged."""
    with get_connection() as conn:
        cursor = conn.execute("UPDATE reports SET acknowledged = TRUE WHERE id = ?", (report_id,))
        return cursor.rowcount > 0


def acknowledge_all_reports() -> int:
    """Mark all reports as acknowledged."""
    with get_connection() as conn:
        cursor = conn.execute("UPDATE reports SET acknowledged = TRUE WHERE acknowledged = FALSE")
        return cursor.rowcount


# =============================================================================
# Agent Interaction Operations (neural-net edge tracking)
# =============================================================================

def log_interaction(
    from_agent_id: str,
    to_agent_id: str,
    interaction_type: str = "orchestrate",
    instruction_summary: Optional[str] = None,
    cost_usd: float = 0.0
) -> Dict[str, Any]:
    """Log an interaction between agents (for neural-net visualization)."""
    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO agent_interactions (from_agent_id, to_agent_id, interaction_type, instruction_summary, cost_usd)
            VALUES (?, ?, ?, ?, ?)
        """, (from_agent_id, to_agent_id, interaction_type,
              instruction_summary[:200] if instruction_summary else None, cost_usd))
        row = conn.execute("SELECT * FROM agent_interactions WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return row_to_dict(row)


def get_interactions(since_hours: int = 24, limit: int = 100) -> List[Dict[str, Any]]:
    """Get recent agent interactions for neural-net visualization."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT i.*,
                   a1.name as from_name, a1.display_name as from_display,
                   a2.name as to_name, a2.display_name as to_display
            FROM agent_interactions i
            LEFT JOIN agents a1 ON i.from_agent_id = a1.id
            LEFT JOIN agents a2 ON i.to_agent_id = a2.id
            WHERE i.created_at >= datetime('now', ?)
            ORDER BY i.created_at DESC
            LIMIT ?
        """, (f'-{since_hours} hours', limit)).fetchall()
        return [row_to_dict(r) for r in rows]


def update_agent_summary(agent_id: str, summary: str):
    """Update an agent's last session summary."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE agents SET last_session_summary = ? WHERE id = ?",
            (summary[:500] if summary else None, agent_id)
        )


# =============================================================================
# Event Operations (REQ-1.1.1)
# =============================================================================

def log_event(event_type: str, agent_id: Optional[str] = None, payload: Optional[Dict] = None) -> Dict[str, Any]:
    """Log an event."""
    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO events (event_type, agent_id, payload)
            VALUES (?, ?, ?)
        """, (event_type, agent_id, json.dumps(payload) if payload else None))
        row = conn.execute("SELECT * FROM events WHERE id = ?", (cursor.lastrowid,)).fetchone()
        result = row_to_dict(row)
        if result and result.get('payload'):
            result['payload'] = json.loads(result['payload'])
        return result


def get_events(event_type: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """Get events, optionally filtered by type."""
    with get_connection() as conn:
        if event_type:
            rows = conn.execute("""
                SELECT * FROM events WHERE event_type = ? ORDER BY created_at DESC LIMIT ?
            """, (event_type, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM events ORDER BY created_at DESC LIMIT ?
            """, (limit,)).fetchall()
        results = []
        for row in rows:
            d = row_to_dict(row)
            if d.get('payload'):
                d['payload'] = json.loads(d['payload'])
            results.append(d)
        return results


# =============================================================================
# Instruction Queue Operations (REQ-0.3)
# =============================================================================

def enqueue_instruction(
    agent_id: str,
    agent_name: str,
    instruction: str,
    priority: str = "normal"
) -> Dict[str, Any]:
    """Add an instruction to the queue for an agent."""
    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO instruction_queue (agent_id, agent_name, instruction, priority)
            VALUES (?, ?, ?, ?)
        """, (agent_id, agent_name, instruction, priority))
        row = conn.execute("SELECT * FROM instruction_queue WHERE id = ?",
                          (cursor.lastrowid,)).fetchone()
        return row_to_dict(row)


def get_agent_queue(agent_id: str) -> List[Dict[str, Any]]:
    """Get pending instructions for an agent, ordered by priority then time."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM instruction_queue
            WHERE agent_id = ? AND status = 'pending'
            ORDER BY CASE priority WHEN 'high' THEN 0 ELSE 1 END, created_at ASC
        """, (agent_id,)).fetchall()
        return [row_to_dict(r) for r in rows]


def dequeue_next(agent_id: str) -> Optional[Dict[str, Any]]:
    """Pop the next pending instruction for an agent. Returns None if empty."""
    with get_connection() as conn:
        row = conn.execute("""
            SELECT * FROM instruction_queue
            WHERE agent_id = ? AND status = 'pending'
            ORDER BY CASE priority WHEN 'high' THEN 0 ELSE 1 END, created_at ASC
            LIMIT 1
        """, (agent_id,)).fetchone()
        if not row:
            return None
        conn.execute("""
            UPDATE instruction_queue SET status = 'dispatched', dispatched_at = ?
            WHERE id = ?
        """, (datetime.now().isoformat(), row['id']))
        return row_to_dict(row)


def fail_queued_instruction(queue_id: int, error: str):
    """Mark a queued instruction as failed."""
    with get_connection() as conn:
        conn.execute("""
            UPDATE instruction_queue SET status = 'failed', error = ?
            WHERE id = ?
        """, (error, queue_id))


# =============================================================================
# Pending Approvals Operations (REQ-0.4)
# =============================================================================
# Completion notifications
# =============================================================================

def add_completion(
    agent_id: str,
    agent_name: str,
    thread_id: str,
    instruction: str,
    summary: str,
    message_id: Optional[int] = None,
    cost_usd: float = 0.0,
) -> Dict[str, Any]:
    """Record a completed dispatch so it surfaces in the attention pill."""
    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO completions
            (agent_id, agent_name, thread_id, message_id, instruction, summary, cost_usd)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (agent_id, agent_name, thread_id, message_id, instruction[:500], summary[:1000], cost_usd))
        row = conn.execute("SELECT * FROM completions WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return dict(row) if row else {}


def get_unacknowledged_completions(limit: int = 20) -> List[Dict[str, Any]]:
    """Fetch recent unacknowledged completions, newest first."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM completions
            WHERE acknowledged = 0
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]


def acknowledge_completion(completion_id: int) -> bool:
    from datetime import datetime
    with get_connection() as conn:
        cursor = conn.execute("""
            UPDATE completions
            SET acknowledged = 1, acknowledged_at = ?
            WHERE id = ?
        """, (datetime.utcnow().isoformat(), completion_id))
        return cursor.rowcount > 0


def acknowledge_all_completions() -> int:
    from datetime import datetime
    with get_connection() as conn:
        cursor = conn.execute("""
            UPDATE completions
            SET acknowledged = 1, acknowledged_at = ?
            WHERE acknowledged = 0
        """, (datetime.utcnow().isoformat(),))
        return cursor.rowcount


# =============================================================================

def add_pending_approval(
    agent_id: str,
    agent_name: str,
    instruction: str,
    requesting_agent_id: Optional[str] = None
) -> Dict[str, Any]:
    """Add a pending approval for a supervised agent."""
    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO pending_approvals (agent_id, agent_name, instruction, requesting_agent_id)
            VALUES (?, ?, ?, ?)
        """, (agent_id, agent_name, instruction, requesting_agent_id))
        row = conn.execute("SELECT * FROM pending_approvals WHERE id = ?",
                          (cursor.lastrowid,)).fetchone()
        return row_to_dict(row)


def get_pending_approvals() -> List[Dict[str, Any]]:
    """Get all pending approvals."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM pending_approvals
            WHERE status = 'pending'
            ORDER BY created_at ASC
        """).fetchall()
        return [row_to_dict(r) for r in rows]


def approve_instruction(approval_id: int) -> Optional[Dict[str, Any]]:
    """Approve a pending instruction. Returns the approval record."""
    with get_connection() as conn:
        conn.execute("""
            UPDATE pending_approvals
            SET status = 'approved', resolved_at = ?
            WHERE id = ? AND status = 'pending'
        """, (datetime.now().isoformat(), approval_id))
        row = conn.execute("SELECT * FROM pending_approvals WHERE id = ?",
                          (approval_id,)).fetchone()
        return row_to_dict(row)


def reject_instruction(approval_id: int, reason: str = "") -> Optional[Dict[str, Any]]:
    """Reject a pending instruction."""
    with get_connection() as conn:
        conn.execute("""
            UPDATE pending_approvals
            SET status = 'rejected', rejection_reason = ?, resolved_at = ?
            WHERE id = ? AND status = 'pending'
        """, (reason, datetime.now().isoformat(), approval_id))
        row = conn.execute("SELECT * FROM pending_approvals WHERE id = ?",
                          (approval_id,)).fetchone()
        return row_to_dict(row)


# Initialize database on import
if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
