"""Query rewriting: expand a user's business question into a
retrieval-friendlier form before it is passed to search.

Uses a local Ollama model by default (zero cost, no API key) — the
project's cost-discipline rule reserves paid models for the final
evaluation runs in Week 2.
"""

from __future__ import annotations

from src.llm_client import OllamaUnavailableError, chat

SYSTEM_PROMPT = (
    "You are the query rewriting step in a text-to-SQL system over a small "
    "governed analytics warehouse (orders, customers, products, suppliers, "
    "regions, and dates - a TPC-H-style schema with revenue, discount, order "
    "count, and repeat-customer metrics defined). Rewrite the user's business "
    "question into a short, retrieval-friendly form: expand abbreviations, "
    "and make explicit which business concepts the question is really "
    "asking about (e.g. revenue, discount rate, order count, repeat "
    "customers, region, supplier, ship date vs order date). Do not answer "
    "the question. Do not invent numbers or SQL. Output only the rewritten "
    "question, with no preamble or explanation."
)


def rewrite_query(question: str, timeout: float = 30.0) -> str:
    """Return a retrieval-friendly rewrite of `question`.

    Falls back to returning the original question unchanged if the local
    model backend is unreachable — rewriting is an optimization, not a
    required step, so retrieval must still work without it.
    """
    try:
        rewritten = chat(SYSTEM_PROMPT, question, timeout=timeout)
    except OllamaUnavailableError:
        return question
    return rewritten or question
