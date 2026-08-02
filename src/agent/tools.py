"""Agent-callable tools: search_schema, run_sql, validate_result."""

from __future__ import annotations

import duckdb

from src.agent.guardrails import QueryResult, run_guarded_query
from src.retrieval.reranker import Reranker
from src.retrieval.retriever import Retriever
from src.retrieval.rewriter import rewrite_query


def search_schema(
    question: str,
    retriever: Retriever,
    reranker: Reranker,
    k_retrieve: int = 8,
    k_final: int = 4,
) -> list[dict]:
    """Rewrite the question, hybrid-search the semantic layer, rerank the
    candidates, and return the top k_final chunks as plain dicts.
    """
    rewritten = rewrite_query(question)
    candidates = retriever.hybrid_search(rewritten, k=k_retrieve)
    reranked = reranker.rerank(rewritten, candidates, k=k_final)
    return [
        {
            "doc_id": doc.doc_id,
            "type": doc.doc_type,
            "name": doc.name,
            "text": doc.text,
            "score": score,
        }
        for doc, score in reranked
    ]


def run_sql(con: duckdb.DuckDBPyConnection, sql: str) -> QueryResult:
    """Execute SQL through the guarded, read-only connection."""
    return run_guarded_query(con, sql)


_RATE_KEYWORDS = ("rate", "percentage", "share", "fraction")


def validate_result(question: str, result: QueryResult) -> tuple[bool, str]:
    """Heuristic plausibility check on a query result.

    Deliberately not an LLM call: an empty result set or an all-NULL
    result set are the two shapes that most reliably indicate the SQL
    didn't actually answer the question, and checking for them costs
    nothing. Additionally, every rate/share metric in metrics.yml
    (repeat_customer_rate, average_discount_rate) is defined as a
    fraction in [0, 1] — if the question asks for a rate/share/percentage
    and the result contains a numeric value outside that range, the SQL
    likely computed the wrong thing (e.g. a raw count, or a percentage
    left un-normalised).
    """
    if result.row_count == 0:
        return False, "Query returned no rows."
    if all(value is None for row in result.rows for value in row):
        return False, "Query returned only NULL values."

    if any(keyword in question.lower() for keyword in _RATE_KEYWORDS):
        numeric_values = [
            value for row in result.rows for value in row if isinstance(value, (int, float))
        ]
        if numeric_values and any(not (0 <= value <= 1) for value in numeric_values):
            return False, "Question asks for a rate/share, but the result falls outside [0, 1]."

    return True, "Result looks plausible."
