"""JSON API for the monitoring frontend (frontend/src/components/monitoring).

Ports monitoring/dashboard.py's DuckDB-reading glue to HTTP endpoints, since
a browser can't open data/telemetry.duckdb directly the way Streamlit did.
All the actual data-prep logic (cost, percentiles, error categorisation) is
reused unchanged from monitoring/metrics.py - this module only adds the
query/aggregation layer and the HTTP surface.

TELEMETRY_DB_PATH is referenced directly in each function body rather than
as a bound default argument, so tests can monkeypatch this module's
TELEMETRY_DB_PATH attribute per-test (the same pattern src/app/api.py uses
for TRACE_LOG_PATH, after Day 15-16's bug where a bound default silently
ignored monkeypatching).
"""

from __future__ import annotations

import duckdb
import pandas as pd
from fastapi import APIRouter
from pydantic import BaseModel

from monitoring.metrics import categorize_error, compute_cost_usd, compute_percentiles
from src.config import TELEMETRY_DB_PATH
from src.telemetry.dlt_pipeline import DATASET_NAME, run_pipeline

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


def _table_exists(con: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    result = con.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema = ? AND table_name = ?",
        [DATASET_NAME, table_name],
    ).fetchone()
    return result is not None


def _load_table(table_name: str) -> pd.DataFrame:
    if not TELEMETRY_DB_PATH.exists():
        return pd.DataFrame()
    con = duckdb.connect(str(TELEMETRY_DB_PATH), read_only=True)
    try:
        if not _table_exists(con, table_name):
            return pd.DataFrame()
        return con.execute(f"SELECT * FROM {DATASET_NAME}.{table_name}").df()
    finally:
        con.close()


def _load_traces() -> pd.DataFrame:
    traces = _load_table("traces")
    if traces.empty:
        return traces

    traces["date"] = pd.to_datetime(traces["timestamp"]).dt.date.astype(str)
    traces["category"] = traces["error"].apply(categorize_error)

    for usage_col in ("usage__prompt_tokens", "usage__completion_tokens"):
        if usage_col not in traces.columns:
            traces[usage_col] = 0
        traces[usage_col] = traces[usage_col].fillna(0)

    traces["cost_usd"] = traces.apply(
        lambda r: compute_cost_usd(r["model"], int(r["usage__prompt_tokens"]), int(r["usage__completion_tokens"])),
        axis=1,
    )
    return traces


class SummaryResponse(BaseModel):
    total_queries: int
    execution_accuracy: float
    total_cost_usd: float
    feedback_rate: float
    helpful_count: int
    not_helpful_count: int
    latency_p50_seconds: float
    latency_p95_seconds: float


@router.get("/summary", response_model=SummaryResponse)
def summary() -> SummaryResponse:
    traces = _load_traces()
    feedback = _load_table("feedback")

    if traces.empty:
        return SummaryResponse(
            total_queries=0,
            execution_accuracy=0.0,
            total_cost_usd=0.0,
            feedback_rate=0.0,
            helpful_count=0,
            not_helpful_count=0,
            latency_p50_seconds=0.0,
            latency_p95_seconds=0.0,
        )

    percentiles = compute_percentiles(traces["latency_seconds"].tolist())
    helpful_count = int((feedback["vote"] == "up").sum()) if not feedback.empty else 0
    not_helpful_count = int((feedback["vote"] == "down").sum()) if not feedback.empty else 0

    return SummaryResponse(
        total_queries=len(traces),
        execution_accuracy=float(traces["succeeded"].mean()),
        total_cost_usd=float(traces["cost_usd"].sum()),
        feedback_rate=(len(feedback) / len(traces)) if len(traces) else 0.0,
        helpful_count=helpful_count,
        not_helpful_count=not_helpful_count,
        latency_p50_seconds=percentiles[0.5],
        latency_p95_seconds=percentiles[0.95],
    )


class TimeseriesPoint(BaseModel):
    date: str
    query_count: int
    execution_accuracy: float
    avg_cost_usd: float


class TimeseriesResponse(BaseModel):
    points: list[TimeseriesPoint]


@router.get("/timeseries", response_model=TimeseriesResponse)
def timeseries() -> TimeseriesResponse:
    traces = _load_traces()
    if traces.empty:
        return TimeseriesResponse(points=[])

    grouped = traces.groupby("date").agg(
        query_count=("query_id", "size"),
        execution_accuracy=("succeeded", "mean"),
        avg_cost_usd=("cost_usd", "mean"),
    )
    points = [
        TimeseriesPoint(
            date=str(date),
            query_count=int(row["query_count"]),
            execution_accuracy=float(row["execution_accuracy"]),
            avg_cost_usd=float(row["avg_cost_usd"]),
        )
        for date, row in grouped.sort_index().iterrows()
    ]
    return TimeseriesResponse(points=points)


class FailureCategory(BaseModel):
    category: str
    count: int


class FailuresResponse(BaseModel):
    categories: list[FailureCategory]


@router.get("/failures", response_model=FailuresResponse)
def failures() -> FailuresResponse:
    traces = _load_traces()
    if traces.empty:
        return FailuresResponse(categories=[])

    failed = traces[~traces["succeeded"]]
    if failed.empty:
        return FailuresResponse(categories=[])

    counts = failed["category"].value_counts()
    categories = [FailureCategory(category=str(category), count=int(count)) for category, count in counts.items()]
    return FailuresResponse(categories=categories)


class TraceRow(BaseModel):
    query_id: str
    timestamp: str
    question: str
    model: str
    succeeded: bool
    category: str
    attempt_count: int
    latency_seconds: float
    cost_usd: float


class TracesResponse(BaseModel):
    traces: list[TraceRow]
    total: int


@router.get("/traces", response_model=TracesResponse)
def traces_endpoint(limit: int = 100, offset: int = 0) -> TracesResponse:
    traces = _load_traces()
    if traces.empty:
        return TracesResponse(traces=[], total=0)

    ordered = traces.sort_values("timestamp", ascending=False)
    page = ordered.iloc[offset : offset + limit]

    rows = [
        TraceRow(
            query_id=row["query_id"],
            # DuckDB/pandas round-trips this as a tz-aware Timestamp, not
            # the original ISO string - isoformat() keeps it JSON-safe.
            timestamp=row["timestamp"].isoformat(),
            question=row["question"],
            model=row["model"],
            succeeded=bool(row["succeeded"]),
            category=row["category"],
            attempt_count=int(row["attempt_count"]),
            latency_seconds=float(row["latency_seconds"]),
            cost_usd=float(row["cost_usd"]),
        )
        for _, row in page.iterrows()
    ]
    return TracesResponse(traces=rows, total=len(traces))


@router.post("/refresh")
def refresh() -> dict:
    run_pipeline()
    return {"ok": True}
