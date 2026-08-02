"""Minimal chat-completion client for local Ollama models.

Shared by the query rewriter and the SQL generator so both go through the
same request/timeout/error handling rather than duplicating it.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from src.config import OLLAMA_BASE_URL, OLLAMA_MODEL


class OllamaUnavailableError(Exception):
    """Raised when the local Ollama backend cannot be reached in time."""


def chat(system_prompt: str, user_content: str, model: str = OLLAMA_MODEL, timeout: float = 30.0) -> str:
    """Send a single system+user turn to a local Ollama model and return
    the assistant's reply text.

    Raises OllamaUnavailableError if the backend cannot be reached in time —
    callers decide whether and how to fall back.
    """
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "stream": False,
    }
    request = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read())
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
        raise OllamaUnavailableError(str(exc)) from exc

    return body.get("message", {}).get("content", "").strip()
