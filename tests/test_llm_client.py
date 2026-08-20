"""Tests for the shared chat-completion clients: Ollama, Groq, OpenAI."""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import GROQ_API_KEY, OLLAMA_BASE_URL, OPENAI_API_KEY
from src import llm_client
from src.llm_client import (
    ApiUnavailableError,
    ChatCompletion,
    OllamaUnavailableError,
    chat,
    chat_groq,
    chat_openai,
    embed_openai,
)


def _ollama_reachable() -> bool:
    try:
        urllib.request.urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=2)
        return True
    except (urllib.error.URLError, OSError):
        return False


requires_ollama = pytest.mark.skipif(
    not _ollama_reachable(), reason="Ollama backend not reachable at OLLAMA_BASE_URL"
)
requires_groq_key = pytest.mark.skipif(not GROQ_API_KEY, reason="GROQ_API_KEY not set")
requires_openai_key = pytest.mark.skipif(not OPENAI_API_KEY, reason="OPENAI_API_KEY not set")


def test_chat_raises_on_unreachable_backend(monkeypatch):
    monkeypatch.setattr(llm_client, "OLLAMA_BASE_URL", "http://localhost:1")
    with pytest.raises(OllamaUnavailableError):
        chat("system", "user", timeout=2.0, model="llama3")


@requires_ollama
def test_chat_returns_nonempty_reply():
    reply = chat("You are a terse assistant.", "Reply with exactly one word.")
    assert isinstance(reply, str)
    assert reply.strip()


def test_chat_raises_after_wall_clock_timeout_when_urlopen_hangs(monkeypatch):
    """Simulates the real failure this guards against: something before
    urlopen's own timeout= can apply (a stuck DNS resolution, in
    practice) stalls the call well past its stated timeout. Without the
    wall-clock backstop this would hang for as long as _hangs_forever
    sleeps; with it, chat() must still return control within roughly
    timeout + the (shrunk, for test speed) buffer.
    """
    monkeypatch.setattr(llm_client, "_WALL_CLOCK_BUFFER_SECONDS", 0.2)

    def _hangs_forever(*_args, **_kwargs):
        time.sleep(30)

    monkeypatch.setattr(urllib.request, "urlopen", _hangs_forever)

    start = time.monotonic()
    with pytest.raises(OllamaUnavailableError):
        chat("system", "user", timeout=0.3, model="llama3")
    elapsed = time.monotonic() - start

    assert elapsed < 5.0


def test_chat_openai_compatible_raises_on_bad_key():
    with pytest.raises(ApiUnavailableError):
        llm_client.chat_openai_compatible(
            "https://api.groq.com/openai/v1", "invalid-key", "llama-3.3-70b-versatile",
            "system", "user", timeout=10.0,
        )


@requires_groq_key
def test_chat_groq_returns_nonempty_reply():
    result = chat_groq("You are a terse assistant.", "Reply with exactly one word.")
    assert isinstance(result, ChatCompletion)
    assert result.content.strip()
    assert result.usage.get("total_tokens", 0) > 0


@requires_openai_key
def test_chat_openai_returns_nonempty_reply():
    result = chat_openai("You are a terse assistant.", "Reply with exactly one word.")
    assert isinstance(result, ChatCompletion)
    assert result.content.strip()
    assert result.usage.get("total_tokens", 0) > 0


def test_embed_openai_raises_on_bad_key(monkeypatch):
    monkeypatch.setattr(llm_client, "OPENAI_API_KEY", "invalid-key")
    with pytest.raises(ApiUnavailableError):
        embed_openai(["hello"], timeout=10.0)


def test_embed_openai_reorders_by_index_field(monkeypatch):
    """OpenAI's own docs say data isn't guaranteed to preserve input
    order - each item's index is the source of truth. Simulates a
    shuffled response to check embed_openai actually reorders rather
    than trusting array position.
    """

    class FakeResponse:
        def __init__(self, body: bytes):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    body = json.dumps(
        {
            "data": [
                {"index": 1, "embedding": [0.0, 1.0]},
                {"index": 0, "embedding": [1.0, 0.0]},
            ]
        }
    ).encode("utf-8")

    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: FakeResponse(body))

    vectors = embed_openai(["first", "second"])

    assert vectors == [[1.0, 0.0], [0.0, 1.0]]


@requires_openai_key
def test_embed_openai_returns_real_vectors():
    vectors = embed_openai(["revenue by region", "customer churn"])
    assert len(vectors) == 2
    assert len(vectors[0]) > 0
    assert vectors[0] != vectors[1]
