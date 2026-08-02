"""Verify the golden question set: shape, tier balance, and that every
gold SQL statement actually executes against the real warehouse and
matches its recorded reference result exactly.

This is what keeps evaluation/golden_questions.jsonl trustworthy as ground
truth for the Week 2 evaluation scripts — if the warehouse schema ever
drifts, this is what catches it, the same way test_semantic_layer.py
catches drift in the YAML docs.
"""

import datetime
import decimal
import json
import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import DUCKDB_PATH, REPO_ROOT

GOLDEN_PATH = REPO_ROOT / "evaluation" / "golden_questions.jsonl"

pytestmark = pytest.mark.skipif(
    not (DUCKDB_PATH.exists() and GOLDEN_PATH.exists()),
    reason="warehouse or golden question set not built yet",
)


def _load_records() -> list[dict]:
    with open(GOLDEN_PATH, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


@pytest.fixture(scope="module")
def records():
    return _load_records()


@pytest.fixture(scope="module")
def con():
    connection = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    yield connection
    connection.close()


def test_golden_set_has_50_questions(records):
    assert len(records) == 50


def test_golden_set_ids_are_unique(records):
    ids = [r["id"] for r in records]
    assert len(ids) == len(set(ids))


def test_tier_distribution_matches_plan(records):
    tier_counts = {1: 0, 2: 0, 3: 0}
    for r in records:
        tier_counts[r["tier"]] += 1
    assert tier_counts == {1: 20, 2: 20, 3: 10}


@pytest.mark.parametrize("required_key", ["id", "tier", "question", "sql", "relevant_doc_ids", "reference_result"])
def test_every_record_has_required_fields(records, required_key):
    for r in records:
        assert required_key in r, f"{r.get('id', '?')} missing '{required_key}'"


def test_every_record_has_at_least_one_relevant_doc(records):
    for r in records:
        assert len(r["relevant_doc_ids"]) > 0, f"{r['id']} has no relevant_doc_ids"


def test_tier1_questions_touch_exactly_one_table(records):
    for r in records:
        if r["tier"] != 1:
            continue
        table_docs = [d for d in r["relevant_doc_ids"] if d.startswith("table:")]
        assert len(table_docs) == 1, f"{r['id']} (tier 1) should touch exactly one table doc"


def test_tier3_questions_reference_a_metric_doc(records):
    for r in records:
        if r["tier"] != 3:
            continue
        metric_docs = [d for d in r["relevant_doc_ids"] if d.startswith("metric:")]
        assert len(metric_docs) >= 1, f"{r['id']} (tier 3) should reference at least one metric doc"


def _normalize(value):
    # Match the conversion applied when the reference results were recorded
    # (see the golden-set build script): Decimal -> float, date -> isoformat.
    # Comparing a raw Decimal to its own float conversion is False due to
    # floating-point imprecision, so both sides must go through this.
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value


@pytest.mark.parametrize("record", _load_records(), ids=lambda r: r["id"])
def test_gold_sql_executes_and_matches_reference_result(con, record):
    actual = con.execute(record["sql"]).fetchall()
    actual_normalized = [[_normalize(value) for value in row] for row in actual]
    assert actual_normalized == record["reference_result"], (
        f"{record['id']}: live execution {actual_normalized} != "
        f"recorded reference {record['reference_result']}"
    )
