"""Generates a daily batch of synthetic traffic through the real agent
loop, so the monitoring dashboard has ongoing activity between real
sessions instead of sitting empty. Every trace is a genuine agent
execution against the real warehouse (the same production code path
POST /ask uses) - only the choice of which questions to ask (sampled
from evaluation/golden_questions.jsonl) and whether to leave feedback
on each one is scripted. This is the same approach Day 18 used to seed
the original demo telemetry (see SESSION_LOG.md), now automated so it
runs on its own rather than needing a manual session.

Always uses the free local Ollama backend and never opts into a paid
model on its own, per the project's cost-discipline rule.

Usage: uv run python scripts/generate_synthetic_traffic.py [count]
"""

from __future__ import annotations

import json
import random
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.loop import answer_question  # noqa: E402
from src.config import OLLAMA_MODEL, REPO_ROOT, TRACE_LOG_PATH  # noqa: E402
from src.db.duckdb_client import get_connection  # noqa: E402
from src.llm_client import ChatCompletion, chat_with_usage  # noqa: E402
from src.retrieval.reranker import Reranker  # noqa: E402
from src.retrieval.retriever import Retriever  # noqa: E402
from src.telemetry.logger import log_feedback, log_trace  # noqa: E402

GOLDEN_PATH = REPO_ROOT / "evaluation" / "golden_questions.jsonl"
DEFAULT_COUNT = 12

# Deliberately noisy, not a perfect oracle - validate_result's own
# plausibility check is itself only a heuristic (see
# evaluation/results/error_analysis.md), so a real system's feedback
# would never be 100% consistent with success/failure either. Weights
# chosen to land in the same rough range Day 18's hand-picked demo
# telemetry showed (7 up / 2 down on 20 traces): mostly "up" on success,
# mostly "down" on failure, a slice going the other way or unvoted.
FEEDBACK_ON_SUCCESS = {"up": 0.7, "down": 0.05}
FEEDBACK_ON_FAILURE = {"down": 0.5, "up": 0.05}


def load_questions() -> list[str]:
    questions = []
    with open(GOLDEN_PATH, encoding="utf-8") as f:
        for line in f:
            questions.append(json.loads(line)["question"])
    return questions


def simulate_feedback(query_id: str, succeeded: bool, rng: random.Random) -> str | None:
    """Logs a simulated thumbs up/down for this trace and returns the vote
    cast, or None if this trace gets no vote at all (matching how not
    every real query gets feedback either).
    """
    outcomes = FEEDBACK_ON_SUCCESS if succeeded else FEEDBACK_ON_FAILURE
    roll = rng.random()
    cumulative = 0.0
    for vote, probability in outcomes.items():
        cumulative += probability
        if roll < cumulative:
            log_feedback(query_id, vote, path=TRACE_LOG_PATH)
            return vote
    return None


def generate_one(question: str, con, retriever, reranker, rng: random.Random) -> dict:
    """Runs one question through the real agent loop, logs a trace and a
    simulated feedback vote, and returns a small summary record.
    """
    usage_records: list[dict] = []

    def chat_fn(system_prompt: str, user_content: str, _records=usage_records) -> str:
        completion: ChatCompletion = chat_with_usage(system_prompt, user_content)
        _records.append(completion.usage)
        return completion.content

    start = time.perf_counter()
    response = answer_question(question, con, retriever, reranker, chat_fn=chat_fn)
    latency = time.perf_counter() - start

    last_attempt = response.attempts[-1] if response.attempts else None
    error = None
    if not response.succeeded:
        error = (last_attempt.error or last_attempt.validation_reason) if last_attempt else "no attempts made"
    usage = (
        {
            "prompt_tokens": sum(u.get("prompt_tokens", 0) for u in usage_records),
            "completion_tokens": sum(u.get("completion_tokens", 0) for u in usage_records),
            "total_tokens": sum(u.get("total_tokens", 0) for u in usage_records),
        }
        if usage_records
        else {}
    )

    query_id = str(uuid.uuid4())
    log_trace(
        query_id=query_id,
        question=question,
        sql=response.final_sql,
        succeeded=response.succeeded,
        error=error,
        attempt_count=len(response.attempts),
        row_count=response.final_result.row_count if response.final_result else None,
        latency_seconds=latency,
        model=OLLAMA_MODEL,
        usage=usage,
        path=TRACE_LOG_PATH,
    )
    vote = simulate_feedback(query_id, response.succeeded, rng)
    return {"question": question, "query_id": query_id, "succeeded": response.succeeded, "vote": vote}


def run(count: int = DEFAULT_COUNT, seed: int | None = None) -> list[dict]:
    rng = random.Random(seed)
    questions = load_questions()
    sample = rng.sample(questions, min(count, len(questions)))

    con = get_connection()
    retriever = Retriever()
    reranker = Reranker()
    try:
        results = []
        for question in sample:
            record = generate_one(question, con, retriever, reranker, rng)
            status = "succeeded" if record["succeeded"] else "failed"
            print(f"[{status}] {question!r} (feedback: {record['vote'] or 'none'})")
            results.append(record)
        return results
    finally:
        con.close()


if __name__ == "__main__":
    requested = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_COUNT
    outcomes = run(requested)
    print(f"Generated {len(outcomes)} synthetic traces")
