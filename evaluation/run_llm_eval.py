"""LLM evaluation: 2 models x 2 prompt strategies, execution accuracy.

Models: local Ollama llama3 (free, zero quota risk) and OpenAI gpt-4o-mini
(paid — flagged before use per CLAUDE.md rule 5; cost is tracked from real
API usage, not estimated). Originally used Groq's hosted llama-3.3-70b-versatile
for the free-tier arm; switched to local Ollama after Groq's free-tier daily
token quota (100K/day) was exhausted mid-evaluation by repeated runs during
development — local Ollama has no such external quota to exhaust, and this
also matches PROJECT_PLAN.md Section 5.5's framing more directly ("Development:
Groq free tier and/or local Ollama... Final evaluation runs: one small paid
model").

Prompts:
- baseline: raw DuckDB schema dump (table/column names and types only, no
  descriptions, joins, caveats, or metric definitions) — what a naive
  text-to-SQL system would see without a governed semantic layer.
- schema-grounded: the retrieved semantic layer context (Days 3-5's
  search_schema: rewrite -> hybrid search -> rerank), the same context the
  production agent loop uses.

Execution accuracy: generated SQL is run under the same guardrails as
production, and its result is compared against the golden set's recorded
reference_result as an order-insensitive multiset (most of the golden
SQL's ORDER BY is for readability, not semantically required by the
question) — a guardrail violation, execution error, or non-matching
result all count as incorrect.
"""

from __future__ import annotations

import datetime
import decimal
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.guardrails import GuardrailViolation, QueryTimeoutError, run_guarded_query  # noqa: E402
from src.agent.loop import _extract_sql  # noqa: E402
from src.agent.tools import search_schema  # noqa: E402
from src.config import REPO_ROOT  # noqa: E402
from src.db.duckdb_client import get_connection  # noqa: E402
from src.llm_client import ApiUnavailableError, ChatCompletion, OllamaUnavailableError, chat_openai, chat_with_usage  # noqa: E402
from src.retrieval.reranker import Reranker  # noqa: E402
from src.retrieval.retriever import Retriever  # noqa: E402

import duckdb  # noqa: E402

GOLDEN_PATH = REPO_ROOT / "evaluation" / "golden_questions.jsonl"
RESULTS_PATH = REPO_ROOT / "evaluation" / "results" / "llm_eval.md"

RAW_SCHEMA_TABLES = ["fact_orders", "dim_customer", "dim_product", "dim_date", "dim_region", "dim_supplier"]

BASELINE_PROMPT = (
    "You are a SQL generation system for a DuckDB analytics warehouse. "
    "Given a business question and the raw database schema below (table "
    "and column names and types only, no further documentation), write a "
    "single DuckDB SELECT statement (or WITH ... SELECT) that answers the "
    "question. Output only the SQL statement, inside a single ```sql code "
    "block, with no other explanation."
)

SCHEMA_GROUNDED_PROMPT = (
    "You are a SQL generation system for a DuckDB analytics warehouse. You "
    "are given a business question and documentation retrieved from a "
    "governed semantic layer for the tables and metrics relevant to it. "
    "Write a single DuckDB SELECT statement (or WITH ... SELECT) that "
    "answers the question, using only the tables, columns, and metric "
    "formulas described in the provided context. Never invent a table or "
    "column name that is not in the context. Output only the SQL "
    "statement, inside a single ```sql code block, with no other "
    "explanation."
)


