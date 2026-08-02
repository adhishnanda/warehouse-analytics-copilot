"""Tests for the shared Ollama chat client."""

import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import OLLAMA_BASE_URL
from src import llm_client
from src.llm_client import OllamaUnavailableError, chat


def _ollama_reachable() -> bool:
    try:
        urllib.request.urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=2)
        return True
    except (urllib.error.URLError, OSError):
        return False


requires_ollama = pytest.mark.skipif(
    not _ollama_reachable(), reason="Ollama backend not reachable at OLLAMA_BASE_URL"
)


def test_chat_raises_on_unreachable_backend(monkeypatch):
    monkeypatch.setattr(llm_client, "OLLAMA_BASE_URL", "http://localhost:1")
    with pytest.raises(OllamaUnavailableError):
        chat("system", "user", timeout=2.0, model="llama3")


@requires_ollama
def test_chat_returns_nonempty_reply():
    reply = chat("You are a terse assistant.", "Reply with exactly one word.")
    assert isinstance(reply, str)
    assert reply.strip()
