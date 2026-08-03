"""Pure data-prep functions for the monitoring dashboard
(monitoring/dashboard.py) — no Streamlit or DuckDB dependency, so
they're testable on their own.
"""

from __future__ import annotations

# Verified live from platform.openai.com/docs/pricing (see
# evaluation/results/llm_eval.md's Cost section). Any model not listed
# here (e.g. local Ollama models) costs $0 — local compute has no
# billable usage.
PRICING_USD_PER_MILLION_TOKENS = {
    "gpt-4o-mini": {"prompt": 0.15, "completion": 0.60},
}


def compute_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pricing = PRICING_USD_PER_MILLION_TOKENS.get(model)
    if not pricing:
        return 0.0
    return (prompt_tokens * pricing["prompt"] + completion_tokens * pricing["completion"]) / 1_000_000


def compute_percentiles(values: list[float], percentiles: tuple[float, ...] = (0.5, 0.95)) -> dict[float, float]:
    """Nearest-rank percentiles over a list of latencies. Returns 0.0 for
    every requested percentile when values is empty, so callers don't
    need a separate empty-data branch.
    """
    if not values:
        return {p: 0.0 for p in percentiles}
    ordered = sorted(values)
    result = {}
    for p in percentiles:
        index = min(int(round(p * (len(ordered) - 1))), len(ordered) - 1)
        result[p] = ordered[index]
    return result


# Known error-message prefixes/substrings from the system's own error
# vocabulary (src/agent/guardrails.py, src/agent/tools.py,
# src/agent/loop.py's SqlGenerationError) — mechanical categorization
# by which layer produced the failure, not the deeper semantic causes
# Day 14's error_analysis.md dug into by hand.
_GUARDRAIL_MESSAGES = (
    "Empty query.",
    "Multiple statements are not allowed.",
)
_GUARDRAIL_PREFIXES = ("Only SELECT", "Disallowed keyword in query:")
_IMPLAUSIBLE_RESULT_MESSAGES = (
    "Query returned no rows.",
    "Query returned only NULL values.",
)


def categorize_error(error: str | None) -> str:
    # A successful trace's error column round-trips through DuckDB/pandas
    # as NaN (a float), not None or "" - both are truthy in Python, so
    # `not error` alone would miss NaN and crash on the .startswith calls
    # below. Any non-string value here can only mean "no error".
    if not isinstance(error, str) or not error:
        return "succeeded"
    if error in _GUARDRAIL_MESSAGES or error.startswith(_GUARDRAIL_PREFIXES):
        return "guardrail rejection"
    if "exceeded" in error and "cancelled" in error:
        return "query timeout"
    if error in _IMPLAUSIBLE_RESULT_MESSAGES or "falls outside [0, 1]" in error:
        return "implausible result"
    if error.startswith(("Binder Error:", "Catalog Error:", "Parser Error:", "Conversion Error:", "Constraint Error:")):
        return "SQL execution error"
    if any(keyword in error for keyword in ("HTTP", "unreachable", "Unavailable", "timed out", "Connection")):
        return "LLM backend error"
    return "other"
