"""Claude CLI adapter — wraps process_manager, translates to universal Turn schema."""

from typing import Optional, List
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from .base import ProviderAdapter
from schema import Turn, create_turn
from process_manager import get_process_manager, AgentConfig, AgentResponse


def agent_response_to_turns(
    response: AgentResponse,
    session_id: str,
    model: str,
    user_message: str,
) -> List[Turn]:
    """Convert an AgentResponse into universal Turn objects."""
    turns = []

    # User turn
    turns.append(create_turn(
        session_id=session_id,
        role="user",
        content=user_message,
        provider="claude",
        model=model,
        cost_usd=0.0,
    ))

    # Assistant turn
    usage = response.usage or {}
    tokens = {
        "input": usage.get("input_tokens", 0),
        "output": usage.get("output_tokens", 0),
    }
    turns.append(create_turn(
        session_id=response.session_id or session_id,
        role="assistant",
        content=response.text,
        provider="claude",
        model=model,
        cost_usd=response.cost_usd,
        tokens=tokens,
    ))

    return turns


class ClaudeCLIAdapter(ProviderAdapter):
    """Adapter for Claude via the CLI subprocess."""

    def __init__(self, agent_id: str, name: str, cwd: str, default_model: str = "sonnet"):
        self.agent_id = agent_id
        self.name = name
        self.cwd = cwd
        self.default_model = default_model

    def provider_name(self) -> str:
        return "claude"

    def send(
        self,
        message: str,
        session_id: Optional[str] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        cwd: Optional[str] = None,
    ) -> List[Turn]:
        model = model or self.default_model
        config = AgentConfig(
            agent_id=self.agent_id,
            name=self.name,
            cwd=cwd or self.cwd,
            model=model,
            system_prompt=system_prompt,
            session_id=session_id,
        )

        pm = get_process_manager()
        response = pm.send_message(config, message)

        effective_session = response.session_id or session_id or "unknown"
        return agent_response_to_turns(response, effective_session, model, message)
