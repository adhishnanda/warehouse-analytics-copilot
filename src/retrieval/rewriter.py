"""Query rewriting: expand a user's business question into a
retrieval-friendlier form before it is passed to search.

Uses a local Ollama model by default (zero cost, no API key) — the
project's cost-discipline rule reserves paid models for the final
evaluation runs in Week 2.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from src.config import OLLAMA_BASE_URL, OLLAMA_MODEL

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
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
        "stream": False,
    }
    request = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read())
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
        return question

    rewritten = body.get("message", {}).get("content", "").strip()
    return rewritten or question
