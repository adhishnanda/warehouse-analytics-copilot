"""Monitoring dashboard: 6 charts over live usage telemetry (PROJECT_PLAN.md
Section 10's Monitoring section, rubric requires 5+). Reads from
data/telemetry.duckdb, built by src/telemetry/dlt_pipeline.py from the
JSONL log every /ask and /feedback call writes
(src/telemetry/logger.py).
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from monitoring.metrics import categorize_error, compute_cost_usd, compute_percentiles  # noqa: E402
from src.config import TELEMETRY_DB_PATH  # noqa: E402
from src.telemetry.dlt_pipeline import DATASET_NAME, run_pipeline  # noqa: E402

st.set_page_config(page_title="Warehouse analytics copilot — monitoring", page_icon=":material/monitoring:")


def _table_exists(con: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    result = con.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema = ? AND table_name = ?",
        [DATASET_NAME, table_name],
    ).fetchone()
    return result is not None


@st.cache_data(ttl="5m")
def load_table(table_name: str) -> pd.DataFrame:
    if not TELEMETRY_DB_PATH.exists():
        return pd.DataFrame()
    con = duckdb.connect(str(TELEMETRY_DB_PATH), read_only=True)
    try:
        if not _table_exists(con, table_name):
            return pd.DataFrame()
        return con.execute(f"SELECT * FROM {DATASET_NAME}.{table_name}").df()
    finally:
        con.close()


st.title("Monitoring")
st.caption(
    "Live usage metrics from the deployed agent, built from "
    "data/telemetry/traces.jsonl via the dlt pipeline "
    "(src/telemetry/dlt_pipeline.py)."
)

if st.button("Refresh data", icon=":material/refresh:"):
    run_pipeline()
    st.cache_data.clear()
    st.rerun()

traces = load_table("traces")
feedback = load_table("feedback")

if traces.empty:
    st.info("No telemetry yet — ask a question in the app first, then refresh.")
    st.stop()

traces["date"] = pd.to_datetime(traces["timestamp"]).dt.date
traces["category"] = traces["error"].apply(categorize_error)

# usage__* columns are nullable ints (pd.NA for rows where generation
# failed before any usage was recorded) - `pd.NA or 0` raises TypeError
# ("boolean value of NA is ambiguous"), so fill before computing cost
# rather than relying on a truthiness fallback inside the apply.
for usage_col in ("usage__prompt_tokens", "usage__completion_tokens"):
    if usage_col not in traces.columns:
        traces[usage_col] = 0
    traces[usage_col] = traces[usage_col].fillna(0)

traces["cost_usd"] = traces.apply(
    lambda r: compute_cost_usd(
        r["model"],
        int(r["usage__prompt_tokens"]),
        int(r["usage__completion_tokens"]),
    ),
    axis=1,
)

with st.container(horizontal=True):
    st.metric("Total queries", len(traces), border=True)
    st.metric("Execution accuracy", f"{traces['succeeded'].mean():.0%}", border=True)
    st.metric("Total cost", f"${traces['cost_usd'].sum():.4f}", border=True)

with st.container(border=True):
    st.subheader("Queries over time")
    queries_per_day = traces.groupby("date").size().reset_index(name="query_count")
    st.bar_chart(queries_per_day, x="date", y="query_count", x_label="Date", y_label="Queries")

with st.container(border=True):
    st.subheader("Execution accuracy over time")
    accuracy_per_day = traces.groupby("date")["succeeded"].mean().reset_index(name="accuracy")
    # Explicit "good" status color, not the categorical default - this
    # line is a success rate, not just another series.
    st.line_chart(
        accuracy_per_day,
        x="date",
        y="accuracy",
        x_label="Date",
        y_label="Execution accuracy",
        color="#0ca30c",
    )

with st.container(border=True):
    st.subheader("Cost per query")
    cost_per_day = traces.groupby("date")["cost_usd"].mean().reset_index(name="avg_cost_usd")
    st.bar_chart(cost_per_day, x="date", y="avg_cost_usd", x_label="Date", y_label="Average cost (USD)")
    st.caption(
        "Local Ollama has no billable usage; only paid-backend "
        "(gpt-4o-mini) queries contribute non-zero cost, at the "
        "published per-token pricing in monitoring/metrics.py."
    )

with st.container(border=True):
    st.subheader("Latency (p50/p95)")
    percentiles = compute_percentiles(traces["latency_seconds"].tolist())
    with st.container(horizontal=True):
        st.metric("p50 latency", f"{percentiles[0.5]:.1f}s", border=True)
        st.metric("p95 latency", f"{percentiles[0.95]:.1f}s", border=True)

with st.container(border=True):
    st.subheader("Feedback rate")
    feedback_rate = len(feedback) / len(traces) if len(traces) else 0.0
    up_count = int((feedback["vote"] == "up").sum()) if not feedback.empty else 0
    down_count = int((feedback["vote"] == "down").sum()) if not feedback.empty else 0
    with st.container(horizontal=True):
        st.metric("Feedback rate", f"{feedback_rate:.0%}", border=True)
        st.metric("Helpful", up_count, border=True)
        st.metric("Not helpful", down_count, border=True)

with st.container(border=True):
    st.subheader("Top failure categories")
    failures = traces[~traces["succeeded"]]
    if failures.empty:
        st.caption("No failures logged yet.")
    else:
        category_counts = failures["category"].value_counts().reset_index()
        category_counts.columns = ["category", "count"]
        # Explicit "critical" status color, matching the accuracy chart's
        # "good" green - these two charts read as a pair.
        st.bar_chart(
            category_counts,
            x="category",
            y="count",
            x_label="Failure category",
            y_label="Count",
            color="#d03b3b",
        )

with st.expander("Raw traces"):
    st.dataframe(
        traces[["timestamp", "question", "model", "succeeded", "category", "attempt_count", "latency_seconds", "cost_usd"]],
        hide_index=True,
    )
