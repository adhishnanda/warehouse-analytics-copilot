"""Tests for the chart-form heuristic (src/app/chart.py). No Streamlit
or app dependency — pure function over (columns, rows).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.app.chart import pick_chart_kind


def test_single_value_is_a_metric_not_a_bar_chart():
    assert pick_chart_kind(["order_count"], [[150000]]) == "metric"


def test_single_row_multiple_columns_is_a_kpi_row():
    assert pick_chart_kind(["orders", "revenue"], [[150000, 20535072329.05]]) == "kpi_row"


def test_single_row_too_many_columns_falls_back_to_table():
    columns = ["a", "b", "c", "d", "e"]
    assert pick_chart_kind(columns, [[1, 2, 3, 4, 5]]) == "table"


def test_category_breakdown_is_a_bar_chart():
    rows = [["EUROPE", 4082606859.78], ["ASIA", 4120876821.83]]
    assert pick_chart_kind(["region", "revenue"], rows) == "bar"


def test_date_like_column_name_is_a_line_chart():
    rows = [["2026-01-01", 100.0], ["2026-02-01", 200.0]]
    assert pick_chart_kind(["order_month", "revenue"], rows) == "line"


def test_date_like_values_without_date_column_name_is_a_line_chart():
    rows = [["2026-01-01", 100.0], ["2026-02-01", 200.0]]
    assert pick_chart_kind(["period", "revenue"], rows) == "line"


def test_non_numeric_second_column_falls_back_to_table():
    rows = [["EUROPE", "high"], ["ASIA", "medium"]]
    assert pick_chart_kind(["region", "tier"], rows) == "table"


def test_more_than_two_columns_falls_back_to_table():
    rows = [["EUROPE", "AUTOMOBILE", 100.0], ["ASIA", "MACHINERY", 200.0]]
    assert pick_chart_kind(["region", "segment", "revenue"], rows) == "table"


def test_empty_result_is_a_table():
    assert pick_chart_kind(["order_count"], []) == "table"
