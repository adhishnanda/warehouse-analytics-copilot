"""Tests for the query rewriting step.

The "rewrite actually improves the question" tests call the real local
Ollama backend (zero cost, no API key) and use loose keyword checks since
LLM output isn't deterministic. They're skipped if Ollama isn't reachable
so the suite still runs in environments without it. The fallback test is
fully deterministic and needs no backend.
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import OLLAMA_BASE_URL
from src.retrieval import rewriter
from src.retrieval.rewriter import rewrite_query


def _ollama_reachable() -> bool:
    try:
        urllib.request.urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=2)
        return True
    except (urllib.error.URLError, OSError):
        return False


requires_ollama = pytest.mark.skipif(
    not _ollama_reachable(), reason="Ollama backend not reachable at OLLAMA_BASE_URL"
)


def test_fallback_returns_original_question_when_backend_unreachable(monkeypatch):
    def _raise(*_args, **_kwargs):
        raise rewriter.OllamaUnavailableError("backend unreachable")

    monkeypatch.setattr(rewriter, "chat", _raise)
    question = "what was the rev by region last qtr"
    assert rewrite_query(question, timeout=2.0) == question


@requires_ollama
def test_rewrite_returns_nonempty_string():
    result = rewrite_query("how many orders did we get")
    assert isinstance(result, str)
    assert result.strip()


@requires_ollama
def test_rewrite_expands_abbreviated_question():
    result = rewrite_query("what was the rev by region last qtr").lower()
    assert "revenue" in result
    assert "region" in result


@requires_ollama
def test_rewrite_does_not_fabricate_an_answer():
    # The rewriter must reformulate the question, not answer it with a number.
    result = rewrite_query("what is our repeat customer rate")
    assert "%" not in result
    assert not any(char.isdigit() for char in result)
