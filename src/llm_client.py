"""Chat-completion clients: local Ollama, plus Groq and OpenAI (both
OpenAI-compatible hosted APIs, used for the Week 2 LLM evaluation).

Shared by every caller that needs an LLM turn so request/timeout/error
handling isn't duplicated per provider.

Every outbound call is additionally bounded by a hard wall-clock timeout
(_call_with_wall_clock_timeout), on top of urlopen's own timeout=
parameter. urlopen's timeout only covers the connect/send/receive phases
- it does not cover DNS resolution (socket.getaddrinfo runs unbounded
before the timeout-guarded connect() even starts), so a slow or stuck
resolver can hang a call far past its stated timeout with no way for the
caller to bound it. Observed live: this made the first real /ask request
on Render's free tier hang for minutes with no response at all, even
though every step in the pipeline had its own timeout on paper. Mirrors
the watchdog-thread pattern already used for DB queries in
src/agent/guardrails.py's run_guarded_query.
"""

from __future__ import annotations

import json
import threading
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

# Extra headroom added on top of a call's own timeout= before the hard
# wall-clock cutoff fires - lets the normal (connected, just slow) case
# surface urlopen's own clearer error first; this is purely a backstop
# for the DNS-hang case that timeout= can't reach.
_WALL_CLOCK_BUFFER_SECONDS = 10.0


class OllamaUnavailableError(Exception):
    """Raised when the local Ollama backend cannot be reached in time."""


class ApiUnavailableError(Exception):
    """Raised when a hosted (Groq/OpenAI) chat completion call fails."""


@dataclass
class ChatCompletion:
    content: str
    usage: dict = field(default_factory=dict)


def _call_with_wall_clock_timeout(fn, timeout_seconds: float, timeout_exc: Exception):
    """Run fn() on a background thread and enforce a hard wall-clock
    timeout, so a phase fn doesn't itself bound (DNS resolution, most
    notably - see the module docstring) can't hang the caller past
    timeout_seconds.

    fn keeps running on its thread if it doesn't finish in time (Python
    threads can't be killed), but the caller gets control back regardless,
    with timeout_exc raised in place of an indefinite hang.
    """
    result_holder: dict = {}
    error_holder: dict = {}

    def _run() -> None:
        try:
            result_holder["value"] = fn()
        except Exception as exc:  # noqa: BLE001 - re-raised on the calling thread
            error_holder["error"] = exc

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout_seconds)

    if thread.is_alive():
        raise timeout_exc
    if "error" in error_holder:
        raise error_holder["error"]
    return result_holder["value"]


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

    def _do_request() -> dict:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())

    try:
        body = _call_with_wall_clock_timeout(
            _do_request,
            timeout + _WALL_CLOCK_BUFFER_SECONDS,
            OllamaUnavailableError(f"No response from Ollama within {timeout + _WALL_CLOCK_BUFFER_SECONDS}s."),
        )
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

    def _do_request() -> dict:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())

    try:
        body = _call_with_wall_clock_timeout(
            _do_request,
            timeout + _WALL_CLOCK_BUFFER_SECONDS,
            ApiUnavailableError(f"No response from {base_url} within {timeout + _WALL_CLOCK_BUFFER_SECONDS}s."),
        )
    except urllib.error.HTTPError as exc:
        raise ApiUnavailableError(f"HTTP {exc.code}: {exc.read().decode(errors='replace')}") from exc
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
        raise ApiUnavailableError(str(exc)) from exc

    content = body["choices"][0]["message"]["content"].strip()
    return ChatCompletion(content=content, usage=body.get("usage", {}))


def embed_openai(
    texts: list[str], model: str = "text-embedding-3-small", timeout: float = 30.0
) -> list[list[float]]:
    """Call OpenAI's embeddings endpoint for one or more texts in a single
    request. Used by the deployed instance's API-backed retrieval path
    (RETRIEVAL_BACKEND=openai, see src/retrieval/retriever.py) as a
    torch-free alternative to the local sentence-transformers embedding
    model.
    """
    payload = {"model": model, "input": texts}
    request = urllib.request.Request(
        "https://api.openai.com/v1/embeddings",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    def _do_request() -> dict:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())

    try:
        body = _call_with_wall_clock_timeout(
            _do_request,
            timeout + _WALL_CLOCK_BUFFER_SECONDS,
            ApiUnavailableError(
                f"No response from OpenAI embeddings within {timeout + _WALL_CLOCK_BUFFER_SECONDS}s."
            ),
        )
    except urllib.error.HTTPError as exc:
        raise ApiUnavailableError(f"HTTP {exc.code}: {exc.read().decode(errors='replace')}") from exc
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
        raise ApiUnavailableError(str(exc)) from exc

    # data isn't guaranteed to preserve input order per OpenAI's own docs -
    # each item's index field is the source of truth.
    ordered = sorted(body["data"], key=lambda item: item["index"])
    return [item["embedding"] for item in ordered]


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
