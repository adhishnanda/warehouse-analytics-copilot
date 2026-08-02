"""Chat-completion clients: local Ollama, plus Groq and OpenAI (both
OpenAI-compatible hosted APIs, used for the Week 2 LLM evaluation).

Shared by every caller that needs an LLM turn so request/timeout/error
handling isn't duplicated per provider.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from src.config import (
    GROQ_API_KEY,
    GROQ_MODEL,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OPENAI_API_KEY,
    OPENAI_MODEL,
)


class OllamaUnavailableError(Exception):
    """Raised when the local Ollama backend cannot be reached in time."""


class ApiUnavailableError(Exception):
    """Raised when a hosted (Groq/OpenAI) chat completion call fails."""


@dataclass
class ChatCompletion:
    content: str
    usage: dict = field(default_factory=dict)


def chat_with_usage(
    system_prompt: str, user_content: str, model: str = OLLAMA_MODEL, timeout: float = 30.0
) -> ChatCompletion:
    """Like chat(), but also returns Ollama's reported token usage
    (prompt_eval_count/eval_count), for consistent reporting alongside
    chat_groq/chat_openai in evaluation scripts.

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

    content = body.get("message", {}).get("content", "").strip()
    prompt_tokens = body.get("prompt_eval_count", 0)
    completion_tokens = body.get("eval_count", 0)
    usage = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
    return ChatCompletion(content=content, usage=usage)


def chat(system_prompt: str, user_content: str, model: str = OLLAMA_MODEL, timeout: float = 30.0) -> str:
    """Send a single system+user turn to a local Ollama model and return
    the assistant's reply text. See chat_with_usage for the full response
    including token usage.
    """
    return chat_with_usage(system_prompt, user_content, model, timeout).content


def chat_openai_compatible(
    base_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_content: str,
    timeout: float = 60.0,
) -> ChatCompletion:
    """Call an OpenAI-compatible /chat/completions endpoint (used for both
    Groq and OpenAI, which share the same request/response shape).
    """
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # Groq's Cloudflare protection blocks urllib's default User-Agent.
            "User-Agent": "curl/8.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise ApiUnavailableError(f"HTTP {exc.code}: {exc.read().decode(errors='replace')}") from exc
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
        raise ApiUnavailableError(str(exc)) from exc

    content = body["choices"][0]["message"]["content"].strip()
    return ChatCompletion(content=content, usage=body.get("usage", {}))


def chat_groq(
    system_prompt: str, user_content: str, model: str = GROQ_MODEL, timeout: float = 60.0
) -> ChatCompletion:
    return chat_openai_compatible(
        "https://api.groq.com/openai/v1", GROQ_API_KEY, model, system_prompt, user_content, timeout
    )


def chat_openai(
    system_prompt: str, user_content: str, model: str = OPENAI_MODEL, timeout: float = 60.0
) -> ChatCompletion:
    return chat_openai_compatible(
        "https://api.openai.com/v1", OPENAI_API_KEY, model, system_prompt, user_content, timeout
    )
