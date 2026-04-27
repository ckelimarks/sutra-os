#!/usr/bin/env python3
"""
Bridge Server for Agent Chat.
HTTP server handling agent management, chat messages, and reports.
"""

import json
import os
import sys
import time
import threading
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path
import logging

_server_start_time = time.time()

try:
    import psutil
except ImportError:
    psutil = None

# Add server directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

import db
import heartbeat
import session_manager
import cost_routes
import rate_limiter
from router import route_instruction, RouteDecision, parse_provider_model
from schema import create_turn
from session_writer import append_turn, DEFAULT_SESSION_DIR
import workspace
from process_manager import get_process_manager, AgentConfig, AgentResponse
# pty_manager removed — Sutra uses structured JSON only, no PTY

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PORT = int(os.environ.get('SUTRA_PORT', 8900))
WEB_DIR = Path(__file__).parent.parent / "web"
TOKEN_PATH = Path(__file__).parent.parent / "data" / ".sutra-token"
MESSAGE_SIGNAL_DIR = Path(__file__).parent.parent / "data" / "message_signals"

# Instruction queue moved to SQLite (REQ-0.3)

# Ensure message signal directory exists
MESSAGE_SIGNAL_DIR.mkdir(parents=True, exist_ok=True)

def signal_message_received(agent_id: str, thread_id: str):
  """Signal to WebSocket server that a message was received."""
  try:
    import time
    signal_file = MESSAGE_SIGNAL_DIR / f"msg_{agent_id}_{int(time.time() * 1000)}.signal"
    signal_file.write_text(json.dumps({
      "event": "message_received",
      "agent_id": agent_id,
      "thread_id": thread_id,
      "timestamp": time.time()
    }))
  except Exception as e:
    logger.error(f"Failed to signal message received: {e}")


def signal_agent_created(agent_id: str, agent_name: str):
  """Broadcast that a new agent was created. UI adds lane immediately."""
  try:
    import time
    signal_file = MESSAGE_SIGNAL_DIR / f"create_{agent_id}_{int(time.time() * 1000)}.signal"
    signal_file.write_text(json.dumps({
      "event": "agent_created",
      "agent_id": agent_id,
      "agent_name": agent_name,
      "timestamp": time.time()
    }))
  except Exception as e:
    logger.error(f"Failed to signal agent created: {e}")


def signal_agent_deleted(agent_id: str):
  """Broadcast that an agent was deleted. UI removes lane."""
  try:
    import time
    signal_file = MESSAGE_SIGNAL_DIR / f"delete_{agent_id}_{int(time.time() * 1000)}.signal"
    signal_file.write_text(json.dumps({
      "event": "agent_deleted",
      "agent_id": agent_id,
      "timestamp": time.time()
    }))
  except Exception as e:
    logger.error(f"Failed to signal agent deleted: {e}")


def signal_dispatch_started(agent_id: str, thread_id: str, user_message: str):
  """Broadcast that a dispatch started. UI creates active block immediately."""
  try:
    import time
    signal_file = MESSAGE_SIGNAL_DIR / f"dispatch_{agent_id}_{int(time.time() * 1000)}.signal"
    signal_file.write_text(json.dumps({
      "event": "dispatch_started",
      "agent_id": agent_id,
      "thread_id": thread_id,
      "user_message": user_message[:200],
      "timestamp": time.time()
    }))
  except Exception as e:
    logger.error(f"Failed to signal dispatch started: {e}")


def emit_reset_signal(agent_id: str, phase: str, detail: str = "", ok=None, extra=None):
  """Write a reset progress signal to data/signals/ — picked up by /api/signals
  and rendered by the UI's lane reset overlay.

  Phases: starting, spoof_starting, spoof_running, spoof_log,
          spoof_success, spoof_failed, spoof_no_session, fresh, complete.
  """
  try:
    signal_dir = Path(__file__).parent.parent / "data" / "signals"
    signal_dir.mkdir(parents=True, exist_ok=True)
    ts_ms = int(time.time() * 1000)
    signal_file = signal_dir / f"reset_{agent_id}_{ts_ms}.signal"
    payload = {
      "agent_id": agent_id,
      "kind": "reset_phase",
      "phase": phase,
      "detail": (detail or "")[:500],
      "timestamp": time.time(),
    }
    if ok is not None:
      payload["ok"] = bool(ok)
    if extra:
      payload.update(extra)
    signal_file.write_text(json.dumps(payload))
  except Exception as e:
    logger.debug(f"Reset signal failed: {e}")


def get_or_create_token() -> str:
    """Get or create the Sutra auth token."""
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    if TOKEN_PATH.exists():
        return TOKEN_PATH.read_text().strip()
    import secrets
    token = secrets.token_urlsafe(32)
    TOKEN_PATH.write_text(token)
    return token


def verify_token(handler) -> bool:
    """Verify bearer token from Authorization header."""
    auth = handler.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return False
    return auth[7:] == get_or_create_token()


def drain_instruction_queue(agent_id: str):
    """Check for queued instructions and dispatch the next one if available.
    Called when an agent finishes a task (transitions to 'online')."""
    next_item = db.dequeue_next(agent_id)
    if not next_item:
        return

    logger.info(f"Draining queue: dispatching instruction #{next_item['id']} to {next_item['agent_name']}")

    agent = db.get_agent(agent_id)
    if not agent:
        db.fail_queued_instruction(next_item['id'], "Agent not found")
        return

    thread = db.get_thread_by_agent(agent_id)
    if not thread:
        db.fail_queued_instruction(next_item['id'], "No thread for agent")
        return

    try:
        tier = agent.get('permission_tier', 'autonomous')
        db.add_message(thread['id'], 'user', f"[Queued] {next_item['instruction']}")
        db.set_agent_status(agent_id, 'busy')

        pm = get_process_manager()
        config = AgentConfig(
            agent_id=agent['id'],
            name=agent['name'],
            cwd=agent['cwd'],
            model=agent['model'],
            system_prompt=agent.get('system_prompt'),
            session_id=thread.get('session_id'),
            permission_tier=tier
        )

        def on_queue_complete(resp):
            usage = resp.usage or {}
            ctx = (usage.get('input_tokens', 0) or 0) + \
                  (usage.get('cache_creation_input_tokens', 0) or 0) + \
                  (usage.get('cache_read_input_tokens', 0) or 0)
            db.add_message(
                thread['id'], 'assistant', resp.text,
                cost_usd=resp.cost_usd,
                duration_secs=resp.duration_secs,
                input_tokens=usage.get('input_tokens', 0) or 0,
                output_tokens=usage.get('output_tokens', 0) or 0,
                context_tokens=ctx
            )
            if resp.session_id:
                db.update_thread_session(thread['id'], resp.session_id)
            db.set_agent_status(agent_id, 'online')
            db.increment_unread(thread['id'])
            # Recursively drain next item
            drain_instruction_queue(agent_id)

        pm.send_message_async(config, next_item['instruction'], on_queue_complete)

    except Exception as e:
        logger.error(f"Queue drain error for instruction #{next_item['id']}: {e}")
        db.fail_queued_instruction(next_item['id'], str(e))
        db.set_agent_status(agent_id, 'online')
        # Try next item in queue even if this one failed
        drain_instruction_queue(agent_id)


