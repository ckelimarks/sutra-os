"""
Universal Session Schema for Sutra Orchestrator.
Provider-agnostic turn format — portable across Claude/Gemini/Ollama.
"""

import json
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Optional


VALID_ROLES = {"user", "assistant", "tool_call", "tool_result"}
VALID_PROVIDERS = {"claude", "gemini", "ollama"}


@dataclass
class Turn:
    """A single turn in a conversation session."""
    turn_id: str
    session_id: str
    role: str            # user | assistant | tool_call | tool_result
    content: str
    provider: str        # claude | gemini | ollama
    model: str
    ts: str              # ISO 8601
    cost_usd: float
    tokens: dict = field(default_factory=lambda: {"input": 0, "output": 0})


def create_turn(
    session_id: str,
    role: str,
    content: str,
    provider: str,
    model: str,
    cost_usd: float = 0.0,
    tokens: Optional[dict] = None,
    turn_id: Optional[str] = None,
    ts: Optional[str] = None,
) -> Turn:
    """Create a new Turn with sensible defaults."""
    return Turn(
        turn_id=turn_id or str(uuid.uuid4()),
        session_id=session_id,
        role=role,
        content=content,
        provider=provider,
        model=model,
        ts=ts or datetime.now(timezone.utc).isoformat(),
        cost_usd=cost_usd,
        tokens=tokens or {"input": 0, "output": 0},
    )


def turn_to_dict(turn: Turn) -> dict:
    """Convert a Turn to a plain dictionary."""
    return asdict(turn)


def dict_to_turn(data: dict) -> Turn:
    """Convert a dictionary to a Turn."""
    return Turn(
        turn_id=data["turn_id"],
        session_id=data["session_id"],
        role=data["role"],
        content=data["content"],
        provider=data["provider"],
        model=data["model"],
        ts=data["ts"],
        cost_usd=data.get("cost_usd", 0.0),
        tokens=data.get("tokens", {"input": 0, "output": 0}),
    )


def validate_turn(data: dict) -> tuple[bool, list[str]]:
    """Validate a turn dictionary. Returns (is_valid, errors)."""
    errors = []
    required = ["turn_id", "session_id", "role", "content", "provider", "model", "ts"]
    for field_name in required:
        if field_name not in data:
            errors.append(f"missing required field: {field_name}")

    if "role" in data and data["role"] not in VALID_ROLES:
        errors.append(f"invalid role: {data['role']} (expected one of {VALID_ROLES})")

    if "provider" in data and data["provider"] not in VALID_PROVIDERS:
        errors.append(f"invalid provider: {data['provider']} (expected one of {VALID_PROVIDERS})")

    if "cost_usd" in data and not isinstance(data["cost_usd"], (int, float)):
        errors.append(f"cost_usd must be a number, got {type(data['cost_usd'])}")

    if "tokens" in data:
        tokens = data["tokens"]
        if not isinstance(tokens, dict):
            errors.append("tokens must be a dict with 'input' and 'output' keys")

    return (len(errors) == 0, errors)


def serialize_turn(turn: Turn) -> str:
    """Serialize a Turn to a JSON line (no trailing newline)."""
    return json.dumps(turn_to_dict(turn), separators=(",", ":"))


def deserialize_turn(line: str) -> Turn:
    """Deserialize a JSON line to a Turn."""
    return dict_to_turn(json.loads(line.strip()))
