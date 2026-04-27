"""
Process Manager for Claude CLI subprocess management.
Handles spawning, communication, and lifecycle of Claude agents.
"""

import subprocess
import sqlite3
import threading
import queue
import json
import os
import time
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass, field
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# REQ-6.2: auto-spoof thresholds
AUTO_SPOOF_THRESHOLD = 0.70  # 70% context usage
_MODEL_MAX_CONTEXT = {
    'opus': 1000000, 'claude-opus-4-6': 1000000, 'claude-opus-4-7': 1000000,
    'sonnet': 200000, 'claude-sonnet-4-6': 200000,
    'haiku': 200000, 'claude-haiku-4-5': 200000, 'claude-haiku-4-5-20251001': 200000,
}


@dataclass
class AgentConfig:
    """Configuration for a Claude agent."""
    agent_id: str
    name: str
    cwd: str
    model: str = "sonnet"
    system_prompt: Optional[str] = None
    session_id: Optional[str] = None
    permission_tier: str = "autonomous"  # autonomous | supervised | restricted
    extra_tools: Optional[list] = None  # additional tool names to allow (e.g. MCP write tools)


@dataclass
class AgentResponse:
    """Structured response from a Claude agent."""
    text: str
    session_id: Optional[str] = None
    cost_usd: float = 0.0
    duration_secs: float = 0.0
    usage: Dict[str, Any] = field(default_factory=dict)
    is_error: bool = False


