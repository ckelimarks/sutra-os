"""
Model Router for Sutra Orchestrator.
Pure functions for deciding which model/provider handles an instruction.
"""

import json
import logging
import subprocess
from dataclasses import dataclass
from typing import Optional, List

logger = logging.getLogger(__name__)


@dataclass
class RouteDecision:
    """Result of routing an instruction to a model/provider."""
    provider: str    # "claude" | "ollama"
    model: str       # "opus" | "sonnet" | "haiku" | "qwen2.5-coder"
    reason: str


DEFAULT_FALLBACK_CHAIN = ["sonnet", "haiku", "ollama:qwen2.5-coder"]

CODE_KEYWORDS = {
    "def ", "class ", "function ", "import ", "require(", "const ",
    "bug", "error", "fix", "refactor", "implement", "deploy", "test",
    "database", "query", "migration", "endpoint", "API",
    "dockerfile", "yaml", "config", "schema",
}

COMPLEX_INDICATORS = {
    "and then", "after that", "first", "then", "next",
    "step by step", "architecture", "design", "plan",
    "compare", "analyze", "evaluate", "review",
    "build", "create", "write a",
}


def classify_complexity_heuristic(instruction: str) -> str:
    """Keyword-based complexity classification (fallback).

    Returns: 'simple' | 'moderate' | 'complex'
    """
    words = instruction.split()
    word_count = len(words)
    lower = instruction.lower()

    has_code = any(kw.lower() in lower for kw in CODE_KEYWORDS)
    has_complex = any(ind in lower for ind in COMPLEX_INDICATORS)

    if word_count > 80 or (has_code and has_complex):
        return "complex"
    elif word_count < 20 and not has_code and not has_complex:
        return "simple"
    else:
        return "moderate"


def classify_complexity_llm(instruction: str) -> Optional[str]:
    """Classify instruction complexity using a Haiku LLM call.

    Returns: 'simple' | 'moderate' | 'complex', or None on failure.
    """
    prompt = (
        "Classify this instruction's complexity as exactly one word: simple, moderate, or complex.\n"
        "- simple: trivial questions, lookups, greetings, one-step tasks\n"
        "- moderate: standard tasks, explanations, multi-step but routine work\n"
        "- complex: architecture decisions, multi-file refactors, deep analysis, novel design\n\n"
        f"Instruction: {instruction}\n\n"
        "Reply with ONLY one word: simple, moderate, or complex"
    )
    try:
        result = subprocess.run(
            ["claude", "--print", "--output-format", "json", "--model", "haiku", "-p", prompt],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            logger.warning("Haiku classifier failed: %s", result.stderr[:200])
            return None

        # Parse JSON output
        for line in result.stdout.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                text = data.get('result', data.get('content', data.get('text', ''))).strip().lower()
                for level in ('simple', 'moderate', 'complex'):
                    if level in text:
                        return level
            except (json.JSONDecodeError, AttributeError):
                # Try as plain text
                text = line.strip().lower()
                for level in ('simple', 'moderate', 'complex'):
                    if level in text:
                        return level

        logger.warning("Haiku classifier returned unparseable response")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("Haiku classifier timed out")
        return None
    except Exception as e:
        logger.warning("Haiku classifier error: %s", e)
        return None


def classify_complexity(instruction: str, use_llm: bool = True) -> str:
    """Classify instruction complexity.

    Uses Haiku LLM call if use_llm=True, falls back to heuristic on failure.
    Returns: 'simple' | 'moderate' | 'complex'
    """
    if use_llm:
        result = classify_complexity_llm(instruction)
        if result:
            return result
        logger.info("LLM classifier failed, falling back to heuristic")

    return classify_complexity_heuristic(instruction)


def route_instruction(
    instruction: str,
    agent_model: str = "sonnet",
    budget_remaining: Optional[float] = None,
    prefer_local: bool = False,
    local_model: str = "qwen2.5-coder",
    fallback_chain: Optional[List[str]] = None,
    force_model: Optional[str] = None,
    use_llm_classifier: bool = True,
) -> RouteDecision:
    """Decide which model/provider handles this instruction.

    Rules (in priority order):
    1. force_model → use that model directly
    2. Budget < $0.50 → force haiku or ollama
    3. prefer_local → ollama
    4. simple → haiku
    5. complex → opus (unless agent is already opus)
    6. moderate → agent's default model
    """
    # Manual override (REQ-1.1.1)
    if force_model:
        provider, model = parse_provider_model(force_model)
        return RouteDecision(provider, model, f"force_model override → {force_model}")

    complexity = classify_complexity(instruction, use_llm=use_llm_classifier)

    # Budget constraint
    if budget_remaining is not None and budget_remaining < 0.50:
        if prefer_local:
            return RouteDecision("ollama", local_model, "budget_override — budget low + prefer local")
        return RouteDecision("claude", "haiku", "budget_override — budget low, forcing cheapest model")

    # Prefer local
    if prefer_local:
        return RouteDecision("ollama", local_model, "local model preferred")

    # Route by complexity
    if complexity == "simple":
        return RouteDecision("claude", "haiku", "simple query — fast and cheap")

    if complexity == "complex":
        if agent_model == "opus":
            return RouteDecision("claude", "opus", "complex query — agent already on opus")
        return RouteDecision("claude", "opus", "complex query — routing to most capable model")

    # Moderate — use agent's configured model
    return RouteDecision("claude", agent_model, f"moderate query — using agent default ({agent_model})")


def parse_provider_model(spec: str) -> tuple[str, str]:
    """Parse a 'provider:model' spec string.

    'sonnet' → ('claude', 'sonnet')
    'ollama:qwen2.5-coder' → ('ollama', 'qwen2.5-coder')
    'claude:haiku' → ('claude', 'haiku')
    """
    if ":" in spec:
        provider, model = spec.split(":", 1)
        return (provider, model)
    return ("claude", spec)
