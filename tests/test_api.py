"""Tests for the FastAPI backend (src/app/api.py). The LLM call is
monkeypatched for determinism (same approach as test_agent_loop.py) —
this checks the HTTP surface, response shape, and telemetry logging
call, not model quality.

The TestClient is module-scoped: FastAPI's lifespan builds a Retriever
and Reranker (loads sentence-transformer/cross-encoder weights) on
startup, and there's no need to pay that cost once per test.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import src.app.api as api
from src.config import DUCKDB_PATH
from src.llm_client import ChatCompletion
from src.retrieval.indexer import INDEX_PATH

pytestmark = pytest.mark.skipif(
    not (DUCKDB_PATH.exists() and INDEX_PATH.exists()),
    reason="warehouse/index not built yet — run scripts/seed_and_index.py",
)


@pytest.fixture(scope="module")
def client():
    with TestClient(api.app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def isolate_trace_log(monkeypatch, tmp_path):
    """api.py resolves TRACE_LOG_PATH at call time (a module-level name,
    not a bound default argument), so patching it here keeps every
    test's trace/feedback writes out of the real data/telemetry/ log.
    """
    monkeypatch.setattr(api, "TRACE_LOG_PATH", tmp_path / "traces.jsonl")


@pytest.fixture(autouse=True)
def reset_rate_limit(monkeypatch):
    """The rate limiter's counter is process-wide, module-level state -
    reset it per test so one test's call count can't leak into another's.
    """
    monkeypatch.setattr(api, "_rate_limit_state", {"date": None, "count": 0})


@pytest.fixture(autouse=True)
def default_chat_response(monkeypatch):
    """Every test gets a working SQL reply unless it overrides chat_with_usage itself."""
    monkeypatch.setattr(
        api,
        "chat_with_usage",
        lambda *a, **k: ChatCompletion(
            content="```sql\nSELECT COUNT(*) FROM fact_orders\n```",
            usage={"total_tokens": 42},
        ),
    )


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ask_returns_a_successful_answer(client):
    response = client.post("/ask", json={"question": "how many orders"})

    assert response.status_code == 200
    body = response.json()
    assert body["succeeded"] is True
    assert body["sql"] == "SELECT COUNT(*) FROM fact_orders"
    assert body["row_count"] == 1
    assert body["rows"][0][0] > 0
    assert body["query_id"]
    assert body["model"] == "llama3"
    assert body["chart_kind"] == "metric"


def test_ask_rejects_empty_question(client):
    response = client.post("/ask", json={"question": "   "})
    assert response.status_code == 400


def test_ask_logs_a_trace(client, monkeypatch):
    calls = []
    monkeypatch.setattr(api, "log_trace", lambda **kwargs: calls.append(kwargs))

    response = client.post("/ask", json={"question": "how many orders"})

    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0]["question"] == "how many orders"
    assert calls[0]["succeeded"] is True
    assert calls[0]["query_id"] == response.json()["query_id"]


def test_feedback_accepts_a_valid_vote(client):
    response = client.post("/feedback", json={"query_id": "some-id", "vote": "up"})
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_feedback_rejects_an_invalid_vote(client):
    response = client.post("/feedback", json={"query_id": "some-id", "vote": "sideways"})
    assert response.status_code == 400


def test_ask_reports_failure_when_guardrail_rejects_every_attempt(client, monkeypatch):
    monkeypatch.setattr(
        api,
        "chat_with_usage",
        lambda *a, **k: ChatCompletion(content="```sql\nDROP TABLE fact_orders\n```", usage={}),
    )
    response = client.post("/ask", json={"question": "how many orders"})

    assert response.status_code == 200
    body = response.json()
    assert body["succeeded"] is False
    assert body["error"] is not None
    assert body["row_count"] == 0
    assert body["chart_kind"] == "table"


def test_ask_is_never_rate_limited_on_the_free_backend(client, monkeypatch):
    monkeypatch.setattr(api, "AGENT_CHAT_BACKEND", "ollama")
    monkeypatch.setattr(api, "MAX_DAILY_QUERIES", 1)

    for _ in range(3):
        response = client.post("/ask", json={"question": "how many orders"})
        assert response.status_code == 200


def test_ask_is_rate_limited_on_the_paid_backend_once_the_daily_cap_is_hit(client, monkeypatch):
    monkeypatch.setattr(api, "AGENT_CHAT_BACKEND", "openai")
    monkeypatch.setattr(api, "MAX_DAILY_QUERIES", 2)
    monkeypatch.setattr(
        api,
        "chat_openai",
        lambda *a, **k: ChatCompletion(content="```sql\nSELECT COUNT(*) FROM fact_orders\n```", usage={}),
    )

    assert client.post("/ask", json={"question": "q1"}).status_code == 200
    assert client.post("/ask", json={"question": "q2"}).status_code == 200

    response = client.post("/ask", json={"question": "q3"})

    assert response.status_code == 429
    assert "Daily query limit" in response.json()["detail"]
