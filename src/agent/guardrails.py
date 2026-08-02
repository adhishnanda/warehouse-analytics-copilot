"""Guardrails for the agent's SQL execution path.

Kept in its own file, separate from tools.py, so the safety logic is
auditable on its own. Four independent layers:

1. Read-only connection (src/db/duckdb_client.py) — DuckDB itself refuses
   any write regardless of what SQL is passed to it.
2. SELECT-only whitelist (check_select_only) — rejects anything that
   isn't a single standalone SELECT/WITH...SELECT statement, and rejects
   known write/DDL/admin keywords outright as a second, independent check.
3. Row limit (apply_row_limit) — every query is wrapped so at most
   MAX_ROWS rows can ever be returned, regardless of what the inner query
   does.
4. Query timeout (run_guarded_query) — a watchdog thread interrupts the
   connection if execution exceeds QUERY_TIMEOUT_SECONDS.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass

import duckdb

MAX_ROWS = 1000
QUERY_TIMEOUT_SECONDS = 10.0

_DISALLOWED_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|ATTACH|DETACH|"
    r"COPY|EXPORT|IMPORT|CALL|PRAGMA|SET|INSTALL|LOAD|VACUUM|GRANT|REVOKE)\b",
    re.IGNORECASE,
)


class GuardrailViolation(Exception):
    """Raised when a candidate SQL statement fails a guardrail check."""


class QueryTimeoutError(Exception):
    """Raised when a query exceeds the allowed execution time."""


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    row_count: int
    truncated: bool


def check_select_only(sql: str) -> None:
    """Reject anything that isn't a single, standalone SELECT statement."""
    stripped = sql.strip().rstrip(";")

    if not stripped:
        raise GuardrailViolation("Empty query.")

    if ";" in stripped:
        raise GuardrailViolation("Multiple statements are not allowed.")

    if not re.match(r"^\s*(WITH\b|SELECT\b)", stripped, re.IGNORECASE):
        raise GuardrailViolation("Only SELECT (or WITH ... SELECT) statements are allowed.")

    match = _DISALLOWED_KEYWORDS.search(stripped)
    if match:
        raise GuardrailViolation(f"Disallowed keyword in query: {match.group(0)}")


def apply_row_limit(sql: str, max_rows: int = MAX_ROWS) -> str:
    """Wrap the query so at most max_rows rows can ever be returned.

    Requests max_rows + 1 so the caller can detect true truncation rather
    than guessing from a row count that happens to equal the cap.
    """
    stripped = sql.strip().rstrip(";")
    return f"SELECT * FROM ({stripped}) AS _guarded_subquery LIMIT {max_rows + 1}"


def run_guarded_query(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    max_rows: int = MAX_ROWS,
    timeout_seconds: float = QUERY_TIMEOUT_SECONDS,
) -> QueryResult:
    """Validate, cap, and execute a single SELECT statement with a timeout."""
    check_select_only(sql)
    guarded_sql = apply_row_limit(sql, max_rows)

    result_holder: dict = {}
    error_holder: dict = {}

    def _execute() -> None:
        try:
            cursor = con.execute(guarded_sql)
            result_holder["columns"] = [d[0] for d in cursor.description]
            result_holder["rows"] = cursor.fetchall()
        except Exception as exc:  # noqa: BLE001 - re-raised on the calling thread
            error_holder["error"] = exc

    thread = threading.Thread(target=_execute, daemon=True)
    thread.start()
    thread.join(timeout_seconds)

    if thread.is_alive():
        con.interrupt()
        thread.join(timeout_seconds)
        raise QueryTimeoutError(f"Query exceeded {timeout_seconds}s and was cancelled.")

    if "error" in error_holder:
        raise error_holder["error"]

    rows = result_holder["rows"]
    truncated = len(rows) > max_rows
    if truncated:
        rows = rows[:max_rows]

    return QueryResult(
        columns=result_holder["columns"],
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
    )
