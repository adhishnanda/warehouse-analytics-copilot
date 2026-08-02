"""Sandboxed, read-only DuckDB connection.

This is the outermost layer of the guardrail story: even if a query
somehow slipped past the statement-level checks in
src/agent/guardrails.py, DuckDB itself refuses any write against a
connection opened with read_only=True.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from src.config import DUCKDB_PATH


def get_connection(path: Path = DUCKDB_PATH) -> duckdb.DuckDBPyConnection:
    """Open a read-only connection to the warehouse."""
    return duckdb.connect(str(path), read_only=True)
