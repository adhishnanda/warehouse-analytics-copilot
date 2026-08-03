"""Writes one JSON line per query trace or feedback event.

Deliberately a plain append-only log, not a database write: this is the
raw capture point every API call goes through, and Day 17's dlt pipeline
(dlt_pipeline.py) is responsible for turning this log into queryable
DuckDB telemetry tables. Keeping the write path this simple means the
live request path never blocks on, or fails because of, the warehouse
connection.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.config import TRACE_LOG_PATH


@dataclass
class TraceEvent:
    event_type: str
    query_id: str
    timestamp: str
    question: str
    sql: str | None
    succeeded: bool
    error: str | None
    attempt_count: int
    row_count: int | None
    latency_seconds: float
    model: str
    usage: dict = field(default_factory=dict)


@dataclass
class FeedbackEvent:
    event_type: str
    query_id: str
    timestamp: str
    vote: str


def _append(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


def log_trace(
    query_id: str,
    question: str,
    sql: str | None,
    succeeded: bool,
    error: str | None,
    attempt_count: int,
    row_count: int | None,
    latency_seconds: float,
    model: str,
    usage: dict | None = None,
    path: Path = TRACE_LOG_PATH,
) -> TraceEvent:
    event = TraceEvent(
        event_type="trace",
        query_id=query_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        question=question,
        sql=sql,
        succeeded=succeeded,
        error=error,
        attempt_count=attempt_count,
        row_count=row_count,
        latency_seconds=latency_seconds,
        model=model,
        usage=usage or {},
    )
    _append(path, asdict(event))
    return event


def log_feedback(query_id: str, vote: str, path: Path = TRACE_LOG_PATH) -> FeedbackEvent:
    if vote not in ("up", "down"):
        raise ValueError(f"vote must be 'up' or 'down', got {vote!r}")
    event = FeedbackEvent(
        event_type="feedback",
        query_id=query_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        vote=vote,
    )
    _append(path, asdict(event))
    return event
