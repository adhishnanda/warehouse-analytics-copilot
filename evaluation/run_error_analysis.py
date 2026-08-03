"""Concrete evidence for the error analysis write-up
(evaluation/results/error_analysis.md).

Re-runs, through the full production agent loop (src/agent/loop.py,
gpt-4o-mini + schema-grounded context), the exact question IDs that
failed in Day 12's self-correction evaluation
(evaluation/results/self_correction_eval.md — see SESSION_LOG.md, Day
12, for the console output these IDs were read from), capturing every
attempt's generated SQL, execution error, and validate_result reasoning.

Targeted rather than a full fresh 50-question sweep: Day 12 already
identified which specific questions failed, so this captures *why* with
minimal additional paid calls (7 questions, up to MAX_ATTEMPTS each)
instead of re-running everything at full cost.

Combined with evaluation/results/ablation_outcomes.json (which already
has full generated SQL for the Tier-3 ablation's retrieval-disabled
failures), this is the evidence base for error_analysis.md — every
category and example cited there traces back to one of these two files.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.run_llm_eval import load_golden_questions  # noqa: E402
from evaluation.run_self_correction_eval import make_openai_chat_fn  # noqa: E402
from src.agent.loop import MAX_ATTEMPTS, answer_question  # noqa: E402
from src.config import REPO_ROOT  # noqa: E402
from src.db.duckdb_client import get_connection  # noqa: E402
from src.retrieval.reranker import Reranker  # noqa: E402
from src.retrieval.retriever import Retriever  # noqa: E402

TRACES_PATH = REPO_ROOT / "evaluation" / "results" / "error_analysis_traces.json"

# From Day 12's self-correction evaluation console output (gpt-4o-mini,
# schema-grounded, production config) — see SESSION_LOG.md, Day 12.
KNOWN_FAILING_IDS = ["t1_11", "t2_01", "t2_02", "t2_07", "t2_11", "t2_13", "t2_14"]


def build_trace(q: dict, response) -> dict:
    return {
        "question_id": q["id"],
        "tier": q["tier"],
        "question": q["question"],
        "reference_result": q["reference_result"],
        "attempts": [
            {
                "sql": a.sql,
                "error": a.error,
                "valid": a.valid,
                "validation_reason": a.validation_reason,
                "result_rows": a.result.rows if a.result else None,
            }
            for a in response.attempts
        ],
        "final_sql": response.final_sql,
        "final_result_rows": response.final_result.rows if response.final_result else None,
        "succeeded_per_validate_result": response.succeeded,
    }


def main() -> None:
    questions = {q["id"]: q for q in load_golden_questions()}
    con = get_connection()
    retriever = Retriever()
    reranker = Reranker()
    chat_fn, usage_log = make_openai_chat_fn()

    traces = []
    for qid in KNOWN_FAILING_IDS:
        q = questions[qid]
        response = answer_question(
            q["question"], con, retriever, reranker, max_attempts=MAX_ATTEMPTS, chat_fn=chat_fn
        )
        trace = build_trace(q, response)
        traces.append(trace)
        print(f"[{qid}] attempts={len(response.attempts)} succeeded(validate_result)={response.succeeded}")

    TRACES_PATH.write_text(json.dumps(traces, indent=2, default=str), encoding="utf-8")
    total_tokens = sum(u.get("total_tokens", 0) for u in usage_log)
    print(f"\nWrote {len(traces)} traces to {TRACES_PATH}")
    print(f"Total OpenAI tokens: {total_tokens}")


if __name__ == "__main__":
    main()
