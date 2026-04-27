"""Base adapter interface for AI providers."""

from abc import ABC, abstractmethod
from typing import Optional, List

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from schema import Turn


class ProviderAdapter(ABC):
    """Abstract base for provider adapters.

    Each adapter wraps a specific AI provider (Claude CLI, Ollama, etc.)
    and translates to/from the universal Turn schema.
    """

    @abstractmethod
    def send(
        self,
        message: str,
        session_id: Optional[str] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        cwd: Optional[str] = None,
    ) -> List[Turn]:
        """Send a message and return a list of Turns (user + assistant at minimum)."""
        ...

    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider identifier: 'claude', 'gemini', 'ollama'."""
        ...
