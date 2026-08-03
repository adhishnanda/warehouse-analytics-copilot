"""Tests for the monitoring dashboard's pure data-prep functions
(monitoring/metrics.py). No Streamlit or DuckDB dependency.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from monitoring.metrics import categorize_error, compute_cost_usd, compute_percentiles

# --- compute_cost_usd -----------------------------------------------


def test_ollama_model_costs_nothing():
    assert compute_cost_usd("llama3", prompt_tokens=10_000, completion_tokens=5_000) == 0.0


def test_gpt_4o_mini_cost_matches_published_pricing():
    # 1,000,000 prompt tokens @ $0.15/1M + 1,000,000 completion tokens @ $0.60/1M
    cost = compute_cost_usd("gpt-4o-mini", prompt_tokens=1_000_000, completion_tokens=1_000_000)
    assert cost == 0.75


def test_unknown_model_costs_nothing():
    assert compute_cost_usd("some-future-model", prompt_tokens=1_000_000, completion_tokens=1_000_000) == 0.0


# --- compute_percentiles ----------------------------------------------


def test_percentiles_on_empty_list_returns_zero():
    assert compute_percentiles([]) == {0.5: 0.0, 0.95: 0.0}


def test_percentiles_on_single_value():
    assert compute_percentiles([5.0]) == {0.5: 5.0, 0.95: 5.0}


def test_p50_and_p95_on_a_sorted_range():
    values = list(range(1, 101))  # 1..100
    result = compute_percentiles([float(v) for v in values], percentiles=(0.5, 0.95))
    assert result[0.5] == 51.0
    assert result[0.95] == 95.0


def test_percentiles_do_not_require_pre_sorted_input():
    values = [5.0, 1.0, 3.0, 2.0, 4.0]
    result = compute_percentiles(values, percentiles=(0.5,))
    assert result[0.5] == 3.0


# --- categorize_error --------------------------------------------------


def test_no_error_is_categorized_as_succeeded():
    assert categorize_error(None) == "succeeded"
    assert categorize_error("") == "succeeded"


def test_nan_error_is_categorized_as_succeeded():
    # pandas/DuckDB round-trips a NULL error column as float NaN, not
    # None - a real bug caught by running the dashboard against real
    # data (NaN is truthy in Python, so `not error` alone misses it).
    assert categorize_error(float("nan")) == "succeeded"


def test_guardrail_violations_are_categorized_correctly():
    assert categorize_error("Empty query.") == "guardrail rejection"
    assert categorize_error("Multiple statements are not allowed.") == "guardrail rejection"
    assert categorize_error("Only SELECT (or WITH ... SELECT) statements are allowed.") == "guardrail rejection"
    assert categorize_error("Disallowed keyword in query: DROP") == "guardrail rejection"


def test_query_timeout_is_categorized_correctly():
    assert categorize_error("Query exceeded 10.0s and was cancelled.") == "query timeout"


def test_implausible_result_is_categorized_correctly():
    assert categorize_error("Query returned no rows.") == "implausible result"
    assert categorize_error("Query returned only NULL values.") == "implausible result"
    assert (
        categorize_error("Question asks for a rate/share, but the result falls outside [0, 1].")
        == "implausible result"
    )


def test_duckdb_native_errors_are_categorized_as_sql_execution_error():
    assert categorize_error('Binder Error: Table "r" does not have a column named "region_key"') == "SQL execution error"
    assert categorize_error("Catalog Error: Table does not exist") == "SQL execution error"


def test_backend_errors_are_categorized_correctly():
    assert categorize_error("HTTP 429: rate_limit_exceeded") == "LLM backend error"
    assert categorize_error("Ollama backend unreachable") == "LLM backend error"


def test_unrecognized_error_falls_back_to_other():
    assert categorize_error("something completely unexpected") == "other"
