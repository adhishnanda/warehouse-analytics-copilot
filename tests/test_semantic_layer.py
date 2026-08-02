"""Verify the semantic layer: YAML shape, and no drift against the actual
DuckDB schema (documented tables/columns must exist; metric SQL must run).
"""

import sys
from pathlib import Path

import duckdb
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import DUCKDB_PATH, SEMANTIC_LAYER_DIR

pytestmark = pytest.mark.skipif(
    not DUCKDB_PATH.exists(),
    reason="warehouse.duckdb not built yet — run data/seed_warehouse.py",
)

TABLE_YML_FILES = sorted((SEMANTIC_LAYER_DIR / "tables").glob("*.yml"))
METRICS_FILE = SEMANTIC_LAYER_DIR / "metrics.yml"


@pytest.fixture(scope="module")
def con():
    connection = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    yield connection
    connection.close()


def test_table_yml_files_exist():
    assert len(TABLE_YML_FILES) == 6


@pytest.mark.parametrize("path", TABLE_YML_FILES, ids=lambda p: p.stem)
def test_table_doc_has_required_keys(path):
    doc = yaml.safe_load(path.read_text())
    assert doc["table"] == path.stem
    assert doc["description"].strip()
    assert doc["grain"].strip()
    assert doc["columns"]
    for column, meta in doc["columns"].items():
        assert meta["type"], f"{path.stem}.{column} missing type"
        assert meta["description"].strip(), f"{path.stem}.{column} missing description"


@pytest.mark.parametrize("path", TABLE_YML_FILES, ids=lambda p: p.stem)
def test_table_doc_matches_actual_schema(con, path):
    doc = yaml.safe_load(path.read_text())
    table = doc["table"]

    actual_columns = {
        row[1] for row in con.execute(f"PRAGMA table_info('{table}')").fetchall()
    }
    documented_columns = set(doc["columns"].keys())

    missing_from_db = documented_columns - actual_columns
    missing_from_docs = actual_columns - documented_columns

    assert not missing_from_db, f"{table}: documented columns not in DB: {missing_from_db}"
    assert not missing_from_docs, f"{table}: DB columns not documented: {missing_from_docs}"


def test_metrics_file_has_required_keys():
    metrics = yaml.safe_load(METRICS_FILE.read_text())
    assert len(metrics) >= 3
    for name, meta in metrics.items():
        assert meta["description"].strip(), f"{name} missing description"
        assert meta["sql"].strip(), f"{name} missing sql"


def test_metrics_sql_executes_and_returns_a_value(con):
    metrics = yaml.safe_load(METRICS_FILE.read_text())
    for name, meta in metrics.items():
        result = con.execute(meta["sql"]).fetchone()
        assert result is not None, f"{name}: query returned no row"
        assert result[0] is not None, f"{name}: query returned NULL"
