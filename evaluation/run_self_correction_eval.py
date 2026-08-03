"""Self-correction lift (PROJECT_PLAN.md Section 7.4): does the agent's
validate-and-retry loop actually improve execution accuracy over a
single-shot attempt?

Uses the Day 11 production winner (OpenAI `gpt-4o-mini`, schema-grounded
context via search_schema) so the number reported here describes the
system as it will actually run, not an arbitrary comparison config.

Design: rather than running two independent full passes (single-shot vs
retry-enabled) — which would double the paid API calls and introduce
sampling noise between the two arms' first attempts — each of the 50
golden questions is run exactly once through answer_question with
max_attempts=2 (the production default). Both arms are then read off the
same run:

- single-shot accuracy: was attempts[0]'s result correct?
- retry-enabled accuracy: was the loop's final result correct?

This is an apples-to-apples comparison (identical first attempt in both
arms) and it directly measures the loop's real behaviour: attempt 2 only
ever runs when validate_result (a heuristic, not an oracle) judged
attempt 1 implausible. So the measured lift is bounded by how often that
heuristic actually catches a wrong answer — a real limitation, not a
knob to tune, and it's disclosed in the report.

Correctness is judged the same way as Day 11's LLM evaluation: an
order-insensitive comparison of the executed result rows against the
golden set's reference_result (not validate_result's plausibility check,
which is what decides retries but is not itself a correctness oracle).
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.run_llm_eval import _parse_retry_after_seconds, results_match  # noqa: E402
from src.agent.loop import MAX_ATTEMPTS, answer_question  # noqa: E402
from src.config import REPO_ROOT  # noqa: E402
from src.db.duckdb_client import get_connection  # noqa: E402
from src.llm_client import ApiUnavailableError, chat_openai  # noqa: E402
from src.retrieval.reranker import Reranker  # noqa: E402
from src.retrieval.retriever import Retriever  # noqa: E402

GOLDEN_PATH = REPO_ROOT / "evaluation" / "golden_questions.jsonl"
RESULTS_PATH = REPO_ROOT / "evaluation" / "results" / "self_correction_eval.md"


def load_golden_questions() -> list[dict]:
    with open(GOLDEN_PATH, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def make_openai_chat_fn(max_retries: int = 3):
    """Wraps chat_openai to match the str-returning chat_fn contract
    src/agent/loop.py expects, with 429 backoff (same approach as Day 11's
    generate_sql_with_retry) and a usage log for cost disclosure.
    """
    usage_log: list[dict] = []

    def chat_fn(system_prompt: str, user_content: str) -> str:
        for attempt in range(max_retries + 1):
            try:
                completion = chat_openai(system_prompt, user_content)
                usage_log.append(completion.usage)
                return completion.content
            except ApiUnavailableError as exc:
                if "429" not in str(exc) or attempt == max_retries:
                    raise
                wait_seconds = min(_parse_retry_after_seconds(str(exc)), 900.0) + 2.0
                print(f"    rate limited, waiting {wait_seconds:.0f}s (retry {attempt + 1}/{max_retries})...")
                time.sleep(wait_seconds)
        raise AssertionError("unreachable")  # loop always returns or raises

    return chat_fn, usage_log


@dataclass
class QuestionOutcome:
    question_id: str
    tier: int
    single_shot_correct: bool
    retry_correct: bool
    retried: bool
    rescued: bool
    regressed: bool
    attempt_count: int
    final_error: str | None = None


def evaluate_question(q: dict, con, retriever, reranker, chat_fn) -> QuestionOutcome:
    response = answer_question(
        q["question"], con, retriever, reranker, max_attempts=MAX_ATTEMPTS, chat_fn=chat_fn
    )
    first = response.attempts[0] if response.attempts else None
    single_shot_correct = bool(first and first.result and results_match(first.result.rows, q["reference_result"]))
    retry_correct = bool(
        response.final_result and results_match(response.final_result.rows, q["reference_result"])
    )
    retried = len(response.attempts) > 1
    rescued = retried and not single_shot_correct and retry_correct
    regressed = retried and single_shot_correct and not retry_correct
    last = response.attempts[-1] if response.attempts else None
    return QuestionOutcome(
        question_id=q["id"],
        tier=q["tier"],
        single_shot_correct=single_shot_correct,
        retry_correct=retry_correct,
        retried=retried,
        rescued=rescued,
        regressed=regressed,
        attempt_count=len(response.attempts),
        final_error=last.error if last else None,
    )


def summarize(outcomes: list[QuestionOutcome]) -> dict:
    per_tier_single = {1: [], 2: [], 3: []}
    per_tier_retry = {1: [], 2: [], 3: []}
    for o in outcomes:
        per_tier_single[o.tier].append(o.single_shot_correct)
        per_tier_retry[o.tier].append(o.retry_correct)

    return {
        "single_shot_accuracy": sum(o.single_shot_correct for o in outcomes) / len(outcomes),
        "retry_accuracy": sum(o.retry_correct for o in outcomes) / len(outcomes),
        "per_tier_single": {t: (sum(v) / len(v) if v else 0.0) for t, v in per_tier_single.items()},
        "per_tier_retry": {t: (sum(v) / len(v) if v else 0.0) for t, v in per_tier_retry.items()},
        "retried_count": sum(o.retried for o in outcomes),
        "rescued_count": sum(o.rescued for o in outcomes),
        "regressed_count": sum(o.regressed for o in outcomes),
    }


def write_report(outcomes: list[QuestionOutcome], summary: dict, total_tokens: int) -> None:
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    delta = summary["retry_accuracy"] - summary["single_shot_accuracy"]
    lines = [
        "# Self-correction lift",
        "",
        "Measures whether the validate-and-retry loop (up to "
        f"{MAX_ATTEMPTS} attempts, `src/agent/loop.py`) improves execution "
        "accuracy over a single-shot attempt, against all 50 golden "
        "questions, using the Day 11 production winner: OpenAI "
        "`gpt-4o-mini` with schema-grounded context. Each question is run "
        "once through the full loop; single-shot accuracy is read from the "
        "first attempt's result, and retry-enabled accuracy from the "
        "loop's final result — an apples-to-apples comparison, since both "
        "arms share the same first attempt rather than being sampled "
        "independently.",
        "",
        "| Condition | Execution accuracy |",
        "|---|---|",
        f"| Single-shot (no retry) | {summary['single_shot_accuracy']:.3f} |",
        f"| Retry-enabled (max {MAX_ATTEMPTS} attempts) | {summary['retry_accuracy']:.3f} |",
        "",
        f"Accuracy delta from enabling retry: **{delta:+.3f}**",
        "",
        "## By tier",
        "",
        "| Tier | Single-shot | Retry-enabled |",
        "|---|---|---|",
    ]
    for t in (1, 2, 3):
        lines.append(f"| {t} | {summary['per_tier_single'][t]:.3f} | {summary['per_tier_retry'][t]:.3f} |")

    lines += [
        "",
        "## Retry behaviour",
        "",
        f"Retry was triggered (attempt 1 judged implausible by "
        f"`validate_result`) on {summary['retried_count']} of "
        f"{len(outcomes)} questions.",
        f"- Rescued (wrong on attempt 1, correct after retry): {summary['rescued_count']}",
        f"- Regressed (correct on attempt 1, wrong after retry): {summary['regressed_count']}",
        "",
        "`validate_result` is a heuristic plausibility check (empty/NULL "
        "results, out-of-range rate values), not a correctness oracle "
        "against the golden reference — so retry only ever fires when that "
        "heuristic happens to catch a problem. An attempt that is "
        "confidently wrong in a way the heuristic can't detect (e.g. a "
        "plausible-looking but incorrect join) never gets a second try, "
        "which bounds how much lift this loop can produce by construction, "
        "not by chance.",
        "",
        "## Cost",
        "",
        f"Total OpenAI (`gpt-4o-mini`) tokens across this evaluation: "
        f"{total_tokens:,} (prompt + completion, from real API usage "
        "figures, not estimated).",
    ]

    RESULTS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    questions = load_golden_questions()
    con = get_connection()
    retriever = Retriever()
    reranker = Reranker()
    chat_fn, usage_log = make_openai_chat_fn()

    outcomes = []
    for q in questions:
        outcome = evaluate_question(q, con, retriever, reranker, chat_fn)
        outcomes.append(outcome)
        tag = "OK" if outcome.retry_correct else "FAIL"
        note = " (retried)" if outcome.retried else ""
        print(f"  [{q['id']}] {tag}{note}")

    summary = summarize(outcomes)
    total_tokens = sum(u.get("total_tokens", 0) for u in usage_log)
    write_report(outcomes, summary, total_tokens)

    print("\nSummary:")
    print(f"  single-shot accuracy:    {summary['single_shot_accuracy']:.3f}")
    print(f"  retry-enabled accuracy:  {summary['retry_accuracy']:.3f}")
    print(f"  delta:                   {summary['retry_accuracy'] - summary['single_shot_accuracy']:+.3f}")
    print(f"  retried: {summary['retried_count']}  rescued: {summary['rescued_count']}  regressed: {summary['regressed_count']}")


if __name__ == "__main__":
    main()