def load_golden_questions() -> list[dict]:
    with open(GOLDEN_PATH, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def raw_schema_dump(con: duckdb.DuckDBPyConnection) -> str:
    lines = []
    for table in RAW_SCHEMA_TABLES:
        columns = con.execute(f"PRAGMA table_info('{table}')").fetchall()
        col_desc = ", ".join(f"{c[1]} {c[2]}" for c in columns)
        lines.append(f"{table}({col_desc})")
    return "\n".join(lines)


def schema_grounded_context(question: str, retriever: Retriever, reranker: Reranker) -> str:
    chunks = search_schema(question, retriever, reranker)
    return "\n\n".join(c["text"] for c in chunks)


def _normalize(value):
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value


def results_match(actual_rows: list[tuple], expected_rows: list[list]) -> bool:
    def _key(rows):
        return sorted(tuple(_normalize(v) for v in row) for row in rows)

    return _key(actual_rows) == _key([tuple(r) for r in expected_rows])


@dataclass
class QuestionOutcome:
    question_id: str
    tier: int
    sql: str
    correct: bool
    error: str | None
    usage: dict = field(default_factory=dict)


def generate_sql(chat_fn, system_prompt: str, context: str, question: str) -> tuple[str, dict]:
    user_content = f"Question: {question}\n\nContext:\n{context}"
    completion: ChatCompletion = chat_fn(system_prompt, user_content)
    return _extract_sql(completion.content), completion.usage


def _parse_retry_after_seconds(error_message: str) -> float:
    match = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", error_message)
    if not match:
        return 30.0
    minutes = float(match.group(1) or 0)
    seconds = float(match.group(2))
    return minutes * 60 + seconds


def generate_sql_with_retry(
    chat_fn, system_prompt: str, context: str, question: str, max_retries: int = 3
) -> tuple[str, dict]:
    """Like generate_sql, but retries on a rate-limit (429) response rather
    than letting a transient quota hit get scored as a wrong answer — a
    real bug in an earlier run of this script silently mis-scored 31 of 50
    questions this way (see evaluation/results/llm_eval.md methodology notes).
    Only hosted-API 429s are retried; a local Ollama failure has no rate
    limit to wait out, so it's re-raised immediately.
    """
    for attempt in range(max_retries + 1):
        try:
            return generate_sql(chat_fn, system_prompt, context, question)
        except ApiUnavailableError as exc:
            if "429" not in str(exc) or attempt == max_retries:
                raise
            wait_seconds = min(_parse_retry_after_seconds(str(exc)), 900.0) + 2.0
            print(f"    rate limited, waiting {wait_seconds:.0f}s (retry {attempt + 1}/{max_retries})...")
            time.sleep(wait_seconds)
    raise AssertionError("unreachable")  # loop always returns or raises


def run_combination(
    model_name: str,
    chat_fn,
    prompt_name: str,
    system_prompt: str,
    context_for: callable,
    questions: list[dict],
    con: duckdb.DuckDBPyConnection,
) -> list[QuestionOutcome]:
    outcomes = []
    for q in questions:
        context = context_for(q)
        try:
            sql, usage = generate_sql_with_retry(chat_fn, system_prompt, context, q["question"])
        except (ApiUnavailableError, OllamaUnavailableError) as exc:
            outcomes.append(QuestionOutcome(q["id"], q["tier"], "", False, f"API error: {exc}"))
            print(f"  [{model_name}/{prompt_name}] {q['id']}: FAIL (API error)")
            continue

        try:
            result = run_guarded_query(con, sql)
            correct = results_match(result.rows, q["reference_result"])
            error = None if correct else "result mismatch"
        except (GuardrailViolation, QueryTimeoutError, duckdb.Error) as exc:
            correct = False
            error = str(exc)

        outcomes.append(QuestionOutcome(q["id"], q["tier"], sql, correct, error, usage))
        print(f"  [{model_name}/{prompt_name}] {q['id']}: {'OK' if correct else 'FAIL'}")
    return outcomes


def summarize(outcomes: list[QuestionOutcome]) -> dict:
    per_tier = {1: [], 2: [], 3: []}
    for o in outcomes:
        per_tier[o.tier].append(o.correct)
    total_tokens = sum(o.usage.get("total_tokens", 0) for o in outcomes)
    api_error_count = sum(1 for o in outcomes if o.error and o.error.startswith("API error"))
    return {
        "accuracy": sum(o.correct for o in outcomes) / len(outcomes),
        "per_tier_accuracy": {t: (sum(v) / len(v) if v else 0.0) for t, v in per_tier.items()},
        "total_tokens": total_tokens,
        "api_error_count": api_error_count,
    }


def write_report(all_results: list[dict], winner: dict, num_questions: int) -> None:
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# LLM evaluation",
        "",
        f"Evaluated against all {num_questions} golden questions. Execution "
        "accuracy: generated SQL is run under the production guardrails and "
        "compared to the golden reference result as an order-insensitive "
        "row set. A guardrail violation, execution/API error, or mismatched "
        "result all count as incorrect. Models: local Ollama `llama3` "
        "(free) and OpenAI `gpt-4o-mini` (paid). Prompts: baseline (raw "
        "schema dump only) vs schema-grounded (retrieved semantic layer "
        "context, via the same search_schema pipeline the production agent "
        "uses).",
        "",
        "| Model | Prompt | Execution accuracy |",
        "|---|---|---|",
    ]
    for r in all_results:
        lines.append(f"| {r['model']} | {r['prompt']} | {r['accuracy']:.3f} |")

    lines += [
        "",
        f"Best approach used in production: **{winner['model']} / {winner['prompt']}**",
        "",
        "## Methodology notes",
        "",
        "The free-tier model was originally Groq's hosted `llama-3.3-70b-versatile`. "
        "Mid-evaluation, Groq's free-tier daily token quota (100K/day) was "
        "exhausted by repeated runs during development, which silently "
        "mis-scored 31 of 50 questions as wrong in one run (a missing print "
        "statement on the API-error path masked that every one of those was "
        "actually an HTTP 429 rate-limit response, not a real model "
        "failure — fixed, and covered by tests/test_run_llm_eval.py's retry "
        "tests). Rather than keep fighting an external quota, the free-tier "
        "arm was switched to local Ollama `llama3`, which has no external "
        "rate limit to exhaust and matches PROJECT_PLAN.md Section 5.5's "
        "framing directly (\"Development: Groq free tier and/or local "
        "Ollama... Final evaluation runs: one small paid model\"). The "
        "numbers above are the clean post-switch measurement.",
        "",
    ]

    total_api_errors = sum(r["api_error_count"] for r in all_results)
    if total_api_errors:
        total_calls = num_questions * len(all_results)
        lines.append(
            f"{total_api_errors} of {total_calls} calls in this run hit a "
            "transient API/connection error (counted as incorrect per the "
            "methodology above, not excluded or retried indefinitely)."
        )
        lines.append("")

    lines += [
        "## By tier",
        "",
        "| Model | Prompt | Tier 1 | Tier 2 | Tier 3 |",
        "|---|---|---|---|---|",
    ]
    for r in all_results:
        t = r["per_tier_accuracy"]
        lines.append(f"| {r['model']} | {r['prompt']} | {t[1]:.3f} | {t[2]:.3f} | {t[3]:.3f} |")

    openai_tokens = sum(r["total_tokens"] for r in all_results if r["model"] == "gpt-4o-mini")
    lines += [
        "",
        "## Cost",
        "",
        f"Total OpenAI (`gpt-4o-mini`) tokens across both prompt runs: "
        f"{openai_tokens:,} (prompt + completion, from real API usage "
        "figures, not estimated). Local Ollama has no billable usage.",
    ]

    RESULTS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    questions = load_golden_questions()
    con = get_connection()
    retriever = Retriever()
    reranker = Reranker()

    schema_text = raw_schema_dump(con)

    def baseline_context(_q: dict) -> str:
        return schema_text

    def grounded_context(q: dict) -> str:
        return schema_grounded_context(q["question"], retriever, reranker)

    combinations = [
        ("llama3", chat_with_usage, "baseline", BASELINE_PROMPT, baseline_context),
        ("llama3", chat_with_usage, "schema-grounded", SCHEMA_GROUNDED_PROMPT, grounded_context),
        ("gpt-4o-mini", chat_openai, "baseline", BASELINE_PROMPT, baseline_context),
        ("gpt-4o-mini", chat_openai, "schema-grounded", SCHEMA_GROUNDED_PROMPT, grounded_context),
    ]

    all_results = []
    for model_name, chat_fn, prompt_name, system_prompt, context_for in combinations:
        print(f"=== {model_name} / {prompt_name} ===")
        start = time.perf_counter()
        outcomes = run_combination(model_name, chat_fn, prompt_name, system_prompt, context_for, questions, con)
        elapsed = time.perf_counter() - start
        summary = summarize(outcomes)
        summary["model"] = model_name
        summary["prompt"] = prompt_name
        all_results.append(summary)
        print(f"{model_name}/{prompt_name}: accuracy={summary['accuracy']:.3f}  ({elapsed:.1f}s)")

    winner = max(all_results, key=lambda r: r["accuracy"])
    write_report(all_results, winner, len(questions))

    print("\nSummary:")
    for r in all_results:
        print(f"  {r['model']:25s} {r['prompt']:16s} accuracy={r['accuracy']:.3f}")
    print(f"\nWinner: {winner['model']} / {winner['prompt']}")


if __name__ == "__main__":
    main()
