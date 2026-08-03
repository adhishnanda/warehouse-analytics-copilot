"""dlt pipeline: loads trace/feedback events from the JSONL log written
by src/telemetry/logger.py (via src/app/api.py) into DuckDB tables, so
the monitoring dashboard (Day 18) can query historical usage with SQL
instead of re-parsing the raw log on every render.

Loads into a separate telemetry.duckdb, not the warehouse — see
TELEMETRY_DB_PATH in src/config.py for why. write_disposition="merge"
on query_id makes reruns idempotent: re-running against a JSONL file
that already contains previously-loaded lines does not duplicate rows,
since every trace event is one immutable row per query_id and a
feedback event overwrites any earlier vote for the same query_id
(latest vote wins).
"""

from __future__ import annotations

import json
from pathlib import Path

import dlt

from src.config import TELEMETRY_DB_PATH, TRACE_LOG_PATH

PIPELINE_NAME = "warehouse_analytics_telemetry"
# Deliberately not "telemetry" - the DuckDB catalog name (from the
# telemetry.duckdb filename) would then collide with the dataset/schema
# name, and dlt's schema-versioning queries raise "Ambiguous reference
# to catalog or schema" against DuckDB when the two match.
DATASET_NAME = "telemetry_events"


def _read_events(jsonl_path: Path, event_type: str):
    if not jsonl_path.exists():
        return
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("event_type") == event_type:
                yield record


def make_source(jsonl_path: Path = TRACE_LOG_PATH):
    @dlt.resource(
        name="traces",
        primary_key="query_id",
        write_disposition="merge",
        # error/sql are frequently all-null within a single load batch
        # (e.g. every trace in a run succeeded), which leaves dlt unable
        # to infer their type from the data alone.
        columns={"error": {"data_type": "text"}, "sql": {"data_type": "text"}},
    )
    def traces_resource():
        yield from _read_events(jsonl_path, "trace")

    @dlt.resource(
        name="feedback",
        primary_key="query_id",
        write_disposition="merge",
        # If two feedback events for the same query_id land in the same
        # load batch (the UI disables re-voting, but the API doesn't
        # enforce that), keep the one with the latest timestamp rather
        # than whichever dlt happened to see first.
        columns={"timestamp": {"dedup_sort": "desc"}},
    )
    def feedback_resource():
        yield from _read_events(jsonl_path, "feedback")

    @dlt.source(name="telemetry")
    def telemetry_source():
        return [traces_resource(), feedback_resource()]

    return telemetry_source()


def run_pipeline(jsonl_path: Path = TRACE_LOG_PATH, db_path: Path = TELEMETRY_DB_PATH):
    pipeline = dlt.pipeline(
        pipeline_name=PIPELINE_NAME,
        destination=dlt.destinations.duckdb(str(db_path)),
        dataset_name=DATASET_NAME,
    )
    return pipeline.run(make_source(jsonl_path))


if __name__ == "__main__":
    load_info = run_pipeline()
    print(load_info)
