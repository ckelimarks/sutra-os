"""Ollama adapter — wraps Ollama's local HTTP API, translates to universal Turn schema."""

import json
import logging
from typing import Optional, List

import requests

from .base import ProviderAdapter

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from schema import Turn, create_turn

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5-coder"


def ollama_chat(
    message: str,
    model: str = DEFAULT_MODEL,
    system_prompt: Optional[str] = None,
    history: Optional[List[dict]] = None,
    base_url: str = OLLAMA_BASE_URL,
) -> dict:
    """Send a chat message to Ollama and return the raw response.

    Returns: {"message": {"role": "assistant", "content": "..."}, "total_duration": int, ...}
    """
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": message})

    response = requests.post(
        f"{base_url}/api/chat",
        json={"model": model, "messages": messages, "stream": False},
        timeout=300,
    )
    response.raise_for_status()
    return response.json()


def ollama_response_to_turns(
    raw: dict,
    session_id: str,
    model: str,
    user_message: str,
) -> List[Turn]:
    """Convert an Ollama response to universal Turns."""
    turns = []

    # User turn
    turns.append(create_turn(
        session_id=session_id,
        role="user",
        content=user_message,
        provider="ollama",
        model=model,
        cost_usd=0.0,
    ))

    # Assistant turn
    assistant_content = raw.get("message", {}).get("content", "")
    eval_count = raw.get("eval_count", 0)
    prompt_eval_count = raw.get("prompt_eval_count", 0)

    turns.append(create_turn(
        session_id=session_id,
        role="assistant",
        content=assistant_content,
        provider="ollama",
        model=model,
        cost_usd=0.0,  # local model, always free
        tokens={"input": prompt_eval_count, "output": eval_count},
    ))

    return turns


class OllamaAdapter(ProviderAdapter):
    """Adapter for local Ollama models."""

    def __init__(
        self,
        default_model: str = DEFAULT_MODEL,
        base_url: str = OLLAMA_BASE_URL,
    ):
        self.default_model = default_model
        self.base_url = base_url
        self._history: List[dict] = []

    def provider_name(self) -> str:
        return "ollama"

    def send(
        self,
        message: str,
        session_id: Optional[str] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        cwd: Optional[str] = None,
    ) -> List[Turn]:
        model = model or self.default_model
        session_id = session_id or "ollama-local"

        try:
            raw = ollama_chat(
                message=message,
                model=model,
                system_prompt=system_prompt,
                history=self._history,
                base_url=self.base_url,
            )
        except requests.ConnectionError:
            logger.error("Ollama not running at %s", self.base_url)
            return [create_turn(
                session_id=session_id,
                role="assistant",
                content="Error: Ollama is not running. Start it with `ollama serve`.",
                provider="ollama",
                model=model,
            )]
        except Exception as e:
            logger.error("Ollama error: %s", e)
            return [create_turn(
                session_id=session_id,
                role="assistant",
                content=f"Error: {e}",
                provider="ollama",
                model=model,
            )]

        # Append to history for multi-turn
        self._history.append({"role": "user", "content": message})
        assistant_content = raw.get("message", {}).get("content", "")
        self._history.append({"role": "assistant", "content": assistant_content})

        return ollama_response_to_turns(raw, session_id, model, message)
