"""Tests for the monitoring JSON API (src/app/monitoring.py). Builds a real
telemetry.duckdb via the actual dlt pipeline against a temp JSONL fixture
(same pattern as tests/test_dlt_pipeline.py), then asserts each endpoint's
computed values exactly - never hand-typed expectations detached from a
real pipeline run.
"""

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import src.app.monitoring as monitoring
from src.app.api import app
from src.config import DUCKDB_PATH
from src.retrieval.indexer import INDEX_PATH
from src.telemetry.dlt_pipeline import run_pipeline

pytestmark = pytest.mark.skipif(
    not (DUCKDB_PATH.exists() and INDEX_PATH.exists()),
    reason="warehouse/index not built yet - run scripts/seed_and_index.py",
)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")


def _trace(query_id: str, **overrides) -> dict:
    record = {
        "event_type": "trace",
        "query_id": query_id,
        "timestamp": "2026-08-03T00:00:00+00:00",
        "question": "how many orders",
        "sql": "SELECT 1",
        "succeeded": True,
        "error": None,
        "attempt_count": 1,
        "row_count": 1,
        "latency_seconds": 1.0,
        "model": "llama3",
        "usage": {},
    }
    record.update(overrides)
    return record


def _feedback(query_id: str, vote: str) -> dict:
    return {"event_type": "feedback", "query_id": query_id, "timestamp": "2026-08-03T00:00:05+00:00", "vote": vote}


@pytest.fixture
def telemetry_db(tmp_path, monkeypatch):
    """Builds a real telemetry.duckdb from a fixture JSONL via the actual
    pipeline, then points src.app.monitoring at it. TELEMETRY_DB_PATH is
    read directly from the module body (not a bound default), so patching
    the module attribute here takes effect - same pattern api.py uses for
    TRACE_LOG_PATH.
    """
    jsonl_path = tmp_path / "traces.jsonl"
    db_path = tmp_path / "telemetry.duckdb"
    monkeypatch.setattr(monitoring, "TELEMETRY_DB_PATH", db_path)
    return jsonl_path, db_path


def test_summary_is_zeroed_when_no_telemetry_exists(client, telemetry_db):
    response = client.get("/monitoring/summary")

    assert response.status_code == 200
    assert response.json() == {
        "total_queries": 0,
        "execution_accuracy": 0.0,
        "total_cost_usd": 0.0,
        "feedback_rate": 0.0,
        "helpful_count": 0,
        "not_helpful_count": 0,
        "latency_p50_seconds": 0.0,
        "latency_p95_seconds": 0.0,
    }


def test_summary_computes_real_values_from_traces(client, telemetry_db):
    jsonl_path, db_path = telemetry_db
    _write_jsonl(
        jsonl_path,
        [
            _trace("q1", succeeded=True, latency_seconds=2.0, model="gpt-4o-mini",
                   usage={"prompt_tokens": 1000, "completion_tokens": 500}),
            _trace("q2", succeeded=False, error="Binder Error: column not found", latency_seconds=4.0),
            _feedback("q1", "up"),
        ],
    )
    run_pipeline(jsonl_path=jsonl_path, db_path=db_path)

    body = client.get("/monitoring/summary").json()

    assert body["total_queries"] == 2
    assert body["execution_accuracy"] == pytest.approx(0.5)
    assert body["total_cost_usd"] == pytest.approx(1000 * 0.15 / 1_000_000 + 500 * 0.60 / 1_000_000)
    assert body["feedback_rate"] == pytest.approx(0.5)
    assert body["helpful_count"] == 1
    assert body["not_helpful_count"] == 0
    assert body["latency_p50_seconds"] in (2.0, 4.0)
    assert body["latency_p95_seconds"] == 4.0


def test_timeseries_groups_by_date(client, telemetry_db):
    jsonl_path, db_path = telemetry_db
    _write_jsonl(
        jsonl_path,
        [
            _trace("q1", timestamp="2026-08-01T00:00:00+00:00"),
            _trace("q2", timestamp="2026-08-01T12:00:00+00:00", succeeded=False, error="Binder Error: x"),
            _trace("q3", timestamp="2026-08-02T00:00:00+00:00"),
        ],
    )
    run_pipeline(jsonl_path=jsonl_path, db_path=db_path)

    points = client.get("/monitoring/timeseries").json()["points"]

    assert points == [
        {"date": "2026-08-01", "query_count": 2, "execution_accuracy": pytest.approx(0.5), "avg_cost_usd": 0.0},
        {"date": "2026-08-02", "query_count": 1, "execution_accuracy": pytest.approx(1.0), "avg_cost_usd": 0.0},
    ]


def test_failures_categorizes_only_failed_traces(client, telemetry_db):
    jsonl_path, db_path = telemetry_db
    _write_jsonl(
        jsonl_path,
        [
            _trace("q1", succeeded=True),
            _trace("q2", succeeded=False, error="Binder Error: column not found"),
            _trace("q3", succeeded=False, error="Binder Error: another one"),
            _trace("q4", succeeded=False, error="Ollama backend unreachable"),
        ],
    )
    run_pipeline(jsonl_path=jsonl_path, db_path=db_path)

    categories = client.get("/monitoring/failures").json()["categories"]

    assert {"category": "SQL execution error", "count": 2} in categories
    assert {"category": "LLM backend error", "count": 1} in categories
    assert sum(c["count"] for c in categories) == 3


def test_traces_endpoint_orders_newest_first_and_paginates(client, telemetry_db):
    jsonl_path, db_path = telemetry_db
    _write_jsonl(
        jsonl_path,
        [
            _trace("q1", timestamp="2026-08-01T00:00:00+00:00"),
            _trace("q2", timestamp="2026-08-02T00:00:00+00:00"),
            _trace("q3", timestamp="2026-08-03T00:00:00+00:00"),
        ],
    )
    run_pipeline(jsonl_path=jsonl_path, db_path=db_path)

    body = client.get("/monitoring/traces", params={"limit": 2}).json()

    assert body["total"] == 3
    assert [t["query_id"] for t in body["traces"]] == ["q3", "q2"]


def test_refresh_calls_the_dlt_pipeline(client, monkeypatch):
    calls = []
    monkeypatch.setattr(monitoring, "run_pipeline", lambda: calls.append(True))

    response = client.post("/monitoring/refresh")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert calls == [True]
