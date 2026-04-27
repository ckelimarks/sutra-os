-- Agent Chat Database Schema
-- SQLite database for managing AI agent chat threads

-- Agents table
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    display_name TEXT,
    avatar_path TEXT,
    emoji TEXT DEFAULT '🤖',
    provider TEXT DEFAULT 'claude',
    model TEXT DEFAULT 'sonnet',
    cwd TEXT NOT NULL,
    system_prompt TEXT,
    role TEXT DEFAULT 'worker',  -- 'worker' | 'manager' | 'orchestrator'
    status TEXT DEFAULT 'offline',  -- 'offline' | 'online' | 'busy'
    notification TEXT DEFAULT NULL,  -- NULL | 'attention' | 'done'
    permission_tier TEXT DEFAULT 'autonomous',  -- 'autonomous' | 'supervised' | 'restricted'
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Threads (1:1 with agents)
CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL UNIQUE,
    session_id TEXT,  -- for --resume
    last_activity DATETIME,
    unread_count INTEGER DEFAULT 0,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);

-- Messages
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id TEXT NOT NULL,
    role TEXT NOT NULL,  -- 'user' | 'assistant'
    content TEXT NOT NULL,
    cost_usd REAL DEFAULT 0.0,
    duration_secs REAL DEFAULT 0.0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (thread_id) REFERENCES threads(id) ON DELETE CASCADE
);

-- Reports (Manager inbox)
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    type TEXT NOT NULL,  -- 'decision' | 'plan' | 'blocked' | 'complete' | 'checkpoint'
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    payload JSON,
    acknowledged BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);

-- Session Registry (persistent, survives agent deletion)
CREATE TABLE IF NOT EXISTS session_registry (
    session_id TEXT PRIMARY KEY,
    agent_id TEXT,               -- may be NULL if agent was deleted
    agent_name TEXT NOT NULL,     -- preserved even after deletion
    cwd TEXT NOT NULL,
    model TEXT,
    session_file TEXT,            -- full path to .jsonl on disk
    last_active DATETIME,
    message_count INTEGER DEFAULT 0,
    total_cost_usd REAL DEFAULT 0.0,
    is_current BOOLEAN DEFAULT TRUE,  -- most recent session for this agent
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE SET NULL
);

-- Agent Interactions (tracks orchestration edges for neural-net visualization)
CREATE TABLE IF NOT EXISTS agent_interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_agent_id TEXT NOT NULL,
    to_agent_id TEXT NOT NULL,
    interaction_type TEXT DEFAULT 'orchestrate',  -- orchestrate | mention | shared_context | configured
    instruction_summary TEXT,                      -- first 200 chars of instruction
    cost_usd REAL DEFAULT 0.0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (from_agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    FOREIGN KEY (to_agent_id) REFERENCES agents(id) ON DELETE CASCADE
);

-- Instruction queue (persists across restarts, auto-drains on agent idle)
CREATE TABLE IF NOT EXISTS instruction_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    instruction TEXT NOT NULL,
    priority TEXT DEFAULT 'normal',  -- 'normal' | 'high'
    status TEXT DEFAULT 'pending',   -- 'pending' | 'dispatched' | 'failed'
    error TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    dispatched_at DATETIME,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);

-- Pending approvals (supervised tier)
CREATE TABLE IF NOT EXISTS pending_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    instruction TEXT NOT NULL,
    requesting_agent_id TEXT,
    status TEXT DEFAULT 'pending',  -- 'pending' | 'approved' | 'rejected'
    rejection_reason TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    resolved_at DATETIME,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_reports_agent ON reports(agent_id);
CREATE INDEX IF NOT EXISTS idx_reports_acknowledged ON reports(acknowledged);
CREATE INDEX IF NOT EXISTS idx_threads_last_activity ON threads(last_activity);
CREATE INDEX IF NOT EXISTS idx_session_registry_agent ON session_registry(agent_id);
CREATE INDEX IF NOT EXISTS idx_session_registry_cwd ON session_registry(cwd);
CREATE INDEX IF NOT EXISTS idx_interactions_from ON agent_interactions(from_agent_id);
CREATE INDEX IF NOT EXISTS idx_interactions_to ON agent_interactions(to_agent_id);
CREATE INDEX IF NOT EXISTS idx_interactions_created ON agent_interactions(created_at);
CREATE INDEX IF NOT EXISTS idx_queue_agent ON instruction_queue(agent_id);
CREATE INDEX IF NOT EXISTS idx_queue_status ON instruction_queue(status);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON pending_approvals(status);
CREATE INDEX IF NOT EXISTS idx_approvals_agent ON pending_approvals(agent_id);
