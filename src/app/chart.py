"""Picks a chart form for an agent answer's result shape.

Follows the "is it even a chart?" heuristic: a single value is a stat
tile, not a one-bar bar chart; a short category/value breakdown is a bar
chart; a time series is a line chart; anything wider than that falls
back to a table, which stays honest rather than forcing an unreadable
chart onto an arbitrary result shape. No Streamlit imports here, so the
picking logic is testable without running the app.
"""

from __future__ import annotations

import warnings

import pandas as pd

MAX_KPI_COLUMNS = 4
DATE_LIKE_NAME_HINTS = ("date", "month", "quarter", "year", "week")


def to_dataframe(columns: list[str], rows: list[list]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=columns)


def _is_numeric(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _looks_like_date_column(column_name: str, values: list) -> bool:
    if any(hint in column_name.lower() for hint in DATE_LIKE_NAME_HINTS):
        return True
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            pd.to_datetime(pd.Series(values))
        return True
    except (ValueError, TypeError):
        return False


def pick_chart_kind(columns: list[str], rows: list[list]) -> str:
    """Returns one of "metric", "kpi_row", "bar", "line", "table"."""
    if not rows or not columns:
        return "table"

    if len(rows) == 1:
        if len(columns) == 1:
            return "metric"
        return "kpi_row" if len(columns) <= MAX_KPI_COLUMNS else "table"

    if len(columns) == 2 and all(_is_numeric(row[1]) for row in rows):
        first_column_values = [row[0] for row in rows]
        if _looks_like_date_column(columns[0], first_column_values):
            return "line"
        return "bar"

    return "table"
