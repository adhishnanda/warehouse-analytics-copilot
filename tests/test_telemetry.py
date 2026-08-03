"""Tests for the trace/feedback JSONL logger."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.telemetry.logger import log_feedback, log_trace


@pytest.fixture
def log_path(tmp_path):
    return tmp_path / "telemetry" / "traces.jsonl"


def test_log_trace_writes_one_json_line(log_path):
    log_trace(
        query_id="q1",
        question="how many orders",
        sql="SELECT COUNT(*) FROM fact_orders",
        succeeded=True,
        error=None,
        attempt_count=1,
        row_count=1,
        latency_seconds=1.23,
        model="llama3",
        path=log_path,
    )

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["event_type"] == "trace"
    assert record["query_id"] == "q1"
    assert record["succeeded"] is True
    assert record["sql"] == "SELECT COUNT(*) FROM fact_orders"


def test_log_trace_creates_parent_directory(log_path):
    assert not log_path.parent.exists()
    log_trace(
        query_id="q1",
        question="q",
        sql=None,
        succeeded=False,
        error="backend down",
        attempt_count=1,
        row_count=None,
        latency_seconds=0.5,
        model="llama3",
        path=log_path,
    )
    assert log_path.exists()


def test_log_feedback_appends_after_trace(log_path):
    log_trace(
        query_id="q1",
        question="q",
        sql="SELECT 1",
        succeeded=True,
        error=None,
        attempt_count=1,
        row_count=1,
        latency_seconds=0.1,
        model="llama3",
        path=log_path,
    )
    log_feedback("q1", "up", path=log_path)

    lines = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    assert lines[1]["event_type"] == "feedback"
    assert lines[1]["query_id"] == "q1"
    assert lines[1]["vote"] == "up"


def test_log_feedback_rejects_invalid_vote(log_path):
    with pytest.raises(ValueError):
        log_feedback("q1", "sideways", path=log_path)


def test_log_trace_records_usage_dict(log_path):
    log_trace(
        query_id="q1",
        question="q",
        sql="SELECT 1",
        succeeded=True,
        error=None,
        attempt_count=1,
        row_count=1,
        latency_seconds=0.1,
        model="gpt-4o-mini",
        usage={"total_tokens": 42},
        path=log_path,
    )
    record = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["usage"] == {"total_tokens": 42}
