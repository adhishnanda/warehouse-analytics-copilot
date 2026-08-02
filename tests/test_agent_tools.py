"""Tests for the three agent-callable tools: search_schema, run_sql,
validate_result.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.agent.guardrails import QueryResult
from src.agent.tools import run_sql, search_schema, validate_result
from src.config import DUCKDB_PATH
from src.db.duckdb_client import get_connection
from src.retrieval.indexer import INDEX_PATH
from src.retrieval.reranker import Reranker
from src.retrieval.retriever import Retriever

pytestmark = pytest.mark.skipif(
    not (DUCKDB_PATH.exists() and INDEX_PATH.exists()),
    reason="warehouse/index not built yet — run scripts/seed_and_index.py",
)


@pytest.fixture(scope="module")
def retriever():
    return Retriever()


@pytest.fixture(scope="module")
def reranker():
    return Reranker()


@pytest.fixture
def con():
    connection = get_connection()
    yield connection
    connection.close()


# --- search_schema ---------------------------------------------------


def test_search_schema_returns_expected_shape(retriever, reranker):
    results = search_schema("what is our repeat customer rate", retriever, reranker, k_final=3)
    assert len(results) == 3
    for chunk in results:
        assert set(chunk.keys()) == {"doc_id", "type", "name", "text", "score"}


def test_search_schema_finds_relevant_metric(retriever, reranker):
    results = search_schema("what is our repeat customer rate", retriever, reranker, k_final=3)
    doc_ids = [chunk["doc_id"] for chunk in results]
    assert "metric:repeat_customer_rate" in doc_ids


# --- run_sql -----------------------------------------------------------


def test_run_sql_executes_a_valid_select(con):
    result = run_sql(con, "SELECT COUNT(*) AS n FROM fact_orders")
    assert result.rows[0][0] > 0


def test_run_sql_blocks_a_write(con):
    from src.agent.guardrails import GuardrailViolation

    with pytest.raises(GuardrailViolation):
        run_sql(con, "DROP TABLE fact_orders")


# --- validate_result -----------------------------------------------------


def _result(rows, columns=("value",)):
    return QueryResult(columns=list(columns), rows=rows, row_count=len(rows), truncated=False)


def test_validate_result_rejects_empty():
    valid, _reason = validate_result("how many orders", _result([]))
    assert valid is False


def test_validate_result_rejects_all_null():
    valid, _reason = validate_result("what is total revenue", _result([(None,)]))
    assert valid is False


def test_validate_result_accepts_normal_result():
    valid, _reason = validate_result("how many orders", _result([(42,)]))
    assert valid is True


def test_validate_result_accepts_rate_within_range():
    valid, _reason = validate_result("what is our repeat customer rate", _result([(0.34,)]))
    assert valid is True


def test_validate_result_rejects_rate_outside_range():
    valid, reason = validate_result("what is our repeat customer rate", _result([(34.0,)]))
    assert valid is False
    assert "0, 1" in reason


def test_validate_result_ignores_non_numeric_values_for_rate_check():
    valid, _reason = validate_result("what percentage of customers are repeat", _result([("N/A",)]))
    assert valid is True
