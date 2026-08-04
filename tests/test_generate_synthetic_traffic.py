"""Tests for the daily synthetic-traffic generator's own logic (question
sampling, feedback simulation, trace-logging shape) - not a live run
against Ollama. answer_question is monkeypatched with a canned response,
same pattern as tests/test_run_self_correction_eval.py, so nothing here
depends on a running model or the live warehouse.
"""

import random
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scripts.generate_synthetic_traffic as gst


@dataclass
class FakeResult:
    row_count: int


@dataclass
class FakeAttempt:
    sql: str
    error: str | None
    validation_reason: str


@dataclass
class FakeResponse:
    succeeded: bool
    final_sql: str | None
    final_result: object
    attempts: list


def test_load_questions_returns_the_real_golden_question_texts():
    questions = gst.load_questions()
    assert len(questions) == 50
    assert all(isinstance(q, str) and q for q in questions)


def test_simulate_feedback_logs_up_on_a_low_roll_for_a_success(monkeypatch):
    calls = []
    monkeypatch.setattr(gst, "log_feedback", lambda query_id, vote, path: calls.append((query_id, vote)))
    rng = random.Random()
    rng.random = lambda: 0.01  # well under FEEDBACK_ON_SUCCESS's "up" threshold

    vote = gst.simulate_feedback("q1", succeeded=True, rng=rng)

    assert vote == "up"
    assert calls == [("q1", "up")]


def test_simulate_feedback_returns_none_on_a_high_roll(monkeypatch):
    monkeypatch.setattr(gst, "log_feedback", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not vote")))
    rng = random.Random()
    rng.random = lambda: 0.99

    vote = gst.simulate_feedback("q1", succeeded=True, rng=rng)

    assert vote is None


def test_simulate_feedback_skews_toward_down_on_failure(monkeypatch):
    calls = []
    monkeypatch.setattr(gst, "log_feedback", lambda query_id, vote, path: calls.append((query_id, vote)))
    rng = random.Random()
    rng.random = lambda: 0.1  # under FEEDBACK_ON_FAILURE's "down" threshold, over "up"'s

    vote = gst.simulate_feedback("q1", succeeded=False, rng=rng)

    assert vote == "down"


def test_generate_one_logs_a_trace_for_a_successful_response(monkeypatch):
    fake_response = FakeResponse(
        succeeded=True,
        final_sql="SELECT COUNT(*) FROM fact_orders",
        final_result=FakeResult(row_count=1),
        attempts=[FakeAttempt(sql="SELECT COUNT(*) FROM fact_orders", error=None, validation_reason="plausible")],
    )
    monkeypatch.setattr(gst, "answer_question", lambda *a, **k: fake_response)
    monkeypatch.setattr(gst, "simulate_feedback", lambda *a, **k: "up")
    calls = []
    monkeypatch.setattr(gst, "log_trace", lambda **kwargs: calls.append(kwargs))

    record = gst.generate_one("how many orders", con=None, retriever=None, reranker=None, rng=random.Random(0))

    assert record == {
        "question": "how many orders",
        "query_id": calls[0]["query_id"],
        "succeeded": True,
        "vote": "up",
    }
    assert len(calls) == 1
    assert calls[0]["succeeded"] is True
    assert calls[0]["sql"] == "SELECT COUNT(*) FROM fact_orders"
    assert calls[0]["row_count"] == 1
    assert calls[0]["model"] == gst.OLLAMA_MODEL
    assert calls[0]["error"] is None


def test_generate_one_records_the_failure_reason_when_unsuccessful(monkeypatch):
    fake_response = FakeResponse(
        succeeded=False,
        final_sql="SELECT bad_column FROM fact_orders",
        final_result=None,
        attempts=[FakeAttempt(sql="...", error="Binder Error: column not found", validation_reason="")],
    )
    monkeypatch.setattr(gst, "answer_question", lambda *a, **k: fake_response)
    monkeypatch.setattr(gst, "simulate_feedback", lambda *a, **k: None)
    calls = []
    monkeypatch.setattr(gst, "log_trace", lambda **kwargs: calls.append(kwargs))

    record = gst.generate_one("bad question", con=None, retriever=None, reranker=None, rng=random.Random(0))

    assert record["succeeded"] is False
    assert calls[0]["succeeded"] is False
    assert calls[0]["error"] == "Binder Error: column not found"
    assert calls[0]["row_count"] is None


def test_run_samples_the_requested_count_from_the_golden_questions(monkeypatch):
    fake_response = FakeResponse(
        succeeded=True,
        final_sql="SELECT 1",
        final_result=FakeResult(row_count=1),
        attempts=[FakeAttempt(sql="SELECT 1", error=None, validation_reason="plausible")],
    )
    monkeypatch.setattr(gst, "answer_question", lambda *a, **k: fake_response)
    monkeypatch.setattr(gst, "simulate_feedback", lambda *a, **k: None)
    monkeypatch.setattr(gst, "log_trace", lambda **kwargs: None)
    class _FakeConnection:
        def close(self):
            pass

    monkeypatch.setattr(gst, "get_connection", lambda: _FakeConnection())
    monkeypatch.setattr(gst, "Retriever", lambda: None)
    monkeypatch.setattr(gst, "Reranker", lambda: None)

    all_questions = set(gst.load_questions())
    results = gst.run(count=5, seed=42)

    assert len(results) == 5
    assert len({r["query_id"] for r in results}) == 5
    assert all(r["question"] in all_questions for r in results)
