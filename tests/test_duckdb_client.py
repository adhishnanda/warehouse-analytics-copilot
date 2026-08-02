"""Verify the read-only DuckDB connection actually blocks writes.

This is the outermost guardrail layer — independent of the statement
whitelist in src/agent/guardrails.py, which is tested separately.
"""

import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import DUCKDB_PATH
from src.db.duckdb_client import get_connection

pytestmark = pytest.mark.skipif(
    not DUCKDB_PATH.exists(),
    reason="warehouse.duckdb not built yet — run scripts/seed_and_index.py",
)


def test_connection_can_read():
    con = get_connection()
    count = con.execute("SELECT COUNT(*) FROM fact_orders").fetchone()[0]
    assert count > 0


@pytest.mark.parametrize(
    "statement",
    [
        "CREATE TABLE evil (x INTEGER)",
        "INSERT INTO fact_orders (order_key) VALUES (1)",
        "DELETE FROM fact_orders",
        "DROP TABLE fact_orders",
        "UPDATE fact_orders SET quantity = 0",
    ],
)
def test_connection_blocks_writes(statement):
    con = get_connection()
    with pytest.raises(duckdb.Error):
        con.execute(statement)
