"""Tier-3 retrieval ablation (PROJECT_PLAN.md Section 7.5 — the project's
headline result): does retrieval-grounded generation specifically help
where business metric definitions matter, not just generically?

Scoped to the 10 Tier-3 golden questions (business-phrased questions
that only map to a defined metric via metrics.yml, e.g. "how much money
have we brought in altogether" -> total_revenue). Two conditions:

- retrieval disabled: baseline prompt, raw DuckDB schema dump only (no
  metric definitions, no table documentation) — what the model sees if
  the semantic layer is switched off.
- retrieval enabled: schema-grounded prompt, the real search_schema
  pipeline (rewrite -> hybrid search -> rerank).

Two models — gpt-4o-mini (the Day 11 production winner, paid) and local
llama3 (free) — so the finding isn't an artefact of one model.

This reuses the exact prompts, context builders, per-question execution/
scoring, and summary logic from evaluation/run_llm_eval.py rather than
duplicating them: it is literally the same baseline-vs-schema-grounded
comparison Day 11 already ran, scoped to Tier 3 and re-run here with its
own dedicated, standalone report (evaluation/results/ablation_eval.md)
and full per-question outcomes persisted to ablation_outcomes.json
(question, condition, model, generated SQL, correctness, error) so
evaluation/results/error_analysis.md can cite concrete, real failure
examples rather than inferred ones.
"""

from __future__ import annotations

import dataclasses
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.run_llm_eval import (  # noqa: E402
    BASELINE_PROMPT,
    SCHEMA_GROUNDED_PROMPT,
    load_golden_questions,
    raw_schema_dump,
    run_combination,
    schema_grounded_context,
    summarize,
)
from src.config import REPO_ROOT  # noqa: E402
from src.db.duckdb_client import get_connection  # noqa: E402
from src.llm_client import ChatCompletion, chat_openai, chat_with_usage  # noqa: E402
from src.retrieval.reranker import Reranker  # noqa: E402
from src.retrieval.retriever import Retriever  # noqa: E402

RESULTS_PATH = REPO_ROOT / "evaluation" / "results" / "ablation_eval.md"
OUTCOMES_PATH = REPO_ROOT / "evaluation" / "results" / "ablation_outcomes.json"

CONDITION_LABELS = {"baseline": "retrieval disabled", "schema-grounded": "retrieval enabled"}

# Day 11's full-50-question by-tier Tier-3 accuracy, for the corroboration
# check in the report (evaluation/results/llm_eval.md). A different,
# independent sample (unfixed API temperature — see
# evaluation/results/self_correction_eval.md's variance note), not a
# duplicate of this run.
DAY11_TIER3_REFERENCE = {
    ("llama3", "baseline"): 0.100,
    ("llama3", "schema-grounded"): 0.700,
    ("gpt-4o-mini", "baseline"): 0.400,
    ("gpt-4o-mini", "schema-grounded"): 1.000,
}


def load_tier3_questions() -> list[dict]:
    return [q for q in load_golden_questions() if q["tier"] == 3]


def llama3_chat_fn(system_prompt: str, user_content: str) -> ChatCompletion:
    """chat_with_usage with a longer timeout than the 30s default.

    A first run of this script saw 6 of 20 llama3 calls fail with
    OllamaUnavailableError (connection timeout), concentrated right after
    the reranker's cross-encoder model was lazily loaded — CPU contention
    between local inference and Ollama generation, not genuine model
    failures. Raised to 90s for this evaluation script only; the
    production default in src/llm_client.py is unaffected, since a live
    single-question request doesn't compete with a batch of 40 calls
    plus model loading in the same process.
    """
    return chat_with_usage(system_prompt, user_content, timeout=90.0)


