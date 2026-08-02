"""Tests for the agent's SQL execution guardrails: SELECT-only whitelist,
row cap, and query timeout. These checks are the load-bearing safety layer
for LLM-generated SQL, so they are tested against the real warehouse
connection, not mocked.
"""

import sys
import time
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.agent.guardrails import (
    GuardrailViolation,
    QueryTimeoutError,
    apply_row_limit,
    check_select_only,
    run_guarded_query,
)
from src.config import DUCKDB_PATH
from src.db.duckdb_client import get_connection

pytestmark = pytest.mark.skipif(
    not DUCKDB_PATH.exists(),
    reason="warehouse.duckdb not built yet — run scripts/seed_and_index.py",
)


@pytest.fixture
def con():
    connection = get_connection()
    yield connection
    connection.close()


# --- check_select_only ------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM fact_orders",
        "select * from fact_orders",
        "  SELECT COUNT(*) FROM fact_orders  ",
        "WITH x AS (SELECT 1 AS a) SELECT * FROM x",
        "SELECT * FROM fact_orders;",
    ],
)
def test_check_select_only_allows_valid_select(sql):
    check_select_only(sql)  # should not raise


@pytest.mark.parametrize(
    "sql",
    [
        "",
        "DROP TABLE fact_orders",
        "INSERT INTO fact_orders VALUES (1)",
        "UPDATE fact_orders SET quantity = 0",
        "DELETE FROM fact_orders",
        "ALTER TABLE fact_orders ADD COLUMN x INT",
        "CREATE TABLE evil (x INT)",
        "ATTACH 'other.db' AS other",
        "PRAGMA table_info('fact_orders')",
        "CALL dbgen(sf=1)",
        "SELECT 1; DROP TABLE fact_orders",
        "SELECT * FROM fact_orders; SELECT * FROM dim_region",
        "EXPLAIN SELECT * FROM fact_orders",
    ],
)
def test_check_select_only_rejects_everything_else(sql):
    with pytest.raises(GuardrailViolation):
        check_select_only(sql)


# --- apply_row_limit -----------------------------------------------------


def test_apply_row_limit_wraps_query_with_limit():
    guarded = apply_row_limit("SELECT * FROM fact_orders", max_rows=100)
    assert "LIMIT 101" in guarded
    assert "SELECT * FROM fact_orders" in guarded


# --- run_guarded_query: row cap ------------------------------------------


def test_run_guarded_query_caps_rows_and_flags_truncation(con):
    result = run_guarded_query(con, "SELECT * FROM fact_orders", max_rows=5)
    assert result.row_count == 5
    assert result.truncated is True


def test_run_guarded_query_does_not_flag_truncation_when_under_cap(con):
    result = run_guarded_query(con, "SELECT * FROM dim_region", max_rows=1000)
    assert result.row_count == 25
    assert result.truncated is False


def test_run_guarded_query_supports_cte(con):
    result = run_guarded_query(con, "WITH x AS (SELECT 1 AS a) SELECT * FROM x", max_rows=10)
    assert result.rows == [(1,)]


def test_run_guarded_query_rejects_write_before_executing(con):
    with pytest.raises(GuardrailViolation):
        run_guarded_query(con, "DROP TABLE fact_orders")

    # the table must genuinely still exist — guardrail fired before execution
    count = con.execute("SELECT COUNT(*) FROM fact_orders").fetchone()[0]
    assert count > 0


def test_run_guarded_query_propagates_real_sql_errors(con):
    with pytest.raises(duckdb.Error):
        run_guarded_query(con, "SELECT * FROM table_that_does_not_exist")


# --- run_guarded_query: timeout -------------------------------------------


def test_run_guarded_query_times_out_on_slow_query(con):
    slow_query = "SELECT COUNT(*) FROM fact_orders a, fact_orders b"
    start = time.perf_counter()
    with pytest.raises(QueryTimeoutError):
        run_guarded_query(con, slow_query, timeout_seconds=1.0)
    elapsed = time.perf_counter() - start

    # must be interrupted promptly, not left to run to completion (~20s+)
    assert elapsed < 5.0


def test_connection_still_usable_after_a_timeout(con):
    slow_query = "SELECT COUNT(*) FROM fact_orders a, fact_orders b"
    with pytest.raises(QueryTimeoutError):
        run_guarded_query(con, slow_query, timeout_seconds=1.0)

    result = run_guarded_query(con, "SELECT COUNT(*) FROM fact_orders", timeout_seconds=5.0)
    assert result.rows[0][0] > 0


def test_run_guarded_query_does_not_time_out_on_fast_query(con):
    result = run_guarded_query(con, "SELECT COUNT(*) FROM fact_orders", timeout_seconds=5.0)
    assert result.rows[0][0] > 0
