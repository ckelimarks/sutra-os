"""Local Qwen 2.5 1.5B client via llama-server OpenAI-compatible API."""

import json
import requests


class QwenClient:
    """Thin client for Qwen 2.5 1.5B running on llama-server."""

    def __init__(self, base_url="http://localhost:11434", model="qwen2.5:0.5b"):
        self.base_url = base_url.rstrip("/")
        self.endpoint = f"{self.base_url}/v1/chat/completions"
        self.model = model

    def is_available(self) -> bool:
        try:
            # Ollama uses /api/tags, llama-server uses /health
            r = requests.get(f"{self.base_url}/api/tags", timeout=2)
            if r.status_code == 200:
                return True
            r = requests.get(f"{self.base_url}/health", timeout=2)
            return r.status_code == 200
        except requests.ConnectionError:
            return False

    def generate(self, prompt: str, system: str = None, max_tokens: int = 50, stream: bool = False) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": stream,
            "temperature": 0.7,
        }

        try:
            if stream:
                return "".join(self.generate_stream(prompt, system, max_tokens))

            r = requests.post(self.endpoint, json=payload, timeout=10)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except (requests.ConnectionError, requests.Timeout):
            return "I hear you."
        except (KeyError, IndexError, requests.HTTPError):
            return "I hear you."

    def generate_stream(self, prompt: str, system: str = None, max_tokens: int = 50):
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": True,
            "temperature": 0.7,
        }

        try:
            r = requests.post(self.endpoint, json=payload, timeout=10, stream=True)
            r.raise_for_status()

            for line in r.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0]["delta"]
                    if "content" in delta:
                        yield delta["content"]
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError):
            yield "I hear you."


# --- Pre-built prompt functions ---

ACKS = [
    "Got it, on it.",
    "One sec, checking.",
    "Pulling that up.",
    "Let me look into that.",
    "Checking now.",
    "On it.",
    "Hmm, let me think.",
    "Right, working on that.",
]


def acknowledge(transcript: str) -> str:
    """System prompt for closed-class ack selection. Model picks a number, not free text."""
    ack_list = "\n".join(f"{i+1}. {a}" for i, a in enumerate(ACKS))
    return (
        f"User said: \"{transcript}\"\n"
        f"Which acknowledgment fits best? Reply with ONLY the number (1-{len(ACKS)}).\n"
        f"{ack_list}"
    )


def route(transcript: str) -> str:
    return (
        "You are a routing classifier. Given the user's speech, decide if it can be handled "
        "locally (simple acknowledgment, greeting, filler) or needs Claude (complex questions, "
        "code, analysis, multi-step reasoning). "
        'Respond with ONLY valid JSON: {"route": "local" or "claude", "reason": "brief reason"}. '
        "No other text."
    )


def narrate_tool(tool_name: str, tool_input: str) -> str:
    return (
        "Describe what this tool call does in 5-8 words. "
        "Use natural, conversational language. No technical jargon. "
        "Example: 'Looking up your recent files' or 'Checking the weather forecast'. "
        f"Tool: {tool_name}, Input: {tool_input}"
    )
