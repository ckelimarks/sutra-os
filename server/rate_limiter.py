"""
Rate Limiter for Sutra Orchestrator.
Tracks rate limit state per provider with exponential backoff.
"""

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List


MAX_BACKOFF_SECS = 120.0


@dataclass
class RateLimitState:
    """Rate limit state for a provider."""
    provider: str
    is_limited: bool = False
    retry_after: Optional[float] = None
    backoff_until: Optional[str] = None
    consecutive_limits: int = 0


# Module-level state
_states: Dict[str, RateLimitState] = {}


def calculate_backoff(consecutive_limits: int) -> float:
    """Exponential backoff: 2^n seconds, capped at MAX_BACKOFF_SECS."""
    return min(2.0 ** consecutive_limits, MAX_BACKOFF_SECS)


def parse_rate_limit(response_text: str, status_code: int = 200) -> Optional[RateLimitState]:
    """Detect rate limiting from a response.

    Returns RateLimitState if limited, None if OK.
    """
    if status_code == 429 or "rate limit" in response_text.lower():
        return RateLimitState(
            provider="unknown",
            is_limited=True,
            consecutive_limits=1,
        )
    if status_code == 529 or "overloaded" in response_text.lower():
        return RateLimitState(
            provider="unknown",
            is_limited=True,
            consecutive_limits=1,
        )
    return None


def record_rate_limit(provider: str) -> RateLimitState:
    """Record a rate limit hit for a provider."""
    existing = _states.get(provider, RateLimitState(provider=provider))
    existing.consecutive_limits += 1
    existing.is_limited = True

    backoff_secs = calculate_backoff(existing.consecutive_limits)
    existing.retry_after = backoff_secs
    existing.backoff_until = (
        datetime.now(timezone.utc) + timedelta(seconds=backoff_secs)
    ).isoformat()

    _states[provider] = existing
    return existing


def record_success(provider: str) -> None:
    """Clear rate limit state for a provider on success."""
    if provider in _states:
        _states[provider] = RateLimitState(provider=provider)


def get_state(provider: str) -> RateLimitState:
    """Get current rate limit state for a provider."""
    return _states.get(provider, RateLimitState(provider=provider))


def is_limited(provider: str) -> bool:
    """Check if a provider is currently rate-limited."""
    state = get_state(provider)
    if not state.is_limited:
        return False

    # Check if backoff period has passed
    if state.backoff_until:
        now = datetime.now(timezone.utc).isoformat()
        if now > state.backoff_until:
            # Backoff expired, clear state
            record_success(provider)
            return False

    return True


def should_reroute(state: RateLimitState) -> bool:
    """True if we should switch to a fallback provider."""
    return state.is_limited and state.consecutive_limits >= 2


def get_available_providers(providers: List[str]) -> List[str]:
    """Filter to providers not currently rate-limited."""
    return [p for p in providers if not is_limited(p)]


def reset_all() -> None:
    """Clear all rate limit state (for testing)."""
    _states.clear()