class AgentChatHandler(BaseHTTPRequestHandler):
    """HTTP request handler for Agent Chat API."""

    def log_message(self, format, *args):
        """Custom log format."""
        logger.info(f"{self.address_string()} - {format % args}")

    def send_json(self, data: dict, status: int = 200):
        """Send JSON response."""
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def send_error_json(self, message: str, status: int = 400):
        """Send JSON error response."""
        self.send_json({"error": message}, status)

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        """Handle GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        # API routes
        if path == '/api/health':
            self.send_json({"status": "ok", "port": PORT})

        elif path == '/api/agents':
            agents = db.list_agents()
            self.send_json({"agents": agents})

        elif path.startswith('/api/agents/') and '/context' in path:
            # /api/agents/{id}/context
            # Read from the CURRENT SESSION JSONL file (not DB, which has all sessions mixed)
            parts = path.split('/')
            agent_id = parts[3]
            agent = db.get_agent(agent_id)
            model = agent.get('model', 'sonnet') if agent else 'sonnet'
            model_max = {
                'opus': 1000000, 'claude-opus-4-6': 1000000,
                'sonnet': 200000, 'claude-sonnet-4-6': 200000,
                'haiku': 200000, 'claude-haiku-4-5': 200000,
            }
            max_tokens = model_max.get(model, 200000)

            used_tokens = 0
            try:
                thread = db.get_thread_by_agent(agent_id)
                session_id = thread.get('session_id') if thread else None
                if session_id and agent:
                    pm = get_process_manager()
                    mangled = pm._mangle_cwd(agent.get('cwd', ''))
                    session_file = Path.home() / ".claude" / "projects" / mangled / f"{session_id}.jsonl"
                    if session_file.exists():
                        # Read the LAST usage entry — not the max, the most recent
                        # This reflects the current context window state
                        last_usage = 0
                        with open(session_file) as f:
                            for line in f:
                                try:
                                    entry = json.loads(line.strip())
                                    msg = entry.get('message', {})
                                    if isinstance(msg, dict):
                                        usage = msg.get('usage', {})
                                        inp = usage.get('input_tokens', 0) or 0
                                        cache_create = usage.get('cache_creation_input_tokens', 0) or 0
                                        cache_read = usage.get('cache_read_input_tokens', 0) or 0
                                        total = inp + cache_create + cache_read
                                        if total > 0:
                                            last_usage = total  # overwrite, not max — want the latest
                                except Exception:
                                    continue
                        used_tokens = last_usage
            except Exception as e:
                logger.warning(f"Context calc failed for {agent_id}: {e}")

            percent = min(100, int((used_tokens / max_tokens) * 100)) if used_tokens > 0 else 0
            self.send_json({
                "used_tokens": used_tokens,
                "max_tokens": max_tokens,
                "percent": percent,
                "model": model,
            })

        elif path.startswith('/api/agents/') and path.count('/') == 3:
            agent_id = path.split('/')[3]
            agent = db.get_agent(agent_id)
            if agent:
                self.send_json({"agent": agent})
            else:
                self.send_error_json("Agent not found", 404)

        elif path.startswith('/api/threads/') and '/messages' in path:
            # /api/threads/{id}/messages
            parts = path.split('/')
            thread_id = parts[3]
            since_id = int(query.get('since', [0])[0])

            if since_id > 0:
                messages = db.get_messages_since(thread_id, since_id)
            else:
                messages = db.get_messages(thread_id)

            self.send_json({"messages": messages})

        elif path == '/api/reports':
            acknowledged = query.get('acknowledged', [None])[0]
            if acknowledged is not None:
                acknowledged = acknowledged.lower() == 'true'
            reports = db.get_reports(acknowledged=acknowledged)
            # Default: summary only (REQ-3.2)
            zoom = query.get('zoom', ['summary'])[0]
            if zoom == 'summary':
                for r in reports:
                    r.pop('payload', None)
            unread_count = db.get_unacknowledged_count()
            self.send_json({"reports": reports, "unread_count": unread_count})

        elif path.startswith('/api/reports/') and path.count('/') == 3:
            # GET /api/reports/{id}?zoom=summary|context|details (REQ-3.2)
            report_id = int(path.split('/')[3])
            zoom = query.get('zoom', ['summary'])[0]
            with db.get_connection() as conn:
                row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
                if not row:
                    self.send_error_json("Report not found", 404)
                    return
                report = dict(row)
                if report.get('payload'):
                    report['payload'] = json.loads(report['payload'])
                # Zoom filtering
                if zoom == 'summary':
                    report.pop('payload', None)
                elif zoom == 'context':
                    # Include summary + context from payload
                    if report.get('payload') and isinstance(report['payload'], dict):
                        report['payload'] = {
                            'context': report['payload'].get('context', ''),
                        }
                # 'details' returns everything
            self.send_json({"report": report})

        elif path == '/api/orchestrator/heartbeats':
            # Get all worker heartbeats
            heartbeats = heartbeat.get_heartbeats()
            self.send_json({"heartbeats": heartbeats})

        elif path == '/api/settings':
            # Get settings
            settings_path = Path(__file__).parent.parent / "data" / "settings.json"
            try:
                if settings_path.exists():
                    with open(settings_path) as f:
                        settings = json.load(f)
                else:
                    settings = {"orchestrator_cron_enabled": True, "orchestrator_cron_interval": 300}
                self.send_json(settings)
            except Exception as e:
                self.send_error_json(str(e), 500)

        elif path == '/api/usage':
            data, status = cost_routes.handle_get_usage(query)
            self.send_json(data, status)

        elif path == '/api/budget':
            data, status = cost_routes.handle_get_budget(query)
            self.send_json(data, status)

        elif path == '/api/sessions':
            # List all registered sessions
            agent_id = query.get('agent_id', [None])[0]
            sessions = session_manager.get_registered_sessions(agent_id)
            self.send_json({"sessions": sessions})

        elif path == '/api/sessions/orphaned':
            # Sessions whose agent was deleted
            orphaned = session_manager.get_orphaned_sessions()
            self.send_json({"orphaned": orphaned})

        elif path == '/api/sessions/reconcile':
            # Manual trigger for session reconciliation
            summary = session_manager.reconcile_on_startup()
            self.send_json({"reconciliation": summary})

        elif path == '/api/orchestrator/briefing':
            # Generate briefing summary
            briefing = heartbeat.generate_briefing()
            self.send_json({"briefing": briefing})

        elif path == '/api/interactions':
            # Get recent agent interactions for neural-net visualization
            hours = int(query.get('hours', [24])[0])
            interactions = db.get_interactions(since_hours=hours)
            self.send_json({"interactions": interactions})

        elif path == '/api/tokens':
            # Token usage dashboard — totals across all agents
            with db.get_connection() as conn:
                rows = conn.execute("""
                    SELECT a.name, a.display_name, a.status,
                           COALESCE(SUM(m.input_tokens), 0) as total_input,
                           COALESCE(SUM(m.output_tokens), 0) as total_output,
                           COALESCE(SUM(m.context_tokens), 0) as total_context,
                           MAX(m.context_tokens) as peak_context,
                           COUNT(CASE WHEN m.role = 'assistant' THEN 1 END) as turns
                    FROM agents a
                    LEFT JOIN threads t ON t.agent_id = a.id
                    LEFT JOIN messages m ON m.thread_id = t.id
                    GROUP BY a.id
                    ORDER BY total_context DESC
                """).fetchall()
                agents_usage = [dict(r) for r in rows]
                grand_total = sum((a.get('total_input', 0) or 0) + (a.get('total_output', 0) or 0) for a in agents_usage)
                grand_context = max((a.get('peak_context', 0) or 0 for a in agents_usage), default=0)
            self.send_json({
                "agents": agents_usage,
                "total_tokens": grand_total,
                "peak_context": grand_context,
            })

        elif path == '/api/slack-agent/config':
            # Get Slack agent configuration
            try:
                from slack_agent import SlackAgentConfig
            except ImportError:
                self.send_error_json("Slack agent not available", 501)
                return
            SlackAgentConfig  # noqa — used below
            config = SlackAgentConfig.load()
            self.send_json({
                "agent_id": config.agent_id,
                "channel_id": config.channel_id,
                "thread_ts": config.thread_ts,
                "state": config.state,
                "last_processed_ts": config.last_processed_ts
            })

        elif path == '/api/canvas':
            # Get canvas HTML (JSON format)
            canvas_path = Path(__file__).parent.parent / "data" / "canvas.html"
            try:
                if canvas_path.exists():
                    with open(canvas_path) as f:
                        html = f.read()
                    self.send_json({"html": html})
                else:
                    self.send_json({"html": ""})
            except Exception as e:
                self.send_error_json(str(e), 500)

        elif path == '/canvas-view':
            # Serve canvas HTML directly (for new tab)
            canvas_path = Path(__file__).parent.parent / "data" / "canvas.html"
            try:
                if canvas_path.exists():
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html')
                    self.send_header('Cache-Control', 'no-cache')
                    self.end_headers()
                    with open(canvas_path, 'rb') as f:
                        self.wfile.write(f.read())
                else:
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html')
                    self.end_headers()
                    self.wfile.write(b'<html><body style="display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;color:#666"><p>No canvas content yet</p></body></html>')
            except Exception as e:
                self.send_error(500)

        elif path == '/api/browse':
            # Directory browser
            dir_path = query.get('path', ['~'])[0]
            try:
                # Handle ~ expansion
                if dir_path.startswith('~'):
                    dir_path = str(Path.home()) + dir_path[1:]
                p = Path(dir_path).expanduser().resolve()
                if not p.exists():
                    self.send_error_json("Path not found", 404)
                    return
                if not p.is_dir():
                    self.send_error_json("Not a directory", 400)
                    return

                items = []
                # Add parent directory option
                if p.parent != p:
                    items.append({
                        "name": "..",
                        "path": str(p.parent),
                        "is_dir": True
                    })

                # List directory contents
                for item in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                    # Skip hidden files and common non-project dirs
                    if item.name.startswith('.') and item.name not in ['.']:
                        continue
                    if item.name in ['node_modules', '__pycache__', 'venv', '.git']:
                        continue
                    if item.is_dir():
                        items.append({
                            "name": item.name,
                            "path": str(item),
                            "is_dir": True
                        })

                self.send_json({
                    "current": str(p),
                    "items": items
                })
            except PermissionError:
                self.send_error_json("Permission denied", 403)
            except Exception as e:
                self.send_error_json(str(e), 500)

        elif path.startswith('/api/agents/') and path.endswith('/queue'):
            # GET /api/agents/{id}/queue — view instruction queue
            agent_id = path.split('/')[3]
            queue = db.get_agent_queue(agent_id)
            self.send_json({"queue": queue})

        elif path.startswith('/api/agents/') and path.endswith('/commits'):
            # GET /api/agents/{id}/commits — workspace commit history (REQ-2.2)
            agent_id = path.split('/')[3]
            agent = db.get_agent(agent_id)
            if not agent:
                self.send_error_json("Agent not found", 404)
                return
            commits = workspace.get_commits(agent['name'])
            self.send_json({"commits": commits})

        elif path == '/api/approvals':
            # GET /api/approvals — list pending approvals
            approvals = db.get_pending_approvals()
            self.send_json({"approvals": approvals})

        elif path == '/api/attention':
            # GET /api/attention — blockers, pending approvals, and completions
            needs_input = []
            needs_permission = []
            completed = []
            with db.get_connection() as conn:
                rows = conn.execute("""
                    SELECT id, agent_id, agent_name, type, title, summary
                    FROM reports
                    WHERE type IN ('blocked', 'needs_input')
                    ORDER BY created_at DESC
                """).fetchall()
                for row in rows:
                    r = dict(row)
                    needs_input.append({
                        "report_id": r['id'],
                        "agent_id": r['agent_id'],
                        "agent_name": r['agent_name'],
                        "type": r['type'],
                        "message": f"{r['title']} — {r['summary']}"
                    })

                rows = conn.execute("""
                    SELECT id, agent_id, agent_name, instruction
                    FROM pending_approvals
                    WHERE status = 'pending'
                    ORDER BY created_at ASC
                """).fetchall()
                for row in rows:
                    r = dict(row)
                    needs_permission.append({
                        "approval_id": r['id'],
                        "agent_id": r['agent_id'],
                        "agent_name": r['agent_name'],
                        "instruction": r['instruction']
                    })

            for c in db.get_unacknowledged_completions(limit=20):
                completed.append({
                    "completion_id": c['id'],
                    "agent_id": c['agent_id'],
                    "agent_name": c['agent_name'],
                    "thread_id": c['thread_id'],
                    "instruction": c.get('instruction') or '',
                    "summary": c.get('summary') or '',
                    "cost_usd": c.get('cost_usd') or 0.0,
                    "created_at": c.get('created_at'),
                })

            # Check for agents with reset_pending notification
            reset_pending = []
            all_agents = db.list_agents()
            for a in all_agents:
                notif = a.get('notification') or ''
                if notif.startswith('reset_pending:'):
                    try:
                        info = json.loads(notif.split(':', 1)[1])
                    except Exception:
                        info = {}
                    reset_pending.append({
                        "agent_id": a['id'],
                        "agent_name": a['name'],
                        "turn_count": info.get('turn_count', 0),
                        "threshold": info.get('threshold', 80),
                    })

            self.send_json({
                "needs_input": needs_input,
                "needs_permission": needs_permission,
                "completed": completed,
                "reset_pending": reset_pending,
            })

        elif path == '/api/status/overview':
            # GET /api/status/overview — synthesized status report
            agents_list = db.list_agents()
            agent_lines = []
            total_cost = 0.0
            total_messages = 0
            active_agents = 0

            with db.get_connection() as conn:
                for agent in agents_list:
                    agent_id = agent.get('id')
                    agent_name = agent.get('name')
                    agent_status = agent.get('status', 'offline')
                    model = agent.get('model', 'unknown')

                    # Get cost for this agent
                    cost_row = conn.execute("""
                        SELECT COALESCE(SUM(cost_usd), 0.0) as total_cost
                        FROM messages m
                        JOIN threads t ON m.thread_id = t.id
                        WHERE t.agent_id = ?
                    """, (agent_id,)).fetchone()
                    agent_cost = dict(cost_row).get('total_cost', 0.0) if cost_row else 0.0
                    total_cost += agent_cost

                    # Get message count
                    msg_row = conn.execute("""
                        SELECT COUNT(*) as count
                        FROM messages m
                        JOIN threads t ON m.thread_id = t.id
                        WHERE t.agent_id = ?
                    """, (agent_id,)).fetchone()
                    agent_msg_count = dict(msg_row).get('count', 0) if msg_row else 0
                    total_messages += agent_msg_count

                    if agent_status != 'offline':
                        active_agents += 1

                    # Get latest report
                    report_row = conn.execute("""
                        SELECT title, summary, type
                        FROM reports
                        WHERE agent_id = ?
                        ORDER BY created_at DESC
                        LIMIT 1
                    """, (agent_id,)).fetchone()

                    last_action = "idle"
                    if report_row:
                        report = dict(report_row)
                        last_action = f"{report.get('title', 'report')} — {report.get('summary', '')}"

                    agent_line = {
                        "agent_id": agent_id,
                        "agent_name": agent_name,
                        "model": model,
                        "status": agent_status,
                        "last_action": last_action,
                        "cost_usd": round(agent_cost, 2),
                        "message_count": agent_msg_count
                    }
                    agent_lines.append(agent_line)

                # Get needs-attention items
                needs_input = []
                report_rows = conn.execute("""
                    SELECT agent_id, agent_name, type, title, summary
                    FROM reports
                    WHERE type IN ('blocked', 'needs_input')
                    ORDER BY created_at DESC
                    LIMIT 5
                """).fetchall()
                for row in report_rows:
                    r = dict(row)
                    needs_input.append({
                        "agent_name": r['agent_name'],
                        "message": f"{r['title']} — {r['summary']}"
                    })

                # Get pending approvals
                needs_permission = []
                approval_rows = conn.execute("""
                    SELECT agent_name, instruction
                    FROM pending_approvals
                    WHERE status = 'pending'
                    ORDER BY created_at ASC
                    LIMIT 5
                """).fetchall()
                for row in approval_rows:
                    r = dict(row)
                    needs_permission.append({
                        "agent_name": r['agent_name'],
                        "instruction": r['instruction']
                    })

            self.send_json({
                "agents": agent_lines,
                "session_totals": {
                    "cost_usd": round(total_cost, 2),
                    "message_count": total_messages,
                    "active_agents": active_agents,
                    "total_agents": len(agents_list)
                },
                "attention": {
                    "needs_input": needs_input,
                    "needs_permission": needs_permission
                }
            })

        elif path == '/api/rate-limits':
            # GET /api/rate-limits — current rate limit state (REQ-1.2)
            states = {}
            for provider in ['claude', 'ollama']:
                s = rate_limiter.get_state(provider)
                states[provider] = {
                    'is_limited': s.is_limited,
                    'retry_after': s.retry_after,
                    'backoff_until': s.backoff_until,
                    'consecutive_limits': s.consecutive_limits,
                }
            self.send_json({"rate_limits": states})

        elif path == '/api/routing/overrides':
            # GET /api/routing/overrides — override history (REQ-1.1.1)
            events = db.get_events(event_type='routing_override')
            self.send_json({"overrides": events})

        elif path == '/api/events':
            # GET /api/events — filtered event history (REQ-3.1)
            agent_id = query.get('agent_id', [None])[0]
            event_type = query.get('type', [None])[0]
            since = query.get('since', [None])[0]
            limit = int(query.get('limit', [50])[0])
            with db.get_connection() as conn:
                sql = "SELECT * FROM events WHERE 1=1"
                params = []
                if agent_id:
                    sql += " AND agent_id = ?"
                    params.append(agent_id)
                if event_type:
                    sql += " AND event_type = ?"
                    params.append(event_type)
                if since:
                    sql += " AND created_at >= ?"
                    params.append(since)
                sql += " ORDER BY created_at DESC LIMIT ?"
                params.append(limit)
                rows = conn.execute(sql, params).fetchall()
                events = []
                for row in rows:
                    d = dict(row)
                    if d.get('payload'):
                        import json as _json
                        try:
                            d['payload'] = _json.loads(d['payload'])
                        except Exception:
                            pass
                    events.append(d)
            self.send_json({"events": events})

        elif path == '/api/sutra/token':
            # GET /api/sutra/token — get auth token (localhost only, REQ-5.2)
            token = get_or_create_token()
            self.send_json({"token": token})

        elif path.startswith('/api/sessions/') and path.endswith('/turns'):
            # GET /api/sessions/{agent_id}/turns — JSONL session turns (REQ-1.3)
            agent_id = path.split('/')[3]
            from session_writer import read_session, DEFAULT_SESSION_DIR
            from schema import turn_to_dict
            turns = read_session(DEFAULT_SESSION_DIR, agent_id)
            self.send_json({"turns": [turn_to_dict(t) for t in turns]})

        elif path == '/api/debug':
            self.send_json(self._build_debug_snapshot())

        elif path == '/api/session-files':
            # List all session JSONL files for an agent
            agent_id = query.get('agent_id', [None])[0]
            if not agent_id:
                self.send_error_json("Missing agent_id param")
                return
            agent = db.get_agent(agent_id)
            if not agent:
                self.send_error_json("Agent not found", 404)
                return
            thread = db.get_thread_by_agent(agent_id)
            current_session = thread.get('session_id') if thread else None

            pm = get_process_manager()
            mangled = pm._mangle_cwd(agent.get('cwd', ''))
            session_dir = Path.home() / ".claude" / "projects" / mangled
            sessions = []
            if session_dir.exists():
                for f in session_dir.iterdir():
                    if f.suffix != '.jsonl':
                        continue
                    sid = f.stem
                    try:
                        stat = f.stat()
                        # Check if spoofed (first line contains "Who are you?")
                        is_spoofed = False
                        line_count = 0
                        try:
                            with open(f) as fh:
                                first_line = fh.readline()
                                if 'Who are you?' in first_line:
                                    is_spoofed = True
                                line_count = 1 + sum(1 for _ in fh)
                        except Exception:
                            pass

                        sessions.append({
                            'session_id': sid,
                            'size_bytes': stat.st_size,
                            'mtime': stat.st_mtime,
                            'lines': line_count,
                            'is_current': sid == current_session,
                            'is_spoofed': is_spoofed,
                        })
                    except Exception:
                        continue

            sessions.sort(key=lambda s: s['mtime'], reverse=True)
            self.send_json({
                "sessions": sessions,
                "agent_id": agent_id,
                "cwd": mangled,
            })

        elif path.startswith('/api/session-file/'):
            # Serve raw session JSONL content
            parts = path.split('/')
            session_id = parts[3]
            cwd_param = query.get('cwd', [None])[0]
            agent_id_param = query.get('agent_id', [None])[0]

            # Resolve cwd from param or agent
            mangled_cwd = cwd_param
            if not mangled_cwd and agent_id_param:
                agent = db.get_agent(agent_id_param)
                if agent:
                    pm = get_process_manager()
                    mangled_cwd = pm._mangle_cwd(agent.get('cwd', ''))

            if not mangled_cwd:
                self.send_error_json("Missing cwd or agent_id param")
                return

            # Check for sub-agent session: ?subagent=agent-abc123.jsonl&parent=parent-session-id
            subagent_file = query.get('subagent', [None])[0]
            parent_session = query.get('parent', [None])[0]

            if subagent_file and parent_session:
                # Sub-agent path: {cwd}/{parent-session}/subagents/{subagent-file}
                session_file = Path.home() / ".claude" / "projects" / mangled_cwd / parent_session / "subagents" / subagent_file
            else:
                session_file = Path.home() / ".claude" / "projects" / mangled_cwd / f"{session_id}.jsonl"

            if not session_file.exists():
                self.send_error_json(f"Session file not found", 404)
                return

            # Security: must be under ~/.claude/projects/
            if not str(session_file.resolve()).startswith(str(Path.home() / ".claude" / "projects")):
                self.send_error_json("Invalid path", 403)
                return

            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            with open(session_file, 'rb') as f:
                self.wfile.write(f.read())

        elif path == '/session-viewer' or path == '/session-viewer.html':
            self.serve_file('session-viewer.html', 'text/html')

        elif path.startswith('/api/agents/') and '/recent' in path:
            # GET /api/agents/{id}/recent — last N messages + signals + status
            # For observability: Sutra reads this instead of dispatching "what happened?"
            parts = path.split('/')
            agent_id = parts[3]
            n = int(query.get('n', [10])[0])

            agent = db.get_agent(agent_id)
            if not agent:
                self.send_error_json("Agent not found", 404)
                return

            thread = db.get_thread_by_agent(agent_id)
            messages = []
            if thread:
                with db.get_connection() as conn:
                    rows = conn.execute(
                        "SELECT role, content, created_at, cost_usd, input_tokens, output_tokens FROM messages WHERE thread_id = ? ORDER BY id DESC LIMIT ?",
                        (thread['id'], n)
                    ).fetchall()
                    messages = [dict(r) for r in reversed(rows)]

            # Recent tool signals
            recent_signals = []
            signal_dir = Path(__file__).parent.parent / "data" / "signals"
            if signal_dir.exists():
                now = time.time()
                for f in sorted(signal_dir.iterdir(), reverse=True):
                    if not f.suffix == '.signal':
                        continue
                    try:
                        data = json.loads(f.read_text())
                        if data.get('agent_id') == agent_id and (now - data.get('timestamp', 0)) < 300:
                            recent_signals.append(data)
                            if len(recent_signals) >= 5:
                                break
                    except Exception:
                        pass

            # Context info
            ctx_pct = 0
            try:
                # Quick context check from session file
                pm = get_process_manager()
                session_id = thread.get('session_id') if thread else None
                if session_id:
                    mangled = pm._mangle_cwd(agent.get('cwd', ''))
                    sf = Path.home() / ".claude" / "projects" / mangled / f"{session_id}.jsonl"
                    if sf.exists():
                        last_ctx = 0
                        with open(sf) as fh:
                            for line in fh:
                                try:
                                    e = json.loads(line.strip())
                                    msg = e.get('message', {})
                                    if isinstance(msg, dict):
                                        u = msg.get('usage', {})
                                        total = (u.get('input_tokens', 0) or 0) + (u.get('cache_creation_input_tokens', 0) or 0) + (u.get('cache_read_input_tokens', 0) or 0)
                                        if total > 0:
                                            last_ctx = total
                                except Exception:
                                    continue
                        model_max = {'opus': 1000000, 'sonnet': 200000, 'haiku': 200000}
                        max_t = model_max.get(agent.get('model', 'sonnet'), 200000)
                        ctx_pct = min(100, int((last_ctx / max_t) * 100)) if last_ctx > 0 else 0
            except Exception:
                pass

            # Build summary
            last_error = None
            last_action = None
            for m in reversed(messages):
                content = m.get('content', '')
                if 'error' in content.lower() or 'permission' in content.lower() or 'denied' in content.lower() or 'blocked' in content.lower():
                    last_error = content[:300]
                if m['role'] == 'assistant' and not last_action:
                    last_action = content[:200]

            self.send_json({
                "agent_id": agent_id,
                "name": agent.get('name'),
                "status": agent.get('status'),
                "model": agent.get('model'),
                "cwd": agent.get('cwd'),
                "context_percent": ctx_pct,
                "recent_messages": messages,
                "recent_signals": recent_signals,
                "last_error": last_error,
                "last_action": last_action,
                "message_count": len(messages),
            })

        elif path.startswith('/api/agents/') and path.endswith('/subagents'):
            # Extract sub-agent spans from session JSONL
            parts = path.split('/')
            agent_id = parts[3]
            agent = db.get_agent(agent_id)
            if not agent:
                self.send_error_json("Agent not found", 404)
                return

            subagents = []
            _sub_session_id = None
            _sub_mangled_cwd = ''
            try:
                thread = db.get_thread_by_agent(agent_id)
                session_id = thread.get('session_id') if thread else None
                if session_id and agent:
                    _sub_session_id = session_id
                    pm = get_process_manager()
                    mangled = pm._mangle_cwd(agent.get('cwd', ''))
                    _sub_mangled_cwd = mangled
                    session_file = Path.home() / ".claude" / "projects" / mangled / f"{session_id}.jsonl"
                    if session_file.exists():
                        pending_agent_calls = {}  # tool_use_id -> {idx, prompt}
                        with open(session_file) as f:
                            for line in f:
                                try:
                                    entry = json.loads(line.strip())
                                    entry_ts = entry.get('timestamp', '')  # ISO timestamp
                                    msg = entry.get('message', {})
                                    if not isinstance(msg, dict):
                                        continue
                                    for block in msg.get('content', []):
                                        if not isinstance(block, dict):
                                            continue
                                        if block.get('type') == 'tool_use' and block.get('name') == 'Agent':
                                            tool_id = block.get('id', '')
                                            prompt = block.get('input', {}).get('prompt', '')[:200]
                                            subtype = block.get('input', {}).get('subagent_type', 'general')
                                            pending_agent_calls[tool_id] = {
                                                'prompt': prompt,
                                                'subagent_type': subtype,
                                                'start_line': len(subagents),
                                            }
                                            subagents.append({
                                                'tool_use_id': tool_id,
                                                'prompt': prompt,
                                                'subagent_type': subtype,
                                                'start_time': entry_ts,
                                                'end_time': None,
                                                'completed': False,
                                            })
                                        elif block.get('type') == 'tool_result':
                                            tool_id = block.get('tool_use_id', '')
                                            if tool_id in pending_agent_calls:
                                                idx = pending_agent_calls[tool_id]['start_line']
                                                result = block.get('content', '')
                                                if isinstance(result, list):
                                                    result = ' '.join(c.get('text', '') for c in result if isinstance(c, dict))
                                                subagents[idx]['completed'] = True
                                                subagents[idx]['end_time'] = entry_ts
                                                subagents[idx]['result_preview'] = str(result)[:300]
                                                del pending_agent_calls[tool_id]
                                except Exception:
                                    continue

                    # Also check for sub-agent session files
                    subagent_dir = Path.home() / ".claude" / "projects" / mangled / session_id / "subagents"
                    if subagent_dir.exists():
                        for f in sorted(subagent_dir.iterdir()):
                            if f.suffix == '.jsonl':
                                stat = f.stat()
                                # Try to match to a pending subagent by name
                                for sa in subagents:
                                    if not sa.get('session_file'):
                                        sa['session_file'] = f.name
                                        sa['session_size'] = stat.st_size
                                        sa['session_mtime'] = stat.st_mtime
                                        break
            except Exception as e:
                logger.warning(f"Subagent extraction failed for {agent_id}: {e}")

            self.send_json({
                "subagents": subagents,
                "agent_id": agent_id,
                "parent_session_id": _sub_session_id,
                "cwd": _sub_mangled_cwd,
            })

        elif path.startswith('/api/agents/') and path.endswith('/sessions'):
            # GET /api/agents/{id}/sessions?days=7
            #
            # Per-agent session timeline for the DAW-style block view: each
            # session = one block. Combines JSONL files on disk with spoof
            # lineage from the events table.
            parts = path.split('/')
            agent_id = parts[3]
            agent = db.get_agent(agent_id)
            if not agent:
                self.send_error_json("Agent not found", 404)
                return

            # Default to last 24 hours (the lane timeline is "DAW recording"
            # scale — older sessions are accessible via the Sessions tab in
            # the drawer). Caller can override up to 30 days if needed.
            try:
                days = float(query.get('days', ['1'])[0])
            except (ValueError, TypeError):
                days = 1.0
            days = max(0.04, min(days, 30))  # safety clamp (1h .. 30d)
            cutoff = time.time() - (days * 86400)

            thread = db.get_thread_by_agent(agent_id)
            current_session = thread.get('session_id') if thread else None
            # "Active" in the timeline-block sense means the agent is currently
            # dispatching (writing to the JSONL). An idle agent's `current_session`
            # is just its resume target — that block should be CLOSED at mtime,
            # not grow live to NOW. Without this, every agent's most-recent
            # session would extend to the playhead even when the agent is asleep.
            agent_is_busy = (agent.get('status') == 'busy')

            pm = get_process_manager()
            mangled = pm._mangle_cwd(agent.get('cwd', ''))
            session_dir = Path.home() / ".claude" / "projects" / mangled

            from datetime import datetime as _dt

            # Build spoof lineage:
            #   child_to_parent[new_id]  = old_id  — to label compressed sessions
            #   parent_to_child[old_id]  = new_id  — to mark spoofed-from sessions
            #   child_to_spoof_time[id]  = epoch   — real "born at" for compressed
            #                                       sessions (their first JSONL
            #                                       line has a replayed identity
            #                                       timestamp, which is wrong)
            child_to_parent = {}
            parent_to_child = {}
            child_to_spoof_time = {}
            try:
                spoof_events = db.get_events(event_type='spoof', limit=300)
                for ev in spoof_events:
                    if ev.get('agent_id') != agent_id:
                        continue
                    payload = ev.get('payload') or {}
                    if payload.get('outcome') != 'spoof_success':
                        continue
                    old = payload.get('old_session_id')
                    new = payload.get('new_session_id')
                    if old and new:
                        child_to_parent[new] = old
                        parent_to_child[old] = new
                        # created_at is "YYYY-MM-DD HH:MM:SS" UTC from sqlite default
                        ca = ev.get('created_at')
                        if ca:
                            try:
                                child_to_spoof_time[new] = _dt.fromisoformat(
                                    str(ca).replace(' ', 'T') + ('+00:00' if '+' not in str(ca) and 'Z' not in str(ca) else '')
                                ).timestamp()
                            except Exception:
                                pass
            except Exception as e:
                logger.debug(f"Failed to read spoof events for {agent_id}: {e}")

            def _read_first_timestamp(path_obj):
                """First non-empty JSONL line's timestamp (ISO-8601 → epoch)."""
                try:
                    with open(path_obj, 'r') as fh:
                        for line in fh:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                obj = json.loads(line)
                            except Exception:
                                continue
                            ts = obj.get('timestamp')
                            if ts:
                                try:
                                    if isinstance(ts, (int, float)):
                                        return float(ts)
                                    return _dt.fromisoformat(str(ts).replace('Z', '+00:00')).timestamp()
                                except Exception:
                                    continue
                    return None
                except Exception:
                    return None

            def _is_ephemeral_artifact(path_obj):
                """True if the JSONL is a Continuum spoof intermediate, not a real
                conversation. Real sessions have either many turns or `progress`
                events from tool calls; spoof intermediates have a handful of
                user/assistant lines plus `queue-operation` and `attachment`
                metadata, no `progress` entries."""
                try:
                    has_progress = False
                    user_turns = 0
                    asst_turns = 0
                    with open(path_obj, 'r') as fh:
                        for line in fh:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                obj = json.loads(line)
                            except Exception:
                                continue
                            t = obj.get('type')
                            if t == 'progress':
                                has_progress = True
                            elif t == 'user':
                                user_turns += 1
                            elif t == 'assistant':
                                asst_turns += 1
                    # Real session: any progress entries, OR enough turns
                    if has_progress or (user_turns + asst_turns) >= 10:
                        return False
                    return True
                except Exception:
                    return False

            sessions = []
            if session_dir.exists():
                for f in session_dir.iterdir():
                    if f.suffix != '.jsonl':
                        continue
                    sid = f.stem
                    try:
                        stat = f.stat()
                    except Exception:
                        continue

                    is_current_target = (sid == current_session)
                    is_active = is_current_target and agent_is_busy
                    spoofed_to = parent_to_child.get(sid)
                    parent = child_to_parent.get(sid)

                    # Real session start:
                    #   - spoofed-into session → use the spoof event's created_at
                    #     (its first JSONL line is a replayed identity bootstrap
                    #     with a misleading historical timestamp)
                    #   - all others → first JSONL timestamp, fallback to mtime
                    if sid in child_to_spoof_time:
                        started_at = child_to_spoof_time[sid]
                    else:
                        started_at = _read_first_timestamp(f) or stat.st_mtime

                    # Filter window is "last activity within N days" — a
                    # long-running session that had a turn yesterday should
                    # still appear in the timeline.
                    last_activity = stat.st_mtime
                    if last_activity < cutoff:
                        continue

                    # Drop Continuum spoof intermediates (queue-operation only)
                    if not is_active and _is_ephemeral_artifact(f):
                        continue

                    if is_active:
                        status = 'active'
                    elif spoofed_to:
                        status = 'spoofed_from'
                    else:
                        status = 'closed'

                    # First-line "Who are you?" identity bootstrap = spoofed-into session
                    is_compressed = bool(parent)
                    try:
                        with open(f, 'r') as fh:
                            first = fh.readline()
                            if 'Who are you?' in first:
                                is_compressed = True
                    except Exception:
                        pass

                    sessions.append({
                        'session_id': sid,
                        'started_at': started_at,
                        'ended_at': None if is_active else stat.st_mtime,
                        'message_count': None,  # cheap-skip; UI doesn't need exact counts for block render
                        'size_bytes': stat.st_size,
                        'status': status,
                        'is_active': is_active,
                        'is_current_target': is_current_target,  # resume target, may be idle
                        'is_compressed': is_compressed,
                        'parent_session_id': parent,
                        'spoofed_to': spoofed_to,
                    })

            sessions.sort(key=lambda s: s['started_at'])

            # Clamp overlap: a session "owns" time from its start until either
            # its ended_at OR the next session's started_at, whichever is
            # earlier. The DAW model is non-overlapping regions on a track.
            for i in range(len(sessions) - 1):
                a = sessions[i]
                b = sessions[i + 1]
                if a.get('ended_at') is not None and a['ended_at'] > b['started_at']:
                    a['ended_at'] = b['started_at']
                    a['_clamped_to_next'] = True

            self.send_json({
                "agent_id": agent_id,
                "agent_name": agent.get('name'),
                "days": days,
                "current_session_id": current_session,
                "sessions": sessions,
            })

        elif path.startswith('/api/agents/') and path.endswith('/files'):
            # Get files touched by an agent — extracted from session JSONL
            parts = path.split('/')
            agent_id = parts[3]
            agent = db.get_agent(agent_id)
            if not agent:
                self.send_error_json("Agent not found", 404)
                return

            # Track files with timestamps — keep latest action per file
            file_map = {}  # path -> {tool, action, timestamp}
            try:
                thread = db.get_thread_by_agent(agent_id)
                session_id = thread.get('session_id') if thread else None
                if session_id:
                    pm = get_process_manager()
                    mangled = pm._mangle_cwd(agent.get('cwd', ''))
                    session_dir = Path.home() / ".claude" / "projects" / mangled
                    session_file = None
                    for f in session_dir.iterdir() if session_dir.exists() else []:
                        if f.name.startswith(session_id) and f.suffix == '.jsonl':
                            session_file = f
                            break

                    if session_file and session_file.exists():
                        from datetime import datetime
                        line_idx = 0
                        with open(session_file) as f:
                            for line in f:
                                line_idx += 1
                                try:
                                    entry = json.loads(line.strip())
                                    # Get timestamp from entry
                                    ts = entry.get('timestamp') or entry.get('created_at') or ''
                                    msg = entry.get('message', {})
                                    if not isinstance(msg, dict):
                                        continue
                                    for block in msg.get('content', []):
                                        if not isinstance(block, dict):
                                            continue
                                        if block.get('type') == 'tool_use':
                                            inp = block.get('input', {})
                                            tool = block.get('name', '')
                                            fp = inp.get('file_path', '') or inp.get('path', '')
                                            if not fp:
                                                continue
                                            action = 'write' if tool == 'Write' else 'edit' if tool == 'Edit' else 'read' if tool == 'Read' else 'search' if tool in ('Glob','Grep') else 'other'
                                            # Upgrade action: if file was read before but now written, upgrade to write
                                            existing = file_map.get(fp)
                                            action_rank = {'write': 3, 'edit': 3, 'read': 1, 'search': 0, 'other': 0}
                                            if not existing or action_rank.get(action, 0) >= action_rank.get(existing['action'], 0):
                                                # Get real file modification time
                                                mtime = None
                                                try:
                                                    mtime = os.path.getmtime(fp)
                                                except Exception:
                                                    pass
                                                file_map[fp] = {
                                                    'path': fp,
                                                    'tool': tool,
                                                    'action': action,
                                                    'mtime': mtime,
                                                    'line_idx': line_idx,
                                                }
                                except Exception:
                                    continue
            except Exception as e:
                logger.warning(f"File extraction failed for {agent_id}: {e}")

            # Also check messages for file references as fallback
            if not file_map:
                try:
                    import re
                    messages = db.get_messages(thread['id']) if thread else []
                    for m in messages:
                        if m.get('role') == 'assistant':
                            paths = re.findall(r'`([^`]+\.[a-zA-Z]+)`', m.get('content', ''))
                            for p in paths:
                                if '/' in p and p not in file_map and not p.startswith('http'):
                                    mtime = None
                                    try: mtime = os.path.getmtime(p)
                                    except: pass
                                    file_map[p] = {'path': p, 'tool': 'mentioned', 'action': 'referenced', 'mtime': mtime, 'line_idx': 0}
                except Exception:
                    pass

            # Sort by mtime descending (most recently modified first), fallback to line index
            files = sorted(file_map.values(), key=lambda f: f.get('mtime') or 0, reverse=True)
            self.send_json({"files": files, "agent_id": agent_id, "agent_cwd": agent.get('cwd', '')})

        elif path.startswith('/api/agents/') and path.endswith('/reset-options'):
            # GET /api/agents/{id}/reset-options — available docs for session reset modal
            parts = path.split('/')
            agent_id = parts[3]
            agent = db.get_agent(agent_id)
            if not agent:
                self.send_error_json("Agent not found", 404)
                return

            agent_name = agent.get('name', 'Unknown')
            PROJECT_ROOT = Path(os.environ.get("SUTRA_PROJECT_ROOT", str(Path.home() / "sutra-project")))

            # Get turn count
            thread = db.get_thread_by_agent(agent_id)
            turn_count = 0
            if thread:
                with db.get_connection() as conn:
                    turn_count = conn.execute(
                        "SELECT COUNT(*) FROM messages WHERE thread_id = ? AND role = 'assistant'",
                        (thread['id'],)
                    ).fetchone()[0]

            # Define available docs
            doc_defs = [
                {"key": "telos", "name": "TELOS.md", "path": str(PROJECT_ROOT / "TELOS.md"), "default": True},
                {"key": "context_payload", "name": "CONTEXT-PAYLOAD.md", "path": str(PROJECT_ROOT / "CONTEXT-PAYLOAD.md"), "default": True},
                {"key": "state", "name": "state.md", "path": str(PROJECT_ROOT / "data" / "agents" / agent_name / "state.md"), "default": True},
                {"key": "context", "name": "CONTEXT.md", "path": str(PROJECT_ROOT / "CONTEXT.md"), "default": False},
                {"key": "learned", "name": "LEARNED.md", "path": str(PROJECT_ROOT / "LEARNED.md"), "default": False},
                {"key": "tasks", "name": "TASKS.md", "path": str(PROJECT_ROOT / "TASKS.md"), "default": False},
            ]

            available_docs = []
            for d in doc_defs:
                p = Path(d['path'])
                tokens = 0
                last_modified = None
                if p.exists():
                    content = p.read_text()
                    tokens = len(content) // 4  # approximate token count
                    from datetime import datetime
                    last_modified = datetime.fromtimestamp(p.stat().st_mtime).isoformat()
                available_docs.append({
                    "key": d['key'],
                    "name": d['name'],
                    "path": d['path'],
                    "tokens": tokens,
                    "last_modified": last_modified,
                    "default": d['default'],
                    "exists": p.exists(),
                })

            self.send_json({
                "agent_id": agent_id,
                "agent_name": agent_name,
                "turn_count": turn_count,
                "threshold": 80,
                "available_docs": available_docs,
                "current_session_id": thread.get('session_id') if thread else None,
            })

        elif path == '/api/signals':
            # Return recent tool signals and clean up old ones
            signals = []
            signal_dir = Path(__file__).parent.parent / "data" / "signals"
            if signal_dir.exists():
                now = time.time()
                for f in sorted(signal_dir.iterdir()):
                    if not f.suffix == '.signal':
                        continue
                    try:
                        data = json.loads(f.read_text())
                        age = now - data.get('timestamp', 0)
                        if age < 60:  # only signals from last 60s
                            signals.append(data)
                        elif age > 300:  # clean up signals older than 5 min
                            f.unlink()
                    except Exception:
                        pass
            self.send_json({"signals": signals})

        # Static files
        elif path == '/' or path == '/index.html':
            self.serve_file('index.html', 'text/html')

        elif path == '/mobile.html':
            self.serve_file('mobile.html', 'text/html')

        elif path == '/manifest.json':
            self.serve_file('manifest.json', 'application/manifest+json')

        elif path.endswith('.js'):
            self.serve_file(path[1:], 'application/javascript')

        elif path.endswith('.css'):
            self.serve_file(path[1:], 'text/css')

        elif path.startswith('/avatars/'):
            avatar_path = Path(__file__).parent.parent / "data" / path[1:]
            if avatar_path.exists():
                content_type = 'image/png' if path.endswith('.png') else 'image/jpeg'
                self.serve_file_absolute(avatar_path, content_type)
            else:
                self.send_error(404)

        else:
            self.send_error(404)

    def do_POST(self):
        """Handle POST requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        # Read body
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode() if content_length > 0 else '{}'

        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self.send_error_json("Invalid JSON")
            return

        # API routes
        if path == '/api/agents':
            # Create agent
            required = ['name', 'cwd']
            if not all(k in data for k in required):
                self.send_error_json(f"Missing required fields: {required}")
                return

            # HARD BOUNDARY: all agent cwds must live under personal-os-main
            PROJECT_ROOT = os.environ.get("SUTRA_PROJECT_ROOT", str(Path.home() / "sutra-project"))
            requested_cwd = str(data['cwd']).rstrip('/')
            if not requested_cwd.startswith(PROJECT_ROOT):
                self.send_error_json(
                    f"cwd must be inside {PROJECT_ROOT}. "
                    f"Got: {requested_cwd}. "
                    f"For external projects, create a workspace under Projects/prototypes/ instead.",
                    status=400
                )
                return

            # Enforce cwd scoping — only orchestrator gets root
            validated_cwd = session_manager.validate_agent_cwd(
                name=data['name'],
                cwd=data['cwd'],
                role=data.get('role', 'worker')
            )

            provider = data.get('provider', 'claude')
            if data.get('model'):
                model = data['model']
            elif provider.startswith('ollama:'):
                model = provider.split(':', 1)[1]  # e.g. "ollama:qwen2.5:7b" → "qwen2.5:7b"
            else:
                model = 'sonnet'

            agent = db.create_agent(
                name=data['name'],
                cwd=validated_cwd,
                display_name=data.get('display_name'),
                emoji=data.get('emoji', '🤖'),
                model=model,
                provider=provider,
                system_prompt=data.get('system_prompt'),
                role=data.get('role', 'worker')
            )

            # Initialize git-backed workspace (REQ-2.1)
            try:
                ws_path = workspace.init_workspace(
                    agent_name=data['name'],
                    permission_tier=data.get('permission_tier', 'autonomous'),
                )
                logger.info(f"Workspace ready at {ws_path}")
            except Exception as e:
                logger.warning(f"Workspace init failed for {data['name']}: {e}")

            # Try to recover a previous session for this agent
            try:
                recovered = session_manager.recover_agent_session(data['name'], data['cwd'])
                if recovered and agent.get('thread_id'):
                    session_id = recovered.get('session_id')
                    # Verify the session file actually exists before linking
                    session_file = recovered.get('file_path') or recovered.get('session_file')
                    if session_file and Path(session_file).exists():
                        db.update_thread_session(agent['thread_id'], session_id)
                        session_manager.register_session(
                            session_id=session_id,
                            agent_id=agent['id'],
                            agent_name=agent['name'],
                            cwd=data['cwd'],
                            model=data.get('model', 'sonnet'),
                            session_file=session_file
                        )
                        agent['session_id'] = session_id
                        agent['_recovered_session'] = True
                        logger.info(f"Recovered session {session_id[:8]}... for recreated agent {data['name']}")
                    else:
                        logger.warning(f"Session recovery for {data['name']}: file not found, starting fresh")
            except Exception as e:
                logger.warning(f"Session recovery failed for {data['name']}: {e}")

            # Broadcast agent_created so any connected UI can add the lane immediately
            signal_agent_created(agent['id'], agent['name'])

            self.send_json({"agent": agent}, 201)

        elif path.startswith('/api/threads/') and '/messages' in path:
            # Send message to agent
            parts = path.split('/')
            thread_id = parts[3]

            if 'content' not in data:
                self.send_error_json("Missing 'content' field")
                return

            thread = db.get_thread(thread_id)
            if not thread:
                self.send_error_json("Thread not found", 404)
                return

            agent = db.get_agent(thread['agent_id'])
            if not agent:
                self.send_error_json("Agent not found", 404)
                return

            # Route instruction (REQ-1.1)
            force_model = data.get('force_model')
            budget_info = None
            try:
                with db.get_connection() as conn:
                    import cost_tracker
                    agent_cost = cost_tracker.get_agent_cost(conn, agent['id'], 'daily')
                    budget_info = 5.0 - agent_cost['cost_usd']  # default $5/day budget
            except Exception:
                pass

            agent_provider = agent.get('provider', 'claude')
            _, agent_local_model = parse_provider_model(agent_provider)
            route = route_instruction(
                instruction=data['content'],
                agent_model=agent['model'],
                budget_remaining=budget_info,
                force_model=force_model,
                prefer_local=(agent_provider.startswith('ollama')),
                local_model=agent_local_model or 'qwen2.5-coder',
            )
            routed_model = route.model
            logger.info(f"Routed message to {route.provider}:{route.model} — {route.reason}")

            # Log override event (REQ-1.1.1)
            if force_model:
                db.log_event('routing_override', agent['id'], {
                    'original_route': f"{agent['model']}",
                    'override_model': force_model,
                    'instruction': data['content'][:200],
                })

            # Check rate limits (REQ-1.2)
            if rate_limiter.is_limited(route.provider):
                state = rate_limiter.get_state(route.provider)
                if rate_limiter.should_reroute(state):
                    available = rate_limiter.get_available_providers(['claude', 'ollama'])
                    if not available:
                        self.send_json({
                            "error": "all_providers_throttled",
                            "retry_after": state.retry_after,
                        }, 503)
                        return
                    # Reroute to first available
                    route = RouteDecision(available[0], 'haiku' if available[0] == 'claude' else 'qwen2.5-coder',
                                         f"rerouted from {route.provider} (rate limited)")

            # Add user message with route info
            user_msg = db.add_message(thread_id, 'user', data['content'], route_reason=route.reason)

            # Signal message received for real-time updates (TASK-6)
            signal_message_received(agent['id'], thread_id)

            # Write user turn to JSONL (REQ-1.3)
            try:
                user_turn = create_turn(
                    session_id=thread.get('session_id', 'unknown'),
                    role='user',
                    content=data['content'],
                    provider=route.provider,
                    model=routed_model,
                )
                append_turn(DEFAULT_SESSION_DIR, agent['id'], user_turn)
            except Exception as e:
                logger.error(f"JSONL user turn write failed for agent {agent['id']}: {e}")

            # Update agent status and clear any notification
            db.set_agent_status(agent['id'], 'busy')
            db.clear_notification(agent['id'])

            # Signal agent status change for real-time updates (TASK-6)
            try:
                signal_file = MESSAGE_SIGNAL_DIR / f"status_{agent['id']}_{int(time.time() * 1000)}.signal"
                signal_file.write_text(json.dumps({
                    "agent_id": agent['id'],
                    "status": "busy",
                    "timestamp": time.time()
                }))
            except Exception as e:
                logger.error(f"Failed to signal agent status: {e}")

            # Send to Claude asynchronously
            pm = get_process_manager()
            config = AgentConfig(
                agent_id=agent['id'],
                name=agent['name'],
                cwd=agent['cwd'],
                model=routed_model,
                system_prompt=agent['system_prompt'],
                session_id=thread.get('session_id')
            )

            def on_complete(resp: AgentResponse):
                # Record rate limit success
                rate_limiter.record_success(route.provider)

                # Add assistant message with cost + token tracking
                usage = resp.usage or {}
                ctx = (usage.get('input_tokens', 0) or 0) + \
                      (usage.get('cache_creation_input_tokens', 0) or 0) + \
                      (usage.get('cache_read_input_tokens', 0) or 0)
                db.add_message(
                    thread_id, 'assistant', resp.text,
                    cost_usd=resp.cost_usd,
                    duration_secs=resp.duration_secs,
                    input_tokens=usage.get('input_tokens', 0) or 0,
                    output_tokens=usage.get('output_tokens', 0) or 0,
                    context_tokens=ctx,
                    route_reason=route.reason
                )

                # Signal message received for real-time updates (TASK-6)
                signal_message_received(agent['id'], thread_id)

                # Write to JSONL session file (REQ-1.3)
                try:
                    turn = create_turn(
                        session_id=resp.session_id or thread.get('session_id', 'unknown'),
                        role='assistant',
                        content=resp.text,
                        provider=route.provider,
                        model=routed_model,
                        cost_usd=resp.cost_usd,
                        tokens={"input": usage.get('input_tokens', 0) or 0,
                                "output": usage.get('output_tokens', 0) or 0},
                    )
                    append_turn(DEFAULT_SESSION_DIR, agent['id'], turn)
                except Exception as e:
                    logger.error(f"JSONL write failed for agent {agent['id']}: {e}")

                # Update session ID if provided
                if resp.session_id:
                    db.update_thread_session(thread_id, resp.session_id)
                    # Register in persistent session registry
                    session_manager.register_session(
                        session_id=resp.session_id,
                        agent_id=agent['id'],
                        agent_name=agent['name'],
                        cwd=agent['cwd'],
                        model=agent['model'],
                        cost_usd=resp.cost_usd
                    )

                # Update agent status
                db.set_agent_status(agent['id'], 'online')

                # Signal agent status change for real-time updates (TASK-6)
                try:
                    signal_file = MESSAGE_SIGNAL_DIR / f"status_{agent['id']}_{int(time.time() * 1000)}.signal"
                    signal_file.write_text(json.dumps({
                        "agent_id": agent['id'],
                        "status": "online",
                        "timestamp": time.time()
                    }))
                except Exception as e:
                    logger.error(f"Failed to signal agent status: {e}")

                # Increment unread if not current thread
                db.increment_unread(thread_id)

                # Auto-drain instruction queue (REQ-0.3)
                drain_instruction_queue(agent['id'])

            # Dispatch based on provider (REQ-1.4)
            if route.provider == 'ollama':
                # Ollama: synchronous, then call on_complete manually
                import threading
                def ollama_dispatch():
                    try:
                        from adapters.ollama import OllamaAdapter
                        ollama = OllamaAdapter(default_model=routed_model)
                        turns = ollama.send(
                            message=data['content'],
                            session_id=thread.get('session_id'),
                            model=routed_model,
                            system_prompt=agent.get('system_prompt'),
                            cwd=agent.get('cwd'),
                        )
                        asst_turns = [t for t in turns if t.role == 'assistant']
                        text = asst_turns[0].content if asst_turns else ''
                        tokens = asst_turns[0].tokens if asst_turns else {"input": 0, "output": 0}
                        fake_resp = AgentResponse(
                            text=text,
                            cost_usd=0.0,
                            duration_secs=0.0,
                            session_id=None,
                            usage={"input_tokens": tokens.get("input", 0),
                                   "output_tokens": tokens.get("output", 0)},
                        )
                        on_complete(fake_resp)
                    except Exception as e:
                        logger.error(f"Ollama dispatch error: {e}")
                        db.set_agent_status(agent['id'], 'online')
                        db.log_event('provider_error', agent['id'], {
                            'provider': 'ollama', 'model': routed_model, 'error': str(e)
                        })
                threading.Thread(target=ollama_dispatch, daemon=True).start()
            else:
                pm.send_message_async(config, data['content'], on_complete)

            self.send_json({
                "message": user_msg,
                "status": "processing"
            }, 202)

        elif path == '/api/reports':
            # Add report (from hook)
            required = ['agent_id', 'agent_name', 'type', 'title', 'summary']
            if not all(k in data for k in required):
                self.send_error_json(f"Missing required fields: {required}")
                return

            report = db.add_report(
                agent_id=data['agent_id'],
                agent_name=data['agent_name'],
                report_type=data['type'],
                title=data['title'],
                summary=data['summary'],
                payload=data.get('payload')
            )

            # Auto-commit workspace on report (REQ-2.2)
            if data['type'] in ('complete', 'decision', 'checkpoint'):
                try:
                    sha = workspace.auto_commit(data['agent_name'], data['summary'][:200])
                    if sha:
                        report['auto_commit_sha'] = sha
                except Exception as e:
                    logger.warning(f"Auto-commit failed for {data['agent_name']}: {e}")

            self.send_json({"report": report}, 201)

        elif path.startswith('/api/reports/') and '/acknowledge' in path:
            # Acknowledge report
            parts = path.split('/')
            report_id = int(parts[3])
            success = db.acknowledge_report(report_id)
            self.send_json({"success": success})

        elif path == '/api/reports/acknowledge-all':
            # Acknowledge all reports
            count = db.acknowledge_all_reports()
            self.send_json({"acknowledged": count})

        # NOTE: Legacy destructive `/reset` (DELETE messages, NULL session) removed 2026-04-21.
        # It was shadowing the real `/reset` handler below via `'/reset' in path` match.
        # The real handler (path.endswith('/reset')) does spoof/fresh with doc injection.

        elif path == '/api/heartbeat':
            # Heartbeat update from hook
            required = ['agent_id', 'agent_name']
            if not all(k in data for k in required):
                self.send_error_json(f"Missing required fields: {required}")
                return

            # Update heartbeat
            heartbeat.write_heartbeat(
                agent_id=data['agent_id'],
                agent_name=data['agent_name'],
                status=data.get('status', 'active'),
                current_task=data.get('current_task'),
                progress=data.get('progress'),
                summary=data.get('summary'),
                blockers=data.get('blockers'),
                key_decisions=data.get('key_decisions'),
                initial_prompt=data.get('initial_prompt'),
                last_prompt=data.get('last_prompt'),
                last_response=data.get('last_response')
            )

            # Also append to session log (rate limited)
            if data.get('current_task'):
                heartbeat.append_session_log(
                    agent_id=data['agent_id'],
                    agent_name=data['agent_name'],
                    entry=data.get('current_task')
                )

            self.send_json({"success": True}, 200)

        elif path.startswith('/api/threads/') and '/read' in path:
            # Mark thread as read
            parts = path.split('/')
            thread_id = parts[3]
            db.clear_unread(thread_id)
            self.send_json({"success": True})

        elif path == '/api/open-file':
            # Open a file in the default editor
            file_path = data.get('path', '')
            if not file_path:
                self.send_error_json("Missing 'path' field")
                return
            # Security: only allow files under personal-os-main
            ALLOWED_ROOT = os.environ.get("SUTRA_PROJECT_ROOT", str(Path.home() / "sutra-project"))
            if not os.path.abspath(file_path).startswith(ALLOWED_ROOT):
                self.send_error_json("Path must be inside personal-os-main", 403)
                return
            if not os.path.exists(file_path):
                self.send_error_json(f"File not found: {file_path}", 404)
                return
            try:
                import subprocess as sp
                sp.Popen(['open', file_path])
                self.send_json({"status": "opened", "path": file_path})
            except Exception as e:
                self.send_error_json(f"Failed to open: {e}", 500)

        elif path.startswith('/api/agents/') and path.endswith('/cancel'):
            # Cancel a running dispatch — kill the subprocess and/or reconcile stale busy state
            parts = path.split('/')
            agent_id = parts[3]
            pm = get_process_manager()
            proc = pm.active_processes.get(agent_id)

            def _signal_status_online():
                try:
                    import time as _t
                    sig = MESSAGE_SIGNAL_DIR / f"status_{agent_id}_{int(_t.time() * 1000)}.signal"
                    sig.write_text(json.dumps({
                        "agent_id": agent_id,
                        "status": "online",
                        "timestamp": _t.time()
                    }))
                except Exception as e:
                    logger.error(f"Failed to signal agent status: {e}")

            if proc and proc.poll() is None:
                # Live process — SIGTERM, wait 3s, SIGKILL fallback
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except Exception:
                    proc.kill()
                pm.active_processes.pop(agent_id, None)
                db.set_agent_status(agent_id, 'online')
                _signal_status_online()
                logger.info(f"Cancelled dispatch for agent {agent_id} (terminated pid {proc.pid})")
                self.send_json({"status": "cancelled", "agent_id": agent_id})
            else:
                # No live process. Reconcile stale state either way — the UI thinks it's busy.
                pm.active_processes.pop(agent_id, None)
                lock = pm.locks.get(agent_id)
                lock_held = bool(lock and lock.locked())
                db.set_agent_status(agent_id, 'online')
                _signal_status_online()
                if lock_held:
                    logger.info(f"Cancel {agent_id}: no proc but lock held — reconciled UI, dispatch will self-complete")
                    self.send_json({"status": "reconciled", "agent_id": agent_id, "message": "Agent force-idled. Any in-flight dispatch will finish in the background."})
                else:
                    logger.info(f"Cancel {agent_id}: no proc, no lock — reconciled stale busy state")
                    self.send_json({"status": "reconciled", "agent_id": agent_id, "message": "Agent was already idle — refreshed status."})

        elif path.startswith('/api/agents/') and path.endswith('/reset'):
            # POST /api/agents/{id}/reset — execute session reset with user-chosen options
            parts = path.split('/')
            agent_id = parts[3]
            agent = db.get_agent(agent_id)
            if not agent:
                self.send_error_json("Agent not found", 404)
                return

            agent_name = agent.get('name', 'Unknown')
            mode = data.get('mode', 'spoof')  # "spoof" or "fresh"
            inject_docs = data.get('inject_docs', [])
            steering_prompt = data.get('steering_prompt', '')
            custom_note = data.get('custom_note', '')

            thread = db.get_thread_by_agent(agent_id)
            if not thread:
                self.send_error_json(f"No thread for agent '{agent_name}'", 404)
                return

            PROJECT_ROOT = Path(os.environ.get("SUTRA_PROJECT_ROOT", str(Path.home() / "sutra-project")))

            # Build doc paths map
            doc_paths = {
                "telos": PROJECT_ROOT / "TELOS.md",
                "context_payload": PROJECT_ROOT / "CONTEXT-PAYLOAD.md",
                "state": PROJECT_ROOT / "data" / "agents" / agent_name / "state.md",
                "context": PROJECT_ROOT / "CONTEXT.md",
                "learned": PROJECT_ROOT / "LEARNED.md",
                "tasks": PROJECT_ROOT / "TASKS.md",
            }

            # Read selected docs and store as reset-context.json
            reset_context = {}
            for doc_key in inject_docs:
                doc_path = doc_paths.get(doc_key)
                if doc_path and doc_path.exists():
                    reset_context[doc_key] = {
                        "name": doc_path.name,
                        "path": str(doc_path),
                        "content": doc_path.read_text(),
                    }

            # Save reset context for the agent
            agent_data_dir = PROJECT_ROOT / "data" / "agents" / agent_name
            agent_data_dir.mkdir(parents=True, exist_ok=True)
            reset_context_file = agent_data_dir / "reset-context.json"
            reset_payload = {
                "mode": mode,
                "inject_docs": reset_context,
                "steering_prompt": steering_prompt,
                "custom_note": custom_note,
                "timestamp": time.time(),
            }
            reset_context_file.write_text(json.dumps(reset_payload, indent=2))
            logger.info(f"Reset context written to {reset_context_file}")

            new_session_id = None
            old_session_id = thread.get('session_id')

            # Capture context state + trigger source BEFORE the spoof for event logging
            _spoof_outcome = None        # spoof_success | spoof_failed | spoof_no_session | fresh
            _spoof_error = None
            _context_used_before = 0
            _context_pct_before = 0.0
            try:
                pm = get_process_manager()
                _context_used_before = pm._get_last_usage_tokens(old_session_id, agent.get('cwd', ''))
                _model_max = {
                    'opus': 1000000, 'claude-opus-4-6': 1000000, 'claude-opus-4-7': 1000000,
                    'sonnet': 200000, 'claude-sonnet-4-6': 200000,
                    'haiku': 200000, 'claude-haiku-4-5': 200000,
                }.get(agent.get('model', 'sonnet'), 200000)
                _context_pct_before = round((_context_used_before / _model_max) * 100, 1) if _context_used_before else 0.0
            except Exception:
                pass

            # Detect trigger source: notification still set with reason=context_pressure → auto-triggered
            _trigger = 'manual'
            try:
                _notif_raw = (agent.get('notification') or '')
                if _notif_raw.startswith('reset_pending:'):
                    _notif_data = json.loads(_notif_raw[len('reset_pending:'):])
                    if _notif_data.get('reason') == 'context_pressure':
                        _trigger = 'auto_pressure'
                    else:
                        _trigger = 'auto_turn_count'
            except Exception:
                pass

            # Emit "starting" so the UI overlay appears immediately
            emit_reset_signal(
                agent_id, 'starting',
                detail=f"mode={mode} • {len(reset_context)} doc(s) • trigger={_trigger}",
                extra={'mode': mode, 'inject_docs': list(reset_context.keys())},
            )

            if mode == 'spoof':
                # Spoof the session via Continuum — compress history, preserve knowledge.
                # Stream stdout from spoof_tool.py and emit progress signals so the UI
                # can show what's happening instead of staring at a blocked request.
                try:
                    import subprocess as sp_reset
                    import threading as _threading
                    continuum_path = Path.home() / ".continuum" / ".install_path"
                    if continuum_path.exists():
                        continuum_dir = continuum_path.read_text().strip()
                        spoof_prompt = steering_prompt or (
                            f'Focus on: {agent_name} is an orchestrator/agent that dispatches to other agents '
                            f'via curl http://localhost:8900/api/orchestrate. Preserve dispatch patterns, decisions made, '
                            f'and current work context. Drop debugging dead-ends and hallucinated tool calls.'
                        )
                        if old_session_id:
                            emit_reset_signal(
                                agent_id, 'spoof_starting',
                                detail=f"Compressing session {old_session_id[:8]} via Continuum...",
                                extra={'old_session_id': old_session_id},
                            )

                            proc = sp_reset.Popen(
                                ['python3', f'{continuum_dir}/spoof_tool.py',
                                 '--compress',
                                 '--session', old_session_id,
                                 '--prompt', spoof_prompt],
                                cwd=agent.get('cwd', '/tmp'),
                                stdout=sp_reset.PIPE, stderr=sp_reset.PIPE, text=True,
                            )

                            spoof_started_at = time.time()
                            stop_heartbeat = _threading.Event()

                            def _heartbeat():
                                while not stop_heartbeat.wait(2.0):
                                    elapsed = int(time.time() - spoof_started_at)
                                    emit_reset_signal(
                                        agent_id, 'spoof_running',
                                        detail=f"Compressing... {elapsed}s elapsed",
                                        extra={'elapsed': elapsed},
                                    )

                            hb = _threading.Thread(target=_heartbeat, daemon=True)
                            hb.start()

                            stdout_lines: list = []
                            stderr_text = ''
                            try:
                                if proc.stdout is not None:
                                    for raw_line in proc.stdout:
                                        line = raw_line.rstrip()
                                        if not line:
                                            continue
                                        stdout_lines.append(line)
                                        emit_reset_signal(
                                            agent_id, 'spoof_log',
                                            detail=line,
                                        )
                                proc.wait(timeout=120)
                            except sp_reset.TimeoutExpired:
                                proc.kill()
                                _spoof_outcome = 'spoof_failed'
                                _spoof_error = 'spoof_tool.py timed out after 120s'
                                logger.warning(f"Spoof timed out for {agent_name}")
                            finally:
                                stop_heartbeat.set()
                                if proc.stderr is not None:
                                    try:
                                        stderr_text = proc.stderr.read() or ''
                                    except Exception:
                                        stderr_text = ''

                            if _spoof_outcome is None:
                                if proc.returncode == 0:
                                    new_session_id = stdout_lines[-1].strip() if stdout_lines else None
                                    if not (new_session_id and len(new_session_id) > 10):
                                        new_session_id = None
                                        _spoof_outcome = 'spoof_failed'
                                        _spoof_error = f"invalid session id: {(stdout_lines[-1] if stdout_lines else '')[:100]}"
                                        logger.warning(f"Spoof returned invalid session ID: {_spoof_error}")
                                    else:
                                        _spoof_outcome = 'spoof_success'
                                        logger.info(f"Spoofed session for {agent_name}: {old_session_id[:8]} -> {new_session_id[:8]}")
                                else:
                                    _spoof_outcome = 'spoof_failed'
                                    _spoof_error = (stderr_text or '').strip()[:300] or f"exit code {proc.returncode}"
                                    logger.warning(f"Spoof failed for {agent_name}: {_spoof_error}")
                        else:
                            _spoof_outcome = 'spoof_no_session'
                            _spoof_error = 'no existing session_id on thread — nothing to compress'
                            logger.info(f"Spoof requested for {agent_name} but thread has no session_id")
                    else:
                        _spoof_outcome = 'spoof_failed'
                        _spoof_error = 'Continuum not installed'
                        logger.info("Continuum not installed — falling back to fresh session")
                except Exception as spoof_err:
                    _spoof_outcome = 'spoof_failed'
                    _spoof_error = str(spoof_err)[:300]
                    logger.warning(f"Spoof error for {agent_name}: {spoof_err}")

                # Emit terminal phase for the spoof attempt
                emit_reset_signal(
                    agent_id, _spoof_outcome,
                    detail=(
                        f"new session {new_session_id[:8]}" if (new_session_id and _spoof_outcome == 'spoof_success')
                        else (_spoof_error or '')
                    ),
                    ok=(_spoof_outcome == 'spoof_success'),
                    extra={'new_session_id': new_session_id},
                )

                if new_session_id:
                    db.update_thread_session(thread['id'], new_session_id)
                else:
                    # Fallback to fresh if spoof failed
                    db.update_thread_session(thread['id'], None)
            else:
                # Fresh start — clear session
                _spoof_outcome = 'fresh'
                db.update_thread_session(thread['id'], None)
                emit_reset_signal(agent_id, 'fresh', detail="Fresh session — history cleared", ok=True)

            # Clear the reset_pending notification
            db.clear_notification(agent_id)

            # Rich spoof event — fires on EVERY mode='spoof' attempt (success/failure/no-session)
            if mode == 'spoof':
                db.log_event('spoof', agent_id, {
                    'agent_name': agent_name,
                    'outcome': _spoof_outcome,
                    'trigger': _trigger,
                    'old_session_id': old_session_id,
                    'new_session_id': new_session_id,
                    'context_used_before': _context_used_before,
                    'context_pct_before': _context_pct_before,
                    'steering_prompt': (steering_prompt or '')[:200],
                    'inject_docs': inject_docs,
                    'error': _spoof_error,
                })

            # Keep legacy session_reset event (other code may consume this)
            db.log_event('session_reset', agent_id, {
                'mode': mode,
                'outcome': _spoof_outcome,
                'trigger': _trigger,
                'inject_docs': inject_docs,
                'old_session_id': old_session_id,
                'new_session_id': new_session_id,
                'context_pct_before': _context_pct_before,
                'steering_prompt': steering_prompt[:200] if steering_prompt else None,
                'custom_note': custom_note[:200] if custom_note else None,
            })

            logger.info(f"Session reset complete for {agent_name} (mode={mode}, docs={inject_docs})")

            # Final overall completion signal — UI overlay turns success/error and fades out
            _complete_ok = _spoof_outcome in ('spoof_success', 'fresh')
            if _spoof_outcome == 'spoof_success' and new_session_id:
                _complete_detail = f"Reset complete — new session {new_session_id[:8]}"
            elif _spoof_outcome == 'fresh':
                _complete_detail = "Reset complete — fresh session"
            elif new_session_id is None and mode == 'spoof':
                _complete_detail = f"Spoof failed ({_spoof_outcome}) — fell back to fresh session"
            else:
                _complete_detail = _spoof_error or _spoof_outcome or "Reset finished"
            emit_reset_signal(
                agent_id, 'complete',
                detail=_complete_detail,
                ok=_complete_ok,
                extra={
                    'mode': mode,
                    'outcome': _spoof_outcome,
                    'new_session_id': new_session_id,
                },
            )

            self.send_json({
                "status": "reset",
                "agent_id": agent_id,
                "agent_name": agent_name,
                "mode": mode,
                "session_id": new_session_id,
                "injected_docs": list(reset_context.keys()),
            })

        elif path == '/api/orchestrate':
            # Orchestrator endpoint: send instruction to any agent by name
            required = ['agent', 'instruction']
            if not all(k in data for k in required):
                self.send_error_json(f"Missing required fields: {required}")
                return

            agent_name = data['agent']
            instruction = data['instruction']
            priority = data.get('priority', 'normal')

            # Find agent by name
            agents = db.list_agents()
            agent = next((a for a in agents if a['name'] == agent_name), None)
            if not agent:
                self.send_error_json(f"Agent '{agent_name}' not found", 404)
                return

            # Block self-dispatch (prevents deadlock — agent curling its own orchestrate endpoint)
            requesting_id = data.get('requesting_agent_id')
            if requesting_id and requesting_id == agent['id']:
                self.send_error_json(
                    f"Agent '{agent_name}' cannot dispatch to itself (would deadlock). Use a subagent instead.",
                    400
                )
                return
            # Also block orchestrator dispatching to itself by name
            if agent.get('role') == 'orchestrator' and pm.is_busy(agent['id']):
                self.send_error_json(
                    f"Agent '{agent_name}' is already processing (self-dispatch blocked).",
                    409
                )
                return

            # Check permission tier
            tier = agent.get('permission_tier', 'autonomous')
            if tier == 'restricted':
                self.send_error_json(
                    f"Agent '{agent_name}' is restricted — owner-only",
                    403
                )
                return
            if tier == 'supervised':
                # Store in pending_approvals table (REQ-0.4)
                approval = db.add_pending_approval(
                    agent_id=agent['id'],
                    agent_name=agent_name,
                    instruction=instruction,
                    requesting_agent_id=data.get('requesting_agent_id')
                )
                self.send_json({
                    "status": "pending_approval",
                    "approval_id": approval['id'],
                    "agent": agent_name,
                    "instruction": instruction,
                    "tier": tier,
                    "message": f"Agent '{agent_name}' requires approval. Instruction queued."
                }, 202)
                return

            # Check if agent is busy — queue if so (check both lock and DB status)
            pm = get_process_manager()
            if pm.is_busy(agent['id']) or agent.get('status') == 'busy':
                # Persist to SQLite queue (REQ-0.3)
                queued = db.enqueue_instruction(
                    agent_id=agent['id'],
                    agent_name=agent_name,
                    instruction=instruction,
                    priority=priority
                )
                pending = db.get_agent_queue(agent['id'])
                self.send_json({
                    "status": "queued",
                    "queue_id": queued['id'],
                    "agent": agent_name,
                    "queue_position": len(pending),
                    "message": f"Agent '{agent_name}' is busy. Instruction queued."
                }, 202)
                return

            # Get thread for this agent
            thread = db.get_thread_by_agent(agent['id'])
            if not thread:
                self.send_error_json(f"No thread for agent '{agent_name}'", 404)
                return

            # Auto-reset check: turn-based
            AUTO_RESET_THRESHOLD = 80  # assistant turns
            with db.get_connection() as conn:
                turn_count = conn.execute(
                    "SELECT COUNT(*) FROM messages WHERE thread_id = ? AND role = 'assistant'",
                    (thread['id'],)
                ).fetchone()[0]

            if turn_count >= AUTO_RESET_THRESHOLD:
                logger.info(f"Reset pending for {agent['name']} at turn {turn_count}")

                # Auto-save: extract state from recent messages before resetting
                try:
                    agent_name = agent.get('name', 'Unknown')
                    state_dir = Path(__file__).parent.parent.parent / "data" / "agents" / agent_name
                    state_dir.mkdir(parents=True, exist_ok=True)
                    state_file = state_dir / "state.md"

                    # Get last 20 messages for context
                    with db.get_connection() as conn:
                        recent = conn.execute(
                            "SELECT role, content, created_at FROM messages WHERE thread_id = ? ORDER BY id DESC LIMIT 20",
                            (thread['id'],)
                        ).fetchall()

                    # Extract: last user messages (what was being worked on)
                    user_msgs = [dict(r) for r in recent if dict(r)['role'] == 'user']
                    asst_msgs = [dict(r) for r in recent if dict(r)['role'] == 'assistant']

                    last_focus = user_msgs[0]['content'][:200] if user_msgs else 'Unknown'
                    last_action = asst_msgs[0]['content'][:300] if asst_msgs else 'Unknown'

                    # Get total cost/tokens
                    with db.get_connection() as conn:
                        totals = conn.execute(
                            "SELECT SUM(cost_usd), SUM(input_tokens), SUM(output_tokens) FROM messages WHERE thread_id = ?",
                            (thread['id'],)
                        ).fetchone()

                    from datetime import datetime
                    now = datetime.now().strftime('%Y-%m-%d, %I:%M %p')

                    state_content = f"""# {agent_name} — State

