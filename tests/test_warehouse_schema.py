"""Verify the seeded DuckDB star schema: shape, row counts, referential integrity.

Requires data/warehouse.duckdb to exist (run data/seed_warehouse.py first).
"""

import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import DUCKDB_PATH

pytestmark = pytest.mark.skipif(
    not DUCKDB_PATH.exists(),
    reason="warehouse.duckdb not built yet — run data/seed_warehouse.py",
)


@pytest.fixture(scope="module")
def con():
    connection = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    yield connection
    connection.close()


EXPECTED_TABLES = {
    "fact_orders",
    "dim_customer",
    "dim_product",
    "dim_date",
    "dim_region",
    "dim_supplier",
}

RAW_TPCH_TABLES = {
    "region",
    "nation",
    "customer",
    "supplier",
    "part",
    "partsupp",
    "orders",
    "lineitem",
}


def test_only_star_schema_tables_exist(con):
    tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    assert EXPECTED_TABLES <= tables
    assert not (tables & RAW_TPCH_TABLES), "raw TPC-H tables should be dropped after seeding"


@pytest.mark.parametrize("table", sorted(EXPECTED_TABLES))
def test_tables_are_non_empty(con, table):
    count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    assert count > 0


def test_dim_customer_key_is_unique(con):
    total = con.execute("SELECT COUNT(*) FROM dim_customer").fetchone()[0]
    distinct = con.execute("SELECT COUNT(DISTINCT customer_key) FROM dim_customer").fetchone()[0]
    assert total == distinct


def test_dim_product_key_is_unique(con):
    total = con.execute("SELECT COUNT(*) FROM dim_product").fetchone()[0]
    distinct = con.execute("SELECT COUNT(DISTINCT product_key) FROM dim_product").fetchone()[0]
    assert total == distinct


def test_dim_supplier_key_is_unique(con):
    total = con.execute("SELECT COUNT(*) FROM dim_supplier").fetchone()[0]
    distinct = con.execute("SELECT COUNT(DISTINCT supplier_key) FROM dim_supplier").fetchone()[0]
    assert total == distinct


def test_dim_region_nation_key_is_unique(con):
    total = con.execute("SELECT COUNT(*) FROM dim_region").fetchone()[0]
    distinct = con.execute("SELECT COUNT(DISTINCT nation_key) FROM dim_region").fetchone()[0]
    assert total == distinct


def test_dim_date_key_is_unique_and_contiguous(con):
    total = con.execute("SELECT COUNT(*) FROM dim_date").fetchone()[0]
    distinct = con.execute("SELECT COUNT(DISTINCT date_key) FROM dim_date").fetchone()[0]
    assert total == distinct

    span = con.execute(
        "SELECT DATE_DIFF('day', MIN(full_date), MAX(full_date)) + 1 FROM dim_date"
    ).fetchone()[0]
    assert span == total


def test_fact_orders_grain_is_unique(con):
    total = con.execute("SELECT COUNT(*) FROM fact_orders").fetchone()[0]
    distinct = con.execute(
        "SELECT COUNT(*) FROM (SELECT DISTINCT order_key, line_number FROM fact_orders)"
    ).fetchone()[0]
    assert total == distinct


@pytest.mark.parametrize(
    "fk_column,dim_table,dim_key",
    [
        ("customer_key", "dim_customer", "customer_key"),
        ("supplier_key", "dim_supplier", "supplier_key"),
        ("product_key", "dim_product", "product_key"),
        ("order_date_key", "dim_date", "date_key"),
        ("ship_date_key", "dim_date", "date_key"),
    ],
)
def test_fact_orders_foreign_keys_resolve(con, fk_column, dim_table, dim_key):
    orphans = con.execute(f"""
        SELECT COUNT(*)
        FROM fact_orders f
        LEFT JOIN {dim_table} d ON f.{fk_column} = d.{dim_key}
        WHERE d.{dim_key} IS NULL
    """).fetchone()[0]
    assert orphans == 0


@pytest.mark.parametrize("dim_table", ["dim_customer", "dim_supplier"])
def test_dim_nation_key_resolves_to_dim_region(con, dim_table):
    orphans = con.execute(f"""
        SELECT COUNT(*)
        FROM {dim_table} t
        LEFT JOIN dim_region r ON t.nation_key = r.nation_key
        WHERE r.nation_key IS NULL
    """).fetchone()[0]
    assert orphans == 0


def test_fact_orders_net_revenue_is_non_negative(con):
    negative = con.execute(
        "SELECT COUNT(*) FROM fact_orders WHERE net_revenue < 0"
    ).fetchone()[0]
    assert negative == 0
