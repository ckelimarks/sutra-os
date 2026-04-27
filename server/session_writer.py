"""
Session Writer — append-only JSONL session files per agent.
Pure functions for reading/writing universal session format.
"""

from pathlib import Path
from typing import List, Optional
from schema import Turn, serialize_turn, deserialize_turn

DEFAULT_SESSION_DIR = Path(__file__).parent.parent / "data" / "sessions"


def ensure_session_dir(session_dir: Path = DEFAULT_SESSION_DIR) -> Path:
    """Create session directory if it doesn't exist."""
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def session_path(session_dir: Path, agent_id: str) -> Path:
    """Get the JSONL file path for an agent's session."""
    return session_dir / f"{agent_id}.jsonl"


def append_turn(
    session_dir: Path,
    agent_id: str,
    turn: Turn,
) -> Path:
    """Append a turn to an agent's session file. Returns the file path."""
    ensure_session_dir(session_dir)
    path = session_path(session_dir, agent_id)
    with open(path, "a") as f:
        f.write(serialize_turn(turn) + "\n")
    return path


def append_turns(
    session_dir: Path,
    agent_id: str,
    turns: List[Turn],
) -> Path:
    """Append multiple turns to an agent's session file."""
    ensure_session_dir(session_dir)
    path = session_path(session_dir, agent_id)
    with open(path, "a") as f:
        for turn in turns:
            f.write(serialize_turn(turn) + "\n")
    return path


def read_session(
    session_dir: Path,
    agent_id: str,
) -> List[Turn]:
    """Read all turns from an agent's session file."""
    path = session_path(session_dir, agent_id)
    if not path.exists():
        return []

    turns = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                turns.append(deserialize_turn(line))
    return turns


def read_session_since(
    session_dir: Path,
    agent_id: str,
    since_ts: str,
) -> List[Turn]:
    """Read turns after a given ISO timestamp."""
    all_turns = read_session(session_dir, agent_id)
    return [t for t in all_turns if t.ts > since_ts]


def get_session_summary(
    session_dir: Path,
    agent_id: str,
) -> dict:
    """Get summary stats for an agent's session.

    Returns: {
        "agent_id": str,
        "turn_count": int,
        "total_cost_usd": float,
        "total_input_tokens": int,
        "total_output_tokens": int,
        "first_ts": str | None,
        "last_ts": str | None,
        "providers": list[str],
        "models": list[str],
    }
    """
    turns = read_session(session_dir, agent_id)

    if not turns:
        return {
            "agent_id": agent_id,
            "turn_count": 0,
            "total_cost_usd": 0.0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "first_ts": None,
            "last_ts": None,
            "providers": [],
            "models": [],
        }

    total_cost = sum(t.cost_usd for t in turns)
    total_input = sum(t.tokens.get("input", 0) for t in turns)
    total_output = sum(t.tokens.get("output", 0) for t in turns)
    providers = list(set(t.provider for t in turns))
    models = list(set(t.model for t in turns))

    return {
        "agent_id": agent_id,
        "turn_count": len(turns),
        "total_cost_usd": total_cost,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "first_ts": turns[0].ts,
        "last_ts": turns[-1].ts,
        "providers": providers,
        "models": models,
    }