> Last saved: {now} (auto-save before reset)
> Project: {agent.get('cwd', 'unknown')}
> Reset reason: turn count exceeded ({turn_count}/{AUTO_RESET_THRESHOLD})

## Current Focus
{last_focus}

## Last Action
{last_action}

## Session Stats
- Turns: {turn_count}
- Cost: ${totals[0]:.2f if totals[0] else 0}
- Tokens: {totals[1] or 0} in / {totals[2] or 0} out

## Cross-Agent Memos
- Session was auto-reset at {turn_count} turns
- Previous session may have behavioral drift — verify dispatches work correctly
"""
                    state_file.write_text(state_content)
                    logger.info(f"Auto-save written to {state_file}")

                    # Git commit the state file
                    import subprocess as sp
                    personal_os_root = Path(__file__).parent.parent.parent
                    try:
                        sp.run(['git', 'add', str(state_file)], cwd=str(personal_os_root), capture_output=True, timeout=5)
                        sp.run(
                            ['git', 'commit', '-m', f'[{agent_name}] /auto-save — {turn_count} turns, session reset'],
                            cwd=str(personal_os_root), capture_output=True, timeout=10
                        )
                        logger.info(f"Auto-save committed to git for {agent_name}")
                    except Exception as ge:
                        logger.warning(f"Git commit failed for auto-save: {ge}")

                except Exception as e:
                    logger.warning(f"Auto-save failed for {agent.get('name')}: {e}")

                # Set pending flag instead of immediately resetting — let user choose via modal
                reset_info = json.dumps({'turn_count': turn_count, 'threshold': AUTO_RESET_THRESHOLD})
                db.set_notification(agent['id'], f'reset_pending:{reset_info}')

                # Log the pending reset event
                db.log_event('reset_pending', agent['id'], {
                    'turn_count': turn_count,
                    'threshold': AUTO_RESET_THRESHOLD,
                    'reason': 'turn_count_exceeded',
                })

                # Continue dispatch with current session (don't clear yet)

            # Route instruction (REQ-1.1)
            force_model = data.get('force_model')
            budget_info = None
            try:
                with db.get_connection() as conn:
                    import cost_tracker
                    agent_cost = cost_tracker.get_agent_cost(conn, agent['id'], 'daily')
                    budget_info = 5.0 - agent_cost['cost_usd']
            except Exception:
                pass

            orch_route = route_instruction(
                instruction=instruction,
                agent_model=agent['model'],
                budget_remaining=budget_info,
                force_model=force_model,
            )
            routed_model = orch_route.model
            logger.info(f"Orchestrate routed to {orch_route.provider}:{orch_route.model} — {orch_route.reason}")

            if force_model:
                db.log_event('routing_override', agent['id'], {
                    'original_route': agent['model'],
                    'override_model': force_model,
                    'instruction': instruction[:200],
                })

            # Behavioral anchor — keeps critical rules in most recent context
            # Only for orchestrator agents, not workers
            if agent.get('role') == 'orchestrator':
                sutra_port = os.environ.get('SUTRA_PORT', '8900')
                anchor = (
                    f"[DISPATCH CONTEXT] You are Sutra, the orchestrator. "
                    f"To reach agents, use: curl -s -X POST http://localhost:{sutra_port}/api/orchestrate "
                    f"-H 'Content-Type: application/json' -d '{{\"agent\": \"NAME\", \"instruction\": \"...\"}}'. "
                    f"To check what an agent did: curl -s http://localhost:{sutra_port}/api/agents/AGENT_ID/recent. "
                    f"Do NOT use SendMessage or Agent tools — they don't reach running agents."
                )
                user_content = f"{anchor}\n\n[Orchestrator] {instruction}"
            else:
                user_content = f"[Orchestrator] {instruction}"

            # Add user message (from orchestrator)
            db.add_message(thread['id'], 'user', user_content, route_reason=orch_route.reason)
            db.set_agent_status(agent['id'], 'busy')

            # Broadcast dispatch_started so UI can create an active block immediately
            signal_dispatch_started(agent['id'], thread['id'], instruction)
            # Also signal message_received so any listeners pick up the new user message
            signal_message_received(agent['id'], thread['id'])

            # Write user turn to JSONL (REQ-1.3)
            try:
                user_turn = create_turn(
                    session_id=thread.get('session_id', 'unknown'),
                    role='user',
                    content=user_content,
                    provider=orch_route.provider,
                    model=routed_model,
                )
                append_turn(DEFAULT_SESSION_DIR, agent['id'], user_turn)
            except Exception as e:
                logger.error(f"JSONL user turn write failed: {e}")

            # Send synchronously (orchestrator waits for response)
            # For orchestrator agents, use dynamic system prompt if no static one is set
            if agent.get('role') == 'orchestrator' and not agent.get('system_prompt'):
                from heartbeat import get_orchestrator_system_prompt
                resolved_system_prompt = get_orchestrator_system_prompt()
            else:
                resolved_system_prompt = agent['system_prompt']

            config = AgentConfig(
                agent_id=agent['id'],
                name=agent['name'],
                cwd=agent['cwd'],
                model=routed_model,
                system_prompt=resolved_system_prompt,
                session_id=thread.get('session_id'),
                permission_tier=tier
            )

            resp = pm.send_message(config, instruction)
            rate_limiter.record_success(orch_route.provider)

            # Store response with token counts
            usage = resp.usage or {}
            ctx = (usage.get('input_tokens', 0) or 0) + \
                  (usage.get('cache_creation_input_tokens', 0) or 0) + \
                  (usage.get('cache_read_input_tokens', 0) or 0)
            db.add_message(
                thread['id'], 'assistant', resp.text,
                cost_usd=resp.cost_usd,
                duration_secs=resp.duration_secs,
                input_tokens=usage.get('input_tokens', 0) or 0,
                output_tokens=usage.get('output_tokens', 0) or 0,
                context_tokens=ctx,
                route_reason=orch_route.reason
            )

            # Write assistant turn to JSONL (REQ-1.3)
            try:
                asst_turn = create_turn(
                    session_id=resp.session_id or thread.get('session_id', 'unknown'),
                    role='assistant',
                    content=resp.text,
                    provider=orch_route.provider,
                    model=routed_model,
                    cost_usd=resp.cost_usd,
                    tokens={"input": usage.get('input_tokens', 0) or 0,
                            "output": usage.get('output_tokens', 0) or 0},
                )
                append_turn(DEFAULT_SESSION_DIR, agent['id'], asst_turn)
            except Exception as e:
                logger.error(f"JSONL assistant turn write failed: {e}")

            if resp.session_id:
                db.update_thread_session(thread['id'], resp.session_id)
                session_manager.register_session(
                    session_id=resp.session_id,
                    agent_id=agent['id'],
                    agent_name=agent['name'],
                    cwd=agent['cwd'],
                    model=agent['model'],
                    cost_usd=resp.cost_usd
                )
            db.set_agent_status(agent['id'], 'online')

            # Record completion for attention pill (worker finished, ready for review)
            try:
                summary_text = (resp.text or '').strip().split('\n')[0][:300]
                db.add_completion(
                    agent_id=agent['id'],
                    agent_name=agent['name'],
                    thread_id=thread['id'],
                    instruction=instruction,
                    summary=summary_text,
                    cost_usd=resp.cost_usd or 0.0,
                )
                # Broadcast so attention pill updates live
                signal_message_received(agent['id'], thread['id'])
            except Exception as e:
                logger.warning(f"Failed to record completion: {e}")

            # Auto-drain instruction queue (REQ-0.3)
            drain_instruction_queue(agent['id'])

            # Log interaction for neural-net visualization
            orchestrator = next((a for a in agents if a.get('role') == 'orchestrator'), None)
            from_id = orchestrator['id'] if orchestrator else agent['id']
            db.log_interaction(
                from_agent_id=from_id,
                to_agent_id=agent['id'],
                interaction_type='orchestrate',
                instruction_summary=instruction,
                cost_usd=resp.cost_usd
            )

            self.send_json({
                "status": "completed",
                "agent": agent_name,
                "response": resp.text,
                "session_id": resp.session_id,
                "cost_usd": resp.cost_usd,
                "duration_secs": resp.duration_secs,
                "usage": resp.usage
            })

        elif path == '/api/sutra':
            # POST /api/sutra — authenticated conversational endpoint (REQ-5.2)
            if not verify_token(self):
                self.send_error_json("Unauthorized — include Bearer token", 401)
                return

            text = data.get('text', data.get('message', ''))
            if not text:
                self.send_error_json("Missing 'text' field")
                return

            # Find orchestrator agent
            agents = db.list_agents()
            orchestrator = next((a for a in agents if a.get('role') == 'orchestrator'), None)
            if not orchestrator:
                self.send_error_json("No orchestrator agent configured", 404)
                return

            thread = db.get_thread_by_agent(orchestrator['id'])
            if not thread:
                self.send_error_json("No thread for orchestrator", 404)
                return

            # Add user message
            db.add_message(thread['id'], 'user', text)
            db.set_agent_status(orchestrator['id'], 'busy')

            # Route and dispatch
            orch_route = route_instruction(
                instruction=text,
                agent_model=orchestrator['model'],
            )

            pm = get_process_manager()
            config = AgentConfig(
                agent_id=orchestrator['id'],
                name=orchestrator['name'],
                cwd=orchestrator['cwd'],
                model=orch_route.model,
                system_prompt=orchestrator.get('system_prompt'),
                session_id=thread.get('session_id'),
            )

            try:
                resp = pm.send_message(config, text)
                usage = resp.usage or {}
                db.add_message(
                    thread['id'], 'assistant', resp.text,
                    cost_usd=resp.cost_usd,
                    duration_secs=resp.duration_secs,
                    route_reason=orch_route.reason
                )
                if resp.session_id:
                    db.update_thread_session(thread['id'], resp.session_id)
                db.set_agent_status(orchestrator['id'], 'online')

                # Get agents involved (from recent interactions)
                interactions = db.get_interactions(since_hours=1)
                agents_involved = list(set(
                    i.get('to_name', '') for i in interactions
                    if i.get('to_name')
                ))

                from datetime import datetime
                self.send_json({
                    "text": resp.text,
                    "cost_usd": resp.cost_usd,
                    "agents_involved": agents_involved,
                    "timestamp": datetime.now().isoformat(),
                    "model": orch_route.model,
                    "route_reason": orch_route.reason,
                })
            except Exception as e:
                db.set_agent_status(orchestrator['id'], 'online')
                self.send_error_json(f"Sutra error: {e}", 500)

        elif path == '/api/events':
            # POST /api/events — receive hook events (REQ-3.1)
            required = ['agent_id', 'event_type']
            if not all(k in data for k in required):
                self.send_error_json(f"Missing required fields: {required}")
                return
            event = db.log_event(
                event_type=data['event_type'],
                agent_id=data['agent_id'],
                payload=data.get('metadata', data.get('payload'))
            )
            self.send_json({"event": event}, 201)

        elif path.startswith('/api/agents/') and path.endswith('/rollback'):
            # POST /api/agents/{id}/rollback (REQ-2.4)
            agent_id = path.split('/')[3]
            agent = db.get_agent(agent_id)
            if not agent:
                self.send_error_json("Agent not found", 404)
                return
            target_sha = data.get('sha')
            if not target_sha:
                self.send_error_json("Missing 'sha' field")
                return
            result = workspace.rollback(agent['name'], target_sha)
            status = 200 if result['success'] else 409
            self.send_json(result, status)

        elif path.startswith('/api/approvals/') and path.endswith('/approve'):
            # POST /api/approvals/{id}/approve (REQ-0.4)
            approval_id = int(path.split('/')[3])
            approval = db.approve_instruction(approval_id)
            if not approval:
                self.send_error_json("Approval not found", 404)
                return
            # Dispatch the approved instruction
            agent = db.get_agent(approval['agent_id'])
            if agent:
                thread = db.get_thread_by_agent(agent['id'])
                if thread:
                    pm = get_process_manager()
                    tier = agent.get('permission_tier', 'autonomous')
                    if pm.is_busy(agent['id']) or agent.get('status') == 'busy':
                        # Agent busy — enqueue
                        db.enqueue_instruction(
                            agent_id=agent['id'],
                            agent_name=agent['name'],
                            instruction=approval['instruction'],
                        )
                        self.send_json({"status": "approved_queued", "approval": approval})
                    else:
                        # Dispatch immediately
                        db.add_message(thread['id'], 'user', f"[Approved] {approval['instruction']}")
                        db.set_agent_status(agent['id'], 'busy')
                        config = AgentConfig(
                            agent_id=agent['id'],
                            name=agent['name'],
                            cwd=agent['cwd'],
                            model=agent['model'],
                            system_prompt=agent.get('system_prompt'),
                            session_id=thread.get('session_id'),
                            permission_tier=tier
                        )
                        resp = pm.send_message(config, approval['instruction'])
                        usage = resp.usage or {}
                        ctx = (usage.get('input_tokens', 0) or 0) + \
                              (usage.get('cache_creation_input_tokens', 0) or 0) + \
                              (usage.get('cache_read_input_tokens', 0) or 0)
                        db.add_message(
                            thread['id'], 'assistant', resp.text,
                            cost_usd=resp.cost_usd,
                            duration_secs=resp.duration_secs,
                            input_tokens=usage.get('input_tokens', 0) or 0,
                            output_tokens=usage.get('output_tokens', 0) or 0,
                            context_tokens=ctx
                        )
                        if resp.session_id:
                            db.update_thread_session(thread['id'], resp.session_id)
                        db.set_agent_status(agent['id'], 'online')
                        drain_instruction_queue(agent['id'])
                        self.send_json({"status": "approved_completed", "approval": approval, "response": resp.text})
                else:
                    self.send_json({"status": "approved", "approval": approval, "warning": "No thread found"})
            else:
                self.send_json({"status": "approved", "approval": approval, "warning": "Agent not found"})

        elif path.startswith('/api/approvals/') and path.endswith('/reject'):
            # POST /api/approvals/{id}/reject (REQ-0.4)
            approval_id = int(path.split('/')[3])
            reason = data.get('reason', '')
            approval = db.reject_instruction(approval_id, reason)
            if not approval:
                self.send_error_json("Approval not found", 404)
                return
            self.send_json({"status": "rejected", "approval": approval})

        elif path.startswith('/api/completions/') and path.endswith('/acknowledge'):
            completion_id = int(path.split('/')[3])
            ok = db.acknowledge_completion(completion_id)
            self.send_json({"success": ok})

        elif path == '/api/completions/acknowledge-all':
            count = db.acknowledge_all_completions()
            self.send_json({"success": True, "acknowledged": count})

        elif path == '/api/improve-prompt':
            # Run a prompt through Haiku to improve it before dispatch.
            # Accepts: {prompt: str, target?: str} → returns {improved: str}
            if 'prompt' not in data:
                self.send_error_json("Missing 'prompt' field")
                return

            original = data['prompt'].strip()
            if not original:
                self.send_error_json("Empty prompt")
                return

            target = data.get('target', 'an AI agent')

            system_prompt = (
                "You are a prompt rewriter. Your ONLY job is to rewrite the text inside <prompt_to_rewrite> tags. "
                "You NEVER answer, respond to, or engage with the content. Treat it as raw text to refactor.\n\n"
                "RULES:\n"
                "- NEVER answer the prompt — if it's a question, rewrite it as a clearer instruction for an agent, do not provide an answer\n"
                "- NEVER add analysis, suggestions, or opinions about the content\n"
                "- Keep the user's voice and intent\n"
                "- Tighten wording, resolve ambiguity, name the concrete deliverable\n"
                "- Do NOT add pleasantries (\"please\", \"thank you\"), filler, or context the user didn't include\n"
                "- Do NOT add XML tags, markdown fencing, quotes, or prefaces in your output\n\n"
                f"The rewritten prompt will be dispatched to {target}.\n\n"
                "EXAMPLES:\n"
                "Input: <prompt_to_rewrite>whats going on with the marketing project</prompt_to_rewrite>\n"
                "Output: Summarize Marketing project status: active campaigns, recent metrics, open blockers.\n\n"
                "Input: <prompt_to_rewrite>help me think about this</prompt_to_rewrite>\n"
                "Output: Help me think through [the current topic in context]. Flag missing info if the topic is unclear.\n\n"
                "Input: <prompt_to_rewrite>why did it break</prompt_to_rewrite>\n"
                "Output: Diagnose why it broke. Read recent logs and session history, identify root cause, propose a fix.\n\n"
                "Output ONLY the rewritten prompt text. Nothing else."
            )

            user_message = f"<prompt_to_rewrite>\n{original}\n</prompt_to_rewrite>"

            try:
                import subprocess as sp
                result = sp.run(
                    ['claude', '--print',
                     '--model', 'haiku',
                     '--append-system-prompt', system_prompt,
                     '--', user_message],
                    capture_output=True, text=True, timeout=30
                )
                if result.returncode != 0:
                    logger.warning(f"improve-prompt failed: {result.stderr[:200]}")
                    self.send_error_json(f"Haiku error: {result.stderr[:200] or 'non-zero exit'}", 500)
                    return

                improved = result.stdout.strip()
                # Strip surrounding quotes if Haiku added them despite instructions
                if (improved.startswith('"') and improved.endswith('"')) or (improved.startswith("'") and improved.endswith("'")):
                    improved = improved[1:-1].strip()

                if not improved:
                    self.send_error_json("Haiku returned empty output", 500)
                    return

                self.send_json({
                    "original": original,
                    "improved": improved,
                    "target": target,
                })
            except sp.TimeoutExpired:
                self.send_error_json("Haiku timeout after 30s", 500)
            except Exception as e:
                logger.warning(f"improve-prompt exception: {e}")
                self.send_error_json(f"Improve failed: {str(e)[:150]}", 500)

        elif path == '/api/canvas':
            # Update canvas HTML
            if 'html' not in data:
                self.send_error_json("Missing 'html' field")
                return

            canvas_path = Path(__file__).parent.parent / "data" / "canvas.html"
            try:
                with open(canvas_path, 'w') as f:
                    f.write(data['html'])

                # Notify WebSocket clients
                self._notify_canvas_update()

                self.send_json({"success": True})
            except Exception as e:
                self.send_error_json(str(e), 500)

        elif path == '/api/slack-agent/config':
            # Configure the Slack agent integration
            try:
                from slack_agent import SlackAgentConfig
            except ImportError:
                self.send_error_json("Slack agent not available", 501)
                return
            SlackAgentConfig  # noqa — used below

            config = SlackAgentConfig.load()

            if 'agent_id' in data:
                config.agent_id = data['agent_id']
            if 'channel_id' in data:
                config.channel_id = data['channel_id']
            if 'thread_ts' in data:
                config.thread_ts = data['thread_ts']

            config.save()

            self.send_json({
                "success": True,
                "config": {
                    "agent_id": config.agent_id,
                    "channel_id": config.channel_id,
                    "thread_ts": config.thread_ts,
                    "state": config.state,
                    "last_processed_ts": config.last_processed_ts
                }
            })

        else:
            self.send_error_json("Not found", 404)

    def do_PUT(self):
        """Handle PUT requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode() if content_length > 0 else '{}'

        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self.send_error_json("Invalid JSON")
            return

        if path == '/api/settings':
            # Update settings
            settings_path = Path(__file__).parent.parent / "data" / "settings.json"
            try:
                # Read existing settings
                existing = {}
                if settings_path.exists():
                    with open(settings_path) as f:
                        existing = json.load(f)

                # Merge with new data
                existing.update(data)

                # Write back
                with open(settings_path, 'w') as f:
                    json.dump(existing, f, indent=2)

                self.send_json(existing)
            except Exception as e:
                self.send_error_json(str(e), 500)

        elif path.startswith('/api/agents/'):
            agent_id = path.split('/')[3]

            # Check if this is a promotion to orchestrator
            old_agent = db.get_agent(agent_id)
            old_role = old_agent.get('role') if old_agent else None
            new_role = data.get('role')

            agent = db.update_agent(agent_id, **data)
            if agent:
                # If promoted to orchestrator, inject system prompt
                if new_role == 'orchestrator' and old_role != 'orchestrator':
                    self._inject_orchestrator_prompt(agent_id)

                self.send_json({"agent": agent})
            else:
                self.send_error_json("Agent not found", 404)
        else:
            self.send_error_json("Not found", 404)

    def do_DELETE(self):
        """Handle DELETE requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith('/api/agents/'):
            agent_id = path.split('/')[3]
            success = db.delete_agent(agent_id)
            if success:
                signal_agent_deleted(agent_id)
                self.send_json({"success": True})
            else:
                self.send_error_json("Agent not found", 404)
        else:
            self.send_error_json("Not found", 404)

    def _notify_canvas_update(self):
        """Notify WebSocket clients that canvas was updated."""
        # Write signal file for ws_server to pick up
        signal_path = Path(__file__).parent.parent / "data" / "canvas.signal"
        signal_path.touch()

    def _inject_orchestrator_prompt(self, agent_id: str):
        """Orchestrator prompt injection — no-op in Sutra (no PTY)."""
        logger.info(f"Orchestrator prompt injection skipped for {agent_id} (no PTY in Sutra)")

    def _build_debug_snapshot(self) -> dict:
        """Build a debug snapshot cross-referencing DB state against process reality."""
        now = time.time()
        uptime_secs = now - _server_start_time

        # DB agents
        db_agents = db.list_agents()
        pm = get_process_manager()

        # Heartbeats
        heartbeats = heartbeat.get_heartbeats()

        agent_snapshots = []
        hung_agents = []
        discrepancies = []

        for a in db_agents:
            aid = a['id']
            name = a.get('name', aid)
            db_status = a.get('status', 'offline')
            process_busy = pm.is_busy(aid)

            # Heartbeat info
            hb = heartbeats.get(aid)
            last_hb_str = hb.get('last_heartbeat') if hb else None
            hb_age = None
            if last_hb_str:
                try:
                    from datetime import datetime
                    hb_time = datetime.fromisoformat(last_hb_str)
                    hb_age = (datetime.now() - hb_time).total_seconds()
                except Exception:
                    hb_age = None

            # Detect discrepancies
            agent_discrep = []
            if db_status == 'busy' and not process_busy:
                agent_discrep.append(f"DB says busy but process lock is free")
            if db_status == 'online' and process_busy:
                agent_discrep.append(f"DB says online but process lock is held")

            # Detect hung agents: busy but no heartbeat in 60s
            is_hung = False
            if process_busy and hb_age is not None and hb_age > 60:
                is_hung = True
                hung_agents.append({
                    'id': aid,
                    'name': name,
                    'heartbeat_age_secs': round(hb_age, 1),
                })

            if agent_discrep:
                discrepancies.extend([f"{name}: {d}" for d in agent_discrep])

            # Token/cost totals from messages table
            thread_id = a.get('thread_id') or a.get('id')
            tokens_cost = {'input_tokens': 0, 'output_tokens': 0, 'cost_usd': 0.0}
            try:
                with db.get_connection() as conn:
                    row = conn.execute(
                        "SELECT COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0), COALESCE(SUM(cost_usd),0) FROM messages WHERE thread_id = ?",
                        (thread_id,)
                    ).fetchone()
                    if row:
                        tokens_cost = {'input_tokens': row[0], 'output_tokens': row[1], 'cost_usd': round(row[2], 4)}
            except Exception as e:
                logger.warning(f"Debug token query failed for {name}: {e}")

            agent_snapshots.append({
                'id': aid,
                'name': name,
                'db_status': db_status,
                'process_busy': process_busy,
                'has_heartbeat': hb is not None,
                'heartbeat_age_secs': round(hb_age, 1) if hb_age is not None else None,
                'is_hung': is_hung,
                'discrepancies': agent_discrep,
                'input_tokens': tokens_cost['input_tokens'],
                'output_tokens': tokens_cost['output_tokens'],
                'cost_usd': tokens_cost['cost_usd'],
            })

        # Session files on disk
        session_files = []
        try:
            for f in sorted(DEFAULT_SESSION_DIR.iterdir()):
                if f.suffix == '.jsonl':
                    session_files.append({
                        'name': f.name,
                        'size_bytes': f.stat().st_size,
                    })
        except Exception:
            pass

        # System info (psutil if available)
        system = {}
        if psutil:
            try:
                proc = psutil.Process()
                system['cpu_percent'] = proc.cpu_percent(interval=0.1)
                system['memory_mb'] = round(proc.memory_info().rss / (1024 * 1024), 1)
            except Exception:
                pass

        # Detect ALL running Claude Code processes on this machine
        running_claude_sessions = []
        try:
            import subprocess as sp
            ps_result = sp.run(
                ['ps', '-eo', 'pid,args'],
                capture_output=True, text=True, timeout=5
            )
            for line in ps_result.stdout.strip().split('\n'):
                line = line.strip()
                if not line or 'PID' in line:
                    continue
                # Match claude processes (not our own grep/ps)
                if 'claude' in line.lower() and 'ps -eo' not in line:
                    parts = line.split(None, 1)
                    if len(parts) < 2:
                        continue
                    pid = parts[0]
                    cmd = parts[1]
                    # Only match actual Claude Code CLI — skip Desktop app + noise
                    if any(skip in cmd for skip in [
                        'Claude.app', 'Claude Helper', 'ShipIt', 'crashpad',
                        'chrome-native-host', 'tail -f', 'snapshot-zsh',
                        'grep claude', 'python', 'bridge.py', 'ws_server.py'
                    ]):
                        continue
                    # Must be the claude CLI binary, not an app bundle
                    cmd_base = cmd.strip().split()[0] if cmd.strip() else ''
                    if not cmd_base.endswith('claude'):
                        continue
                    # Try to get cwd via lsof
                    cwd = None
                    try:
                        lsof_result = sp.run(
                            ['lsof', '-p', pid, '-Fn'],
                            capture_output=True, text=True, timeout=3
                        )
                        for lsof_line in lsof_result.stdout.split('\n'):
                            if lsof_line.startswith('n/') and ('Downloads' in lsof_line or 'Users' in lsof_line):
                                candidate = lsof_line[1:]  # strip 'n' prefix
                                if os.path.isdir(candidate):
                                    cwd = candidate
                                    break
                    except Exception:
                        pass

                    # Check if this PID is managed by us
                    managed = any(
                        a.get('id') in cmd or (a.get('name') and a.get('name') in cmd)
                        for a in db_agents
                    )

                    running_claude_sessions.append({
                        'pid': int(pid),
                        'cmd': cmd[:120],
                        'cwd': cwd,
                        'managed': managed,
                    })
        except Exception as e:
            logger.warning(f"Session detection failed: {e}")

        return {
            'uptime_secs': round(uptime_secs, 1),
            'uptime_human': f"{int(uptime_secs // 3600)}h {int((uptime_secs % 3600) // 60)}m {int(uptime_secs % 60)}s",
            'db_agent_count': len(db_agents),
            'session_file_count': len(session_files),
            'agents': agent_snapshots,
            'hung_agents': hung_agents,
            'discrepancies': discrepancies,
            'session_files': session_files,
            'system': system,
            'running_claude_sessions': running_claude_sessions,
            'rate_limit': pm.last_rate_limit,
        }

    def serve_file(self, filename: str, content_type: str):
        """Serve a static file from the web directory."""
        filepath = WEB_DIR / filename
        self.serve_file_absolute(filepath, content_type)

    def serve_file_absolute(self, filepath: Path, content_type: str):
        """Serve a file from an absolute path."""
        if filepath.exists():
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            with open(filepath, 'rb') as f:
                self.wfile.write(f.read())
        else:
            self.send_error(404)


def run_server():
    """Start the HTTP server."""
    # Initialize database
    db.init_db()
    logger.info(f"Database initialized at {db.DB_PATH}")

    # Reset stale statuses from previous session
    with db.get_connection() as conn:
        conn.execute("UPDATE agents SET status = 'offline', notification = NULL")
    logger.info("Reset agent statuses on startup")

    # Reconcile sessions with disk
    summary = session_manager.reconcile_on_startup()
    logger.info(f"Session reconciliation complete: {summary['sessions_recovered']} recovered, "
                f"{summary['sessions_verified']} verified")

    # Start server (threaded so recursive API calls don't deadlock —
    # Sutra can curl her own API from inside a dispatch without blocking)
    server = ThreadingHTTPServer(('0.0.0.0', PORT), AgentChatHandler)
    server.daemon_threads = True
    logger.info(f"Agent Chat server running at http://0.0.0.0:{PORT} (threaded)")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        server.shutdown()


if __name__ == '__main__':
    run_server()