def write_report(all_results: list[dict], all_outcome_records: list[dict], num_questions: int) -> None:
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Tier-3 retrieval ablation",
        "",
        f"Headline result (PROJECT_PLAN.md Section 7.5): the {num_questions} "
        "Tier-3 golden questions — business-phrased questions that only "
        "map to a correct query via a defined metric in "
        "`semantic_layer/metrics.yml` — run with retrieval disabled "
        "(raw schema dump only, no metric definitions) vs enabled (the "
        "real `search_schema` pipeline: rewrite -> hybrid search -> "
        "rerank). Execution accuracy against the golden reference result, "
        "same methodology as `evaluation/results/llm_eval.md`. Two "
        "models, so the effect isn't specific to one.",
        "",
        "| Model | Condition | Execution accuracy |",
        "|---|---|---|",
    ]
    for r in all_results:
        lines.append(f"| {r['model']} | {CONDITION_LABELS[r['prompt']]} | {r['accuracy']:.3f} |")

    lines += [
        "",
        "## Methodology note",
        "",
        "A first run of this script used the default 30s Ollama timeout "
        "and saw 6 of 20 `llama3` calls fail with a connection timeout "
        "(not a real model failure), concentrated right after the "
        "reranker's cross-encoder model was lazily loaded — CPU "
        "contention between local inference and Ollama generation in the "
        "same process. Diagnosed rather than reported as-is: the "
        "`llama3` timeout was raised to 90s for this script only (see "
        "`llama3_chat_fn` in `run_ablation.py`; the production default in "
        "`src/llm_client.py` is unaffected). The run below is the "
        "re-measurement at 90s.",
    ]
    llama3_api_errors = sum(
        1 for r in all_results if r["model"] == "llama3" and r.get("api_error_count", 0)
    )
    if llama3_api_errors:
        total_llama3_errors = sum(
            r.get("api_error_count", 0) for r in all_results if r["model"] == "llama3"
        )
        lines.append(
            f"Even at 90s, {total_llama3_errors} of 20 `llama3` calls in this "
            "run still hit a connection timeout — reduced from 6 but not "
            "eliminated. Counted as incorrect per the same methodology as "
            "Day 11 (a guardrail violation, execution/API error, or "
            "mismatched result all count as incorrect), not excluded."
        )

    lines += ["", "## Corroboration against Day 11", ""]
    lines.append(
        "Day 11's LLM evaluation (`evaluation/results/llm_eval.md`) already "
        "measured baseline vs schema-grounded accuracy on these same 10 "
        "questions as part of its by-tier breakdown, from an independent "
        "run (unfixed API temperature, so not expected to match exactly — "
        "see the variance note in `evaluation/results/"
        "self_correction_eval.md`). Comparison:"
    )
    lines += ["", "| Model | Condition | This run | Day 11 |", "|---|---|---|---|"]
    for r in all_results:
        day11 = DAY11_TIER3_REFERENCE.get((r["model"], r["prompt"]))
        day11_str = f"{day11:.3f}" if day11 is not None else "n/a"
        lines.append(f"| {r['model']} | {CONDITION_LABELS[r['prompt']]} | {r['accuracy']:.3f} | {day11_str} |")

    total_openai_tokens = sum(r["total_tokens"] for r in all_results if r["model"] == "gpt-4o-mini")
    lines += [
        "",
        "## Cost",
        "",
        f"Total OpenAI (`gpt-4o-mini`) tokens across this ablation: "
        f"{total_openai_tokens:,} (prompt + completion, from real API "
        "usage figures, not estimated). Local Ollama has no billable "
        "usage.",
        "",
        "Full per-question outcomes (generated SQL, correctness, errors) "
        "are in `ablation_outcomes.json`, alongside this report.",
    ]

    RESULTS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    OUTCOMES_PATH.write_text(json.dumps(all_outcome_records, indent=2), encoding="utf-8")


def main() -> None:
    questions = load_tier3_questions()
    con = get_connection()
    retriever = Retriever()
    reranker = Reranker()

    schema_text = raw_schema_dump(con)

    def baseline_context(_q: dict) -> str:
        return schema_text

    def grounded_context(q: dict) -> str:
        return schema_grounded_context(q["question"], retriever, reranker)

    combinations = [
        ("llama3", llama3_chat_fn, "baseline", BASELINE_PROMPT, baseline_context),
        ("llama3", llama3_chat_fn, "schema-grounded", SCHEMA_GROUNDED_PROMPT, grounded_context),
        ("gpt-4o-mini", chat_openai, "baseline", BASELINE_PROMPT, baseline_context),
        ("gpt-4o-mini", chat_openai, "schema-grounded", SCHEMA_GROUNDED_PROMPT, grounded_context),
    ]

    all_results = []
    all_outcome_records: list[dict] = []
    for model_name, chat_fn, prompt_name, system_prompt, context_for in combinations:
        label = CONDITION_LABELS[prompt_name]
        print(f"=== {model_name} / {label} ===")
        start = time.perf_counter()
        outcomes = run_combination(model_name, chat_fn, prompt_name, system_prompt, context_for, questions, con)
        elapsed = time.perf_counter() - start
        for o in outcomes:
            record = dataclasses.asdict(o)
            record["model"] = model_name
            record["condition"] = CONDITION_LABELS[prompt_name]
            all_outcome_records.append(record)
        summary = summarize(outcomes)
        summary["model"] = model_name
        summary["prompt"] = prompt_name
        all_results.append(summary)
        print(f"{model_name}/{label}: accuracy={summary['accuracy']:.3f}  ({elapsed:.1f}s)")

    write_report(all_results, all_outcome_records, len(questions))

    print("\nSummary:")
    for r in all_results:
        print(f"  {r['model']:15s} {CONDITION_LABELS[r['prompt']]:20s} accuracy={r['accuracy']:.3f}")


if __name__ == "__main__":
    main()