class ProcessManager:
    """Manages Claude CLI subprocesses for agents."""

    def __init__(self):
        self.active_processes: Dict[str, subprocess.Popen] = {}
        self.message_queues: Dict[str, queue.Queue] = {}
        self.locks: Dict[str, threading.Lock] = {}
        self.last_rate_limit: Optional[dict] = None  # last rate_limit_event from any agent

    def _get_lock(self, agent_id: str) -> threading.Lock:
        """Get or create lock for an agent."""
        if agent_id not in self.locks:
            self.locks[agent_id] = threading.Lock()
        return self.locks[agent_id]

    def _signal_tool_event(self, agent_id: str, tool_name: str, status: str, detail: str = ""):
        """Signal a tool use event for real-time UI updates."""
        try:
            signal_dir = Path(__file__).parent.parent / "data" / "signals"
            signal_dir.mkdir(parents=True, exist_ok=True)
            signal_file = signal_dir / f"tool_{agent_id}_{int(time.time() * 1000)}.signal"
            signal_file.write_text(json.dumps({
                "agent_id": agent_id,
                "tool": tool_name,
                "status": status,
                "detail": detail,
                "timestamp": time.time()
            }))
        except Exception as e:
            logger.debug(f"Tool signal failed: {e}")

    def _get_last_usage_tokens(self, session_id: str, cwd: str) -> int:
        """Read the last usage entry from session JSONL. Returns total input tokens
        (input + cache_create + cache_read) from the most recent usage record."""
        if not session_id or not cwd:
            return 0
        try:
            mangled = self._mangle_cwd(cwd)
            session_file = Path.home() / ".claude" / "projects" / mangled / f"{session_id}.jsonl"
            if not session_file.exists():
                return 0
            last_usage = 0
            with open(session_file) as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        msg = entry.get('message', {})
                        if isinstance(msg, dict):
                            usage = msg.get('usage', {}) or {}
                            total = (
                                (usage.get('input_tokens') or 0)
                                + (usage.get('cache_creation_input_tokens') or 0)
                                + (usage.get('cache_read_input_tokens') or 0)
                            )
                            if total > 0:
                                last_usage = total
                    except Exception:
                        continue
            return last_usage
        except Exception as e:
            logger.debug(f"Failed to read usage for {session_id}: {e}")
            return 0

    def _set_reset_notification(self, agent_id: str, payload: dict) -> None:
        """Set a 'reset_pending:{json}' notification on the agent so the UI pops its modal.

        Direct sqlite (avoids db.py circular import).
        """
        try:
            db_path = Path(__file__).parent.parent / "data" / "agent-chat.db"
            conn = sqlite3.connect(str(db_path))
            try:
                notif = f"reset_pending:{json.dumps(payload)}"
                conn.execute(
                    "UPDATE agents SET notification = ? WHERE id = ?",
                    (notif, agent_id)
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"Failed to set reset notification for {agent_id}: {e}")

    def _has_pending_reset(self, agent_id: str) -> bool:
        """Check if agent already has a reset_pending notification (avoid re-flagging on every dispatch)."""
        try:
            db_path = Path(__file__).parent.parent / "data" / "agent-chat.db"
            conn = sqlite3.connect(str(db_path))
            try:
                row = conn.execute(
                    "SELECT notification FROM agents WHERE id = ?",
                    (agent_id,)
                ).fetchone()
                if row and row[0] and str(row[0]).startswith('reset_pending:'):
                    return True
            finally:
                conn.close()
        except Exception:
            pass
        return False

    def _maybe_auto_spoof(self, config: 'AgentConfig') -> None:
        """REQ-6.2 (human-in-loop variant): If agent's context is past 70%,
        flag reset_pending on the agent so the UI's reset modal pops up.

        Does NOT auto-execute the spoof — user picks spoof/fresh/etc. from the modal.
        The existing POST /api/agents/{id}/reset handler does the actual work.

        Only flags once per cycle — if already flagged, returns silently (avoids spam).
        """
        if not config.session_id:
            return

        max_ctx = _MODEL_MAX_CONTEXT.get(config.model, 200000)
        used = self._get_last_usage_tokens(config.session_id, config.cwd)
        if used <= 0:
            return
        pct = used / max_ctx

        if pct < AUTO_SPOOF_THRESHOLD:
            return

        # If already flagged, don't re-flag (UI still showing modal)
        if self._has_pending_reset(config.agent_id):
            logger.debug(f"[context-pressure] {config.name} at {pct:.1%}, reset already pending")
            return

        logger.info(f"[context-pressure] {config.name} at {pct:.1%} ({used:,}/{max_ctx:,}) — flagging reset_pending for user review")

        # Payload matches existing reset_pending contract (turn_count/threshold) + adds token fields
        payload = {
            'reason': 'context_pressure',
            'context_used': used,
            'context_max': max_ctx,
            'context_pct': round(pct * 100, 1),
            'threshold_pct': int(AUTO_SPOOF_THRESHOLD * 100),
            # Backward-compat fields so the existing modal renders without changes
            'turn_count': used,
            'threshold': int(max_ctx * AUTO_SPOOF_THRESHOLD),
        }
        self._set_reset_notification(config.agent_id, payload)

        # Signal UI (compaction warning pulse on the lane while modal loads)
        self._signal_tool_event(config.agent_id, "CompactionWarning", "pending",
                                detail=f"Context at {int(pct*100)}% — reset modal recommended")

    def send_message(
        self,
        config: AgentConfig,
        message: str,
        on_complete: Optional[Callable[[AgentResponse], None]] = None
    ) -> AgentResponse:
        """
        Send a message to a Claude agent and get a structured response.

        Args:
            config: Agent configuration
            message: Message to send
            on_complete: Callback(AgentResponse) when done

        Returns:
            AgentResponse with text, session_id, cost, usage
        """
        lock = self._get_lock(config.agent_id)

        with lock:
            # REQ-6.2: auto-spoof if session is past 70% context
            self._maybe_auto_spoof(config)

            start_time = time.time()
            try:
                # Build command with streaming NDJSON output
                cmd = ["claude", "--print", "--output-format", "stream-json", "--verbose"]

                # Add model
                if config.model:
                    cmd.extend(["--model", config.model])

                # Permission mode based on tier:
                # - autonomous: full tool access (can run skills, write files, execute commands)
                # - supervised: default permissions (will fail silently on blocked tools)
                # - restricted: blocked at API level, never reaches here
                if config.permission_tier == 'autonomous':
                    # Prototypes get full permissions — sandbox is the cwd boundary
                    PROTO_PREFIX = "$SUTRA_PROJECT_ROOT/Projects/prototypes/"
                    if config.cwd.startswith(PROTO_PREFIX):
                        cmd.append("--dangerously-skip-permissions")
                    else:
                        # Projects/root get explicit allowlist
                        allowed = [
                            "Read", "Write", "Edit", "Glob", "Grep", "Bash",
                            "WebFetch", "WebSearch", "Agent", "Skill",
                            # Slack read-only
                            "mcp__slack__slack_get_channel_history",
                            "mcp__slack__slack_list_channels",
                            "mcp__slack__slack_get_users",
                            "mcp__slack__slack_get_user_profile",
                            "mcp__slack__slack_get_thread_replies",
                        ]
                        # Agent-specific extra tools from config
                        if config.extra_tools:
                            allowed.extend(config.extra_tools)
                        cmd.extend(["--allowedTools", ",".join(allowed)])

                # Add system prompt
                if config.system_prompt:
                    cmd.extend(["--append-system-prompt", config.system_prompt])

                # Resume session if available
                if config.session_id:
                    cmd.extend(["--resume", config.session_id])

                # -- separates flags from the message argument.
                # Required because --allowedTools is variadic and eats positional args.
                cmd.extend(["--", message])

                logger.info(f"Running command for agent {config.agent_id}: {' '.join(cmd[:6])}...")

                # Run process with streaming output
                proc = subprocess.Popen(
                    cmd,
                    cwd=config.cwd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env={
                        **os.environ,
                        "CLAUDE_CODE_ENTRYPOINT": "agent-chat",
                        "CLAUDE_AGENT_ID": config.agent_id,
                        "CLAUDE_AGENT_NAME": config.name,
                    }
                )

                # Track this process for the debug window
                self.active_processes[config.agent_id] = proc

                # Parse streaming NDJSON line by line
                text_parts = []
                session_id = None
                cost_usd = 0.0
                usage = {}
                rate_limit_info = None

                try:
                    for line in proc.stdout:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        event_type = event.get("type", "")

                        # System events — init has session_id and tools
                        if event_type == "system":
                            sid = event.get("session_id")
                            if sid:
                                session_id = sid

                        # Assistant message — content blocks: text, tool_use, tool_result
                        elif event_type == "assistant":
                            msg = event.get("message", {})
                            sid = event.get("session_id")
                            if sid:
                                session_id = sid
                            for block in msg.get("content", []):
                                block_type = block.get("type", "")
                                if block_type == "text":
                                    text_parts.append(block.get("text", ""))
                                elif block_type == "tool_use":
                                    tool_name = block.get("name", "unknown")
                                    tool_input = block.get("input", {})
                                    # Extract human-readable detail from tool input
                                    detail = ""
                                    if tool_name == "Bash":
                                        detail = tool_input.get("command", "")[:200]
                                    elif tool_name in ("Read", "Write", "Edit", "Glob"):
                                        detail = tool_input.get("file_path", "") or tool_input.get("pattern", "")
                                    elif tool_name == "Grep":
                                        detail = tool_input.get("pattern", "")[:100]
                                    elif tool_name == "WebFetch":
                                        detail = tool_input.get("url", "")[:150]
                                    elif tool_name == "Agent":
                                        detail = tool_input.get("prompt", "")[:200]
                                    logger.info(f"[stream] {config.name} → {tool_name}: {detail[:80]}")
                                    # Agent tool gets a special signal type for sub-agent visualization
                                    if tool_name == "Agent":
                                        self._signal_tool_event(config.agent_id, "Agent", "subagent_start",
                                            detail=tool_input.get("prompt", "")[:200])
                                    else:
                                        self._signal_tool_event(config.agent_id, tool_name, "started", detail=detail)
                                elif block_type == "tool_result":
                                    # Capture output snippet for the UI
                                    result_content = block.get("content", "")
                                    if isinstance(result_content, list):
                                        result_content = " ".join(c.get("text", "") for c in result_content if isinstance(c, dict))
                                    if result_content:
                                        self._signal_tool_event(config.agent_id, "result", "completed", detail=str(result_content)[:500])
                                    # Check if this is a sub-agent result (tool_use_id links back to an Agent call)
                                    # Signal sub-agent end so the UI can close the span
                                    tool_use_id = block.get("tool_use_id", "")
                                    if tool_use_id:
                                        self._signal_tool_event(config.agent_id, "Agent", "subagent_end",
                                            detail=str(result_content)[:300])
                            msg_usage = msg.get("usage", {})
                            if msg_usage:
                                usage.update(msg_usage)

                        # Rate limit event — actual plan info
                        elif event_type == "rate_limit_event":
                            rate_limit_info = event.get("rate_limit_info", {})
                            self.last_rate_limit = rate_limit_info
                            logger.info(f"[stream] rate_limit: type={rate_limit_info.get('rateLimitType')} resets={rate_limit_info.get('resetsAt')}")

                        # Result — final text + cost + usage
                        elif event_type == "result":
                            result_text = event.get("result", "")
                            if result_text:
                                text_parts = [result_text]  # use clean final text
                            session_id = event.get("session_id") or session_id
                            cost_usd = event.get("total_cost_usd", 0.0) or 0.0
                            result_usage = event.get("usage", {})
                            if result_usage:
                                usage = result_usage
                            logger.info(f"[stream] {config.name} complete: ${cost_usd:.4f}, {usage.get('output_tokens', 0)} out tokens")

                    proc.wait(timeout=30)

                finally:
                    self.active_processes.pop(config.agent_id, None)

                duration = time.time() - start_time
                full_text = "".join(text_parts).strip()

                # If stream gave no text, fall back to session file
                if not full_text and session_id:
                    full_text = self._read_session_response(session_id, config.cwd) or ""

                if proc.returncode != 0 and not full_text:
                    stderr = proc.stderr.read() if proc.stderr else ""
                    logger.error(f"Claude CLI error (rc={proc.returncode}): {stderr}")
                    response = AgentResponse(
                        text=f"Error: {stderr}" if stderr else "Error: Process failed",
                        duration_secs=duration,
                        is_error=True
                    )
                else:
                    response = AgentResponse(
                        text=full_text,
                        session_id=session_id,
                        cost_usd=cost_usd,
                        duration_secs=duration,
                        usage=usage,
                        is_error=False
                    )

                if on_complete:
                    on_complete(response)

                return response

            except subprocess.TimeoutExpired:
                # Kill the process if it's still running
                if 'proc' in locals():
                    proc.kill()
                    self.active_processes.pop(config.agent_id, None)
                duration = time.time() - start_time
                logger.error(f"Timeout for agent {config.agent_id}")
                response = AgentResponse(
                    text="Error: Request timed out after 10 minutes",
                    duration_secs=duration,
                    is_error=True
                )
                if on_complete:
                    on_complete(response)
                return response

            except Exception as e:
                duration = time.time() - start_time
                logger.error(f"Exception for agent {config.agent_id}: {e}")
                response = AgentResponse(
                    text=f"Error: {str(e)}",
                    duration_secs=duration,
                    is_error=True
                )
                if on_complete:
                    on_complete(response)
                return response

    def _parse_json_response(self, stdout: str, duration: float, cwd: str = "") -> AgentResponse:
        """Parse structured JSON response from claude --output-format json.

        Known issue: claude --print --output-format json returns empty "result"
        field when invoked via subprocess (TTY detection bug in the CLI).
        The session JSONL file always has the full response text, so we fall
        back to reading it when result is empty.
        """
        try:
            data = json.loads(stdout)
            text = data.get("result", "") or ""
            session_id = data.get("session_id")

            # CLI TTY bug: result is empty in subprocess contexts.
            # Recover text from the session JSONL file.
            if not text and session_id:
                text = self._read_session_response(session_id, cwd) or ""

            if not text:
                logger.warning(f"Empty result even after session file fallback (session={session_id})")

            return AgentResponse(
                text=text,
                session_id=session_id,
                cost_usd=data.get("total_cost_usd", 0.0) or 0.0,
                duration_secs=duration,
                usage=data.get("usage", {}),
                is_error=False
            )
        except json.JSONDecodeError:
            # Fallback: treat raw stdout as text (older CLI versions)
            logger.warning("Failed to parse JSON response, falling back to raw text")
            return AgentResponse(
                text=stdout.strip(),
                duration_secs=duration,
                is_error=False
            )

    @staticmethod
    def _mangle_cwd(cwd: str) -> str:
        """Mangle a cwd path to match Claude's project directory naming.

        Claude replaces both / and . with - in the path.
        e.g. /Users/foo.bar/project → -Users-foo-bar-project
        """
        return cwd.replace("/", "-").replace(".", "-")

    def _read_session_response(self, session_id: str, cwd: str = "") -> Optional[str]:
        """Read the last assistant response from a Claude session JSONL file.

        Claude writes session history to:
          ~/.claude/projects/{mangled-cwd}/{session_id}.jsonl

        Each line is a JSON object. We want the last assistant turn's text
        content (tip from Symbolic: assistant content is a list of blocks,
        not a string — walk the block list and collect type=text).
        """
        try:
            if cwd:
                mangled = self._mangle_cwd(cwd)
                session_dir = Path.home() / ".claude" / "projects" / mangled
            else:
                session_dir = Path.home() / ".claude" / "projects"

            session_file = self._find_session_file(session_dir, session_id)
            if not session_file:
                logger.debug(f"Session file not found for {session_id}")
                return None

            # Read the file and find the last assistant text block.
            # Tip from Symbolic: some JSONL files only contain
            # file-history-snapshot entries — verify we found real content.
            last_text = None
            has_conversation = False
            with open(session_file) as f:
                for line in f:
                    try:
                        obj = json.loads(line.strip())
                        entry_type = obj.get("type", "")

                        # Track whether this file has real conversation turns
                        if entry_type in ("user", "assistant"):
                            has_conversation = True

                        if entry_type == "assistant" or (
                            obj.get("message", {}).get("role") == "assistant"
                        ):
                            # Assistant content is a list of blocks (text,
                            # tool_use, thinking, etc.) — extract text blocks
                            content = obj.get("message", {}).get("content", [])
                            if isinstance(content, list):
                                for block in content:
                                    if isinstance(block, dict) and block.get("type") == "text":
                                        last_text = block["text"]
                    except json.JSONDecodeError:
                        continue

            if not has_conversation:
                logger.debug(f"Session {session_id[:8]} has no conversation turns (snapshot-only)")
                return None

            if last_text:
                logger.info(f"Recovered {len(last_text)} chars from session file for {session_id[:8]}...")
            return last_text

        except Exception as e:
            logger.error(f"Error reading session file for {session_id}: {e}")
            return None

    def _find_session_file(self, search_dir: Path, session_id: str) -> Optional[Path]:
        """Find a session JSONL file by session ID.

        Tip from Symbolic: filter out *subagent* files — they're internal
        and shouldn't be used for session resume/reading.
        """
        target = f"{session_id}.jsonl"

        # Direct path check
        direct = search_dir / target
        if direct.exists() and "subagent" not in direct.name:
            return direct

        # Recursive search (for when cwd isn't known)
        if search_dir.exists():
            for path in search_dir.rglob(target):
                if "subagent" not in path.name:
                    return path

        return None

    def is_busy(self, agent_id: str) -> bool:
        """Check if an agent is currently processing."""
        lock = self._get_lock(agent_id)
        return lock.locked()

    def send_message_async(
        self,
        config: AgentConfig,
        message: str,
        on_complete: Callable[[AgentResponse], None]
    ) -> threading.Thread:
        """
        Send message asynchronously in a background thread.

        Args:
            config: Agent configuration
            message: Message to send
            on_complete: Callback(AgentResponse) when done

        Returns:
            Thread object for the async operation
        """
        thread = threading.Thread(
            target=self.send_message,
            args=(config, message, on_complete),
            daemon=True
        )
        thread.start()
        return thread


# Singleton instance
_process_manager = None


def get_process_manager() -> ProcessManager:
    """Get the singleton ProcessManager instance."""
    global _process_manager
    if _process_manager is None:
        _process_manager = ProcessManager()
    return _process_manager


if __name__ == "__main__":
    # Test the process manager
    pm = get_process_manager()

    config = AgentConfig(
        agent_id="test",
        name="Test Agent",
        cwd=str(Path.home()),
        model="haiku"
    )

    response = pm.send_message(config, "Say hello in exactly 3 words.")
    print(f"Response: {response}")
