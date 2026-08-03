"""Tests for the agent orchestration loop.

Two kinds of test here:
- Deterministic tests that monkeypatch the LLM call, so retry mechanics
  (stop on success, retry on guardrail failure, stop after max_attempts,
  stop immediately if the backend is unreachable) are verified without
  depending on any particular model's SQL quality.
- Real end-to-end tests against the local Ollama backend and the actual
  warehouse, skipped if Ollama isn't reachable. These are not a claim
  about accuracy (that's Week 2's evaluation) — just that the pipeline
  produces a plausible answer for a simple, low-ambiguity question.
"""

import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.agent import loop
from src.agent.loop import MAX_ATTEMPTS, SqlGenerationError, _extract_sql, answer_question
from src.config import DUCKDB_PATH, OLLAMA_BASE_URL
from src.db.duckdb_client import get_connection
from src.llm_client import OllamaUnavailableError
from src.retrieval.indexer import INDEX_PATH
from src.retrieval.reranker import Reranker
from src.retrieval.retriever import Retriever

pytestmark = pytest.mark.skipif(
    not (DUCKDB_PATH.exists() and INDEX_PATH.exists()),
    reason="warehouse/index not built yet — run scripts/seed_and_index.py",
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


@pytest.fixture(scope="module")
def retriever():
    return Retriever()


@pytest.fixture(scope="module")
def reranker():
    return Reranker()


@pytest.fixture
def con():
    connection = get_connection()
    yield connection
    connection.close()


# --- _extract_sql ---------------------------------------------------


@pytest.mark.parametrize(
    "reply,expected",
    [
        ("```sql\nSELECT 1\n```", "SELECT 1"),
        ("```sql\nSELECT 1", "SELECT 1"),  # unclosed fence
        ("```\nSELECT 1\n```", "SELECT 1"),  # fence with no language tag
        ("SELECT 1", "SELECT 1"),  # no fence at all
        ("```sql\nSELECT 1;\n```", "SELECT 1"),  # trailing semicolon stripped
    ],
)
def test_extract_sql(reply, expected):
    assert _extract_sql(reply) == expected


# --- retry mechanics (deterministic, LLM call monkeypatched) ------------


def test_stops_after_first_success(monkeypatch, con, retriever, reranker):
    monkeypatch.setattr(loop, "chat", lambda *a, **k: "```sql\nSELECT COUNT(*) FROM fact_orders\n```")

    response = answer_question("how many orders", con, retriever, reranker)

    assert response.succeeded is True
    assert len(response.attempts) == 1


def test_retries_up_to_max_attempts_on_guardrail_violation(monkeypatch, con, retriever, reranker):
    monkeypatch.setattr(loop, "chat", lambda *a, **k: "```sql\nDROP TABLE fact_orders\n```")

    response = answer_question("how many orders", con, retriever, reranker)

    assert response.succeeded is False
    assert len(response.attempts) == MAX_ATTEMPTS
    assert all(not attempt.valid for attempt in response.attempts)
    assert all("SELECT" in attempt.error for attempt in response.attempts)


def test_stops_immediately_if_backend_unreachable(monkeypatch, con, retriever, reranker):
    def _raise(*_args, **_kwargs):
        raise OllamaUnavailableError("backend down")

    monkeypatch.setattr(loop, "chat", _raise)

    response = answer_question("how many orders", con, retriever, reranker)

    assert response.succeeded is False
    assert len(response.attempts) == 1


def test_generate_sql_raises_on_backend_unreachable(monkeypatch):
    def _raise(*_args, **_kwargs):
        raise OllamaUnavailableError("backend down")

    monkeypatch.setattr(loop, "chat", _raise)

    with pytest.raises(SqlGenerationError):
        loop.generate_sql("how many orders", context=[])


def test_chat_fn_override_bypasses_module_level_chat(monkeypatch, con, retriever, reranker):
    # module-level chat() would raise if called; passing chat_fn should mean it never is
    monkeypatch.setattr(loop, "chat", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")))
    calls = {"n": 0}

    def fake_chat_fn(_system, _user):
        calls["n"] += 1
        return "```sql\nSELECT COUNT(*) FROM fact_orders\n```"

    response = answer_question("how many orders", con, retriever, reranker, chat_fn=fake_chat_fn)

    assert response.succeeded is True
    assert calls["n"] == 1


def test_response_includes_retrieved_context(monkeypatch, con, retriever, reranker):
    monkeypatch.setattr(loop, "chat", lambda *a, **k: "```sql\nSELECT COUNT(*) FROM fact_orders\n```")

    response = answer_question("what is our repeat customer rate", con, retriever, reranker)

    assert len(response.context) > 0
    assert any(chunk["doc_id"] == "metric:repeat_customer_rate" for chunk in response.context)


# --- real end-to-end (local Ollama) --------------------------------------


@requires_ollama
def test_answers_a_simple_counting_question(con, retriever, reranker):
    response = answer_question("How many orders do we have in total?", con, retriever, reranker)

    assert response.succeeded is True
    assert response.final_result is not None
    assert response.final_result.rows[0][0] > 0
