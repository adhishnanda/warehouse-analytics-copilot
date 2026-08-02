"""Load TPC-H data into a governed star schema in DuckDB.

Generates TPC-H data via DuckDB's built-in dbgen, then reshapes it into
one fact table and five dimension tables (customer, product, date, region,
supplier). Raw TPC-H tables are dropped afterwards so only the governed
star schema is queryable — this is the scope the semantic layer documents
and the agent is allowed to see.

Usage:
    uv run python data/seed_warehouse.py [--scale-factor 0.1] [--out data/warehouse.duckdb]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import DUCKDB_PATH, TPCH_SCALE_FACTOR  # noqa: E402

RAW_TPCH_TABLES = [
    "region",
    "nation",
    "customer",
    "supplier",
    "part",
    "partsupp",
    "orders",
    "lineitem",
]


def generate_tpch(con: duckdb.DuckDBPyConnection, scale_factor: float) -> None:
    con.execute("INSTALL tpch")
    con.execute("LOAD tpch")
    con.execute(f"CALL dbgen(sf={scale_factor})")


def build_dim_region(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE OR REPLACE TABLE dim_region AS
        SELECT
            n.n_nationkey AS nation_key,
            n.n_name AS nation_name,
            r.r_name AS region_name
        FROM nation n
        JOIN region r ON n.n_regionkey = r.r_regionkey
        ORDER BY n.n_nationkey
    """)


def build_dim_customer(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE OR REPLACE TABLE dim_customer AS
        SELECT
            c.c_custkey AS customer_key,
            c.c_name AS customer_name,
            c.c_address AS address,
            c.c_phone AS phone,
            c.c_acctbal AS account_balance,
            c.c_mktsegment AS market_segment,
            c.c_nationkey AS nation_key
        FROM customer c
        ORDER BY c.c_custkey
    """)


def build_dim_supplier(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE OR REPLACE TABLE dim_supplier AS
        SELECT
            s.s_suppkey AS supplier_key,
            s.s_name AS supplier_name,
            s.s_address AS address,
            s.s_phone AS phone,
            s.s_acctbal AS account_balance,
            s.s_nationkey AS nation_key
        FROM supplier s
        ORDER BY s.s_suppkey
    """)


def build_dim_product(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE OR REPLACE TABLE dim_product AS
        SELECT
            p.p_partkey AS product_key,
            p.p_name AS product_name,
            p.p_mfgr AS manufacturer,
            p.p_brand AS brand,
            p.p_type AS product_type,
            p.p_size AS size,
            p.p_container AS container,
            p.p_retailprice AS retail_price
        FROM part p
        ORDER BY p.p_partkey
    """)


def build_dim_date(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE OR REPLACE TABLE dim_date AS
        WITH bounds AS (
            SELECT
                LEAST(MIN(o.o_orderdate), MIN(l.l_shipdate)) AS min_date,
                GREATEST(MAX(o.o_orderdate), MAX(l.l_receiptdate)) AS max_date
            FROM orders o, lineitem l
        ),
        spine AS (
            SELECT unnest(generate_series(min_date, max_date, INTERVAL 1 DAY)) AS full_date
            FROM bounds
        )
        SELECT
            CAST(strftime(full_date, '%Y%m%d') AS INTEGER) AS date_key,
            full_date,
            EXTRACT(YEAR FROM full_date) AS year,
            EXTRACT(QUARTER FROM full_date) AS quarter,
            EXTRACT(MONTH FROM full_date) AS month,
            strftime(full_date, '%B') AS month_name,
            EXTRACT(DAY FROM full_date) AS day,
            EXTRACT(DOW FROM full_date) AS day_of_week,
            strftime(full_date, '%A') AS day_name,
            EXTRACT(DOW FROM full_date) IN (0, 6) AS is_weekend
        FROM spine
        ORDER BY full_date
    """)


def build_fact_orders(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE OR REPLACE TABLE fact_orders AS
        SELECT
            l.l_orderkey AS order_key,
            l.l_linenumber AS line_number,
            o.o_custkey AS customer_key,
            l.l_suppkey AS supplier_key,
            l.l_partkey AS product_key,
            CAST(strftime(o.o_orderdate, '%Y%m%d') AS INTEGER) AS order_date_key,
            CAST(strftime(l.l_shipdate, '%Y%m%d') AS INTEGER) AS ship_date_key,
            o.o_orderstatus AS order_status,
            o.o_orderpriority AS order_priority,
            l.l_shipmode AS ship_mode,
            l.l_returnflag AS return_flag,
            l.l_linestatus AS line_status,
            l.l_quantity AS quantity,
            l.l_extendedprice AS extended_price,
            l.l_discount AS discount,
            l.l_tax AS tax,
            ROUND(l.l_extendedprice * (1 - l.l_discount), 2) AS net_revenue
        FROM lineitem l
        JOIN orders o ON l.l_orderkey = o.o_orderkey
        ORDER BY l.l_orderkey, l.l_linenumber
    """)


def drop_raw_tpch_tables(con: duckdb.DuckDBPyConnection) -> None:
    for table in RAW_TPCH_TABLES:
        con.execute(f"DROP TABLE IF EXISTS {table}")


def report_row_counts(con: duckdb.DuckDBPyConnection) -> None:
    tables = ["fact_orders", "dim_customer", "dim_product", "dim_date", "dim_region", "dim_supplier"]
    for table in tables:
        count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {count:,} rows")


def seed(out_path: Path, scale_factor: float) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    con = duckdb.connect(str(out_path))
    try:
        print(f"Generating TPC-H data at scale factor {scale_factor}...")
        generate_tpch(con, scale_factor)

        print("Building star schema...")
        build_dim_region(con)
        build_dim_customer(con)
        build_dim_supplier(con)
        build_dim_product(con)
        build_dim_date(con)
        build_fact_orders(con)

        drop_raw_tpch_tables(con)

        print(f"Warehouse written to {out_path}")
        report_row_counts(con)
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scale-factor", type=float, default=TPCH_SCALE_FACTOR)
    parser.add_argument("--out", type=Path, default=DUCKDB_PATH)
    args = parser.parse_args()

    seed(args.out, args.scale_factor)


if __name__ == "__main__":
    main()
