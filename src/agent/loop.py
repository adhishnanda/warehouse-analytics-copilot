"""Agent orchestration: retrieve context, generate SQL, execute it under
guardrails, validate the result, and retry (up to 2 attempts) on failure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

import duckdb

from src.agent.guardrails import GuardrailViolation, QueryResult, QueryTimeoutError
from src.agent.tools import run_sql, search_schema, validate_result
from src.llm_client import ApiUnavailableError, OllamaUnavailableError, chat
from src.retrieval.reranker import Reranker
from src.retrieval.retriever import Retriever

MAX_ATTEMPTS = 2  # per PROJECT_PLAN.md Section 5.4

SQL_SYSTEM_PROMPT = (
    "You are the SQL generation step in a text-to-SQL system over a small "
    "DuckDB analytics warehouse. You are given a business question and "
    "documentation retrieved from a governed semantic layer for the tables "
    "and metrics relevant to it. Write a single DuckDB SELECT statement (or "
    "WITH ... SELECT) that answers the question, using only the tables, "
    "columns, and metric formulas described in the provided context. Never "
    "invent a table or column name that is not in the context. Output only "
    "the SQL statement, inside a single ```sql code block, with no other "
    "explanation."
)


class SqlGenerationError(Exception):
    """Raised when the LLM backend cannot produce a SQL candidate."""


@dataclass
class AgentAttempt:
    sql: str
    result: QueryResult | None
    error: str | None
    valid: bool
    validation_reason: str


@dataclass
class AgentResponse:
    question: str
    context: list[dict]
    attempts: list[AgentAttempt]
    final_sql: str | None
    final_result: QueryResult | None
    succeeded: bool


def _extract_sql(reply: str) -> str:
    """Strip a ```sql fence around the model's reply, tolerating a missing
    closing fence — models sometimes fail to close the code block, and a
    regex requiring both fences would silently fail open and leave the
    markers in the "SQL", which then correctly (but unhelpfully) fails the
    SELECT-only guardrail instead of being treated as a parsing problem.
    """
    text = reply.strip()
    text = re.sub(r"^```(?:sql)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"```\s*$", "", text)
    return text.strip().rstrip(";")


def _build_context_block(context: list[dict]) -> str:
    return "\n\n".join(chunk["text"] for chunk in context)


def generate_sql(
    question: str,
    context: list[dict],
    error_feedback: str | None = None,
    chat_fn: Callable[[str, str], str] | None = None,
) -> str:
    """Ask the model for a single SQL statement grounded in the retrieved
    semantic layer context.

    chat_fn defaults to the local Ollama chat() (resolved at call time, not
    bind time, so tests can monkeypatch module-level `chat`). Passing a
    different chat_fn — e.g. an OpenAI-backed one — lets evaluation scripts
    drive the same retry-loop logic against a different model without
    duplicating it.
    """
    fn = chat_fn or chat
    user_content = f"Question: {question}\n\nContext:\n{_build_context_block(context)}"
    if error_feedback:
        user_content += (
            f"\n\nThe previous attempt failed with this error:\n{error_feedback}\n"
            "Write a corrected query."
        )
    try:
        reply = fn(SQL_SYSTEM_PROMPT, user_content)
    except (OllamaUnavailableError, ApiUnavailableError) as exc:
        raise SqlGenerationError(str(exc)) from exc

    return _extract_sql(reply)


def answer_question(
    question: str,
    con: duckdb.DuckDBPyConnection,
    retriever: Retriever,
    reranker: Reranker,
    max_attempts: int = MAX_ATTEMPTS,
    chat_fn: Callable[[str, str], str] | None = None,
) -> AgentResponse:
    """Run the full pipeline: retrieve context, generate SQL, execute it,
    validate the result, and retry (feeding the error back to the model)
    up to max_attempts times.
    """
    context = search_schema(question, retriever, reranker)
    attempts: list[AgentAttempt] = []
    error_feedback: str | None = None

    for _ in range(max_attempts):
        try:
            sql = generate_sql(question, context, error_feedback, chat_fn)
        except SqlGenerationError as exc:
            attempts.append(
                AgentAttempt(
                    sql="", result=None, error=str(exc), valid=False, validation_reason="SQL generation failed"
                )
            )
            break

        try:
            result = run_sql(con, sql)
        except (GuardrailViolation, QueryTimeoutError, duckdb.Error) as exc:
            attempts.append(
                AgentAttempt(sql=sql, result=None, error=str(exc), valid=False, validation_reason="execution failed")
            )
            error_feedback = str(exc)
            continue

        valid, reason = validate_result(question, result)
        attempts.append(AgentAttempt(sql=sql, result=result, error=None, valid=valid, validation_reason=reason))
        if valid:
            break
        error_feedback = reason

    last = attempts[-1] if attempts else None
    succeeded = bool(last and last.valid)
    return AgentResponse(
        question=question,
        context=context,
        attempts=attempts,
        final_sql=last.sql if last else None,
        final_result=last.result if last else None,
        succeeded=succeeded,
    )
