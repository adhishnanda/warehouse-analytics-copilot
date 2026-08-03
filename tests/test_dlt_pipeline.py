"""Tests for the dlt telemetry pipeline. Runs against a temp JSONL and a
temp DuckDB file (never the real data/telemetry/traces.jsonl or
telemetry.duckdb) so tests never depend on or mutate live app data.
"""

import json
import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.telemetry.dlt_pipeline import DATASET_NAME, run_pipeline


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
        "latency_seconds": 1.5,
        "model": "llama3",
        "usage": {"total_tokens": 42},
    }
    record.update(overrides)
    return record


def _feedback(query_id: str, vote: str, timestamp: str = "2026-08-03T00:00:05+00:00") -> dict:
    return {"event_type": "feedback", "query_id": query_id, "timestamp": timestamp, "vote": vote}


@pytest.fixture
def paths(tmp_path):
    return tmp_path / "traces.jsonl", tmp_path / "telemetry.duckdb"


def test_loads_trace_and_feedback_into_separate_tables(paths):
    jsonl_path, db_path = paths
    _write_jsonl(jsonl_path, [_trace("q1"), _feedback("q1", "up")])

    run_pipeline(jsonl_path=jsonl_path, db_path=db_path)

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        traces = con.execute(f"SELECT query_id, question, succeeded FROM {DATASET_NAME}.traces").fetchall()
        feedback = con.execute(f"SELECT query_id, vote FROM {DATASET_NAME}.feedback").fetchall()
    finally:
        con.close()

    assert traces == [("q1", "how many orders", True)]
    assert feedback == [("q1", "up")]


def test_flattens_nested_usage_dict(paths):
    jsonl_path, db_path = paths
    _write_jsonl(jsonl_path, [_trace("q1", usage={"total_tokens": 99})])

    run_pipeline(jsonl_path=jsonl_path, db_path=db_path)

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        result = con.execute(f"SELECT usage__total_tokens FROM {DATASET_NAME}.traces").fetchall()
    finally:
        con.close()

    assert result == [(99,)]


def test_rerun_on_unchanged_file_does_not_duplicate_rows(paths):
    jsonl_path, db_path = paths
    _write_jsonl(jsonl_path, [_trace("q1")])

    run_pipeline(jsonl_path=jsonl_path, db_path=db_path)
    run_pipeline(jsonl_path=jsonl_path, db_path=db_path)

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        count = con.execute(f"SELECT COUNT(*) FROM {DATASET_NAME}.traces").fetchone()[0]
    finally:
        con.close()

    assert count == 1


def test_rerun_after_appending_a_new_event_adds_exactly_one_row(paths):
    jsonl_path, db_path = paths
    _write_jsonl(jsonl_path, [_trace("q1")])
    run_pipeline(jsonl_path=jsonl_path, db_path=db_path)

    with open(jsonl_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(_trace("q2", succeeded=False, error="binder error")) + "\n")
    run_pipeline(jsonl_path=jsonl_path, db_path=db_path)

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = con.execute(f"SELECT query_id, succeeded, error FROM {DATASET_NAME}.traces ORDER BY query_id").fetchall()
    finally:
        con.close()

    assert rows == [("q1", True, None), ("q2", False, "binder error")]


def test_a_second_feedback_event_for_the_same_query_overwrites_the_first(paths):
    """Merge write_disposition means 'latest vote wins' if a query_id is
    somehow voted on twice (the UI disables re-voting, but the API
    itself doesn't enforce that)."""
    jsonl_path, db_path = paths
    _write_jsonl(
        jsonl_path,
        [
            _trace("q1"),
            _feedback("q1", "up", timestamp="2026-08-03T00:00:05+00:00"),
            _feedback("q1", "down", timestamp="2026-08-03T00:00:10+00:00"),
        ],
    )

    run_pipeline(jsonl_path=jsonl_path, db_path=db_path)

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = con.execute(f"SELECT query_id, vote FROM {DATASET_NAME}.feedback").fetchall()
    finally:
        con.close()

    assert rows == [("q1", "down")]


def test_missing_jsonl_file_runs_without_erroring(paths):
    jsonl_path, db_path = paths  # jsonl_path never created

    run_pipeline(jsonl_path=jsonl_path, db_path=db_path)

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        tables = {row[0] for row in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    finally:
        con.close()

    # No source data means dlt has nothing to infer a schema from, so it
    # creates only its own bookkeeping tables, not traces/feedback.
    assert "traces" not in tables
    assert "feedback" not in tables
