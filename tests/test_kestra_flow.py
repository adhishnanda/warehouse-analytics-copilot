"""Structural checks on the Kestra nightly refresh flow YAML
(orchestration/kestra/refresh_flow.yml). Not a substitute for actually
running the flow against a live Kestra instance (see SESSION_LOG.md, Day
19, for what was and wasn't verified live) — this only catches YAML
corruption or accidental schema drift on future edits.
"""

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import REPO_ROOT

FLOW_PATH = REPO_ROOT / "orchestration" / "kestra" / "refresh_flow.yml"


@pytest.fixture(scope="module")
def flow() -> dict:
    return yaml.safe_load(FLOW_PATH.read_text(encoding="utf-8"))


def test_flow_has_required_top_level_keys(flow):
    assert flow["id"] == "warehouse_nightly_refresh"
    assert flow["namespace"] == "warehouse.analytics.copilot"
    assert "tasks" in flow
    assert "triggers" in flow


def test_flow_has_exactly_two_tasks_in_order(flow):
    task_ids = [t["id"] for t in flow["tasks"]]
    assert task_ids == ["refresh_warehouse", "refresh_telemetry"]


@pytest.mark.parametrize("task_id", ["refresh_warehouse", "refresh_telemetry"])
def test_each_task_runs_in_the_project_docker_image(flow, task_id):
    task = next(t for t in flow["tasks"] if t["id"] == task_id)
    assert task["type"] == "io.kestra.plugin.scripts.shell.Commands"
    assert task["containerImage"] == "warehouse-analytics-copilot:latest"
    assert task["taskRunner"]["type"] == "io.kestra.plugin.scripts.runner.docker.Docker"


def test_tasks_share_the_same_named_volume(flow):
    for task_id in ("refresh_warehouse", "refresh_telemetry"):
        task = next(t for t in flow["tasks"] if t["id"] == task_id)
        assert task["taskRunner"]["volumes"] == ["warehouse_data:/app/data"]


def test_tasks_cd_into_app_before_running_uv():
    """A real bug caught by live execution: Kestra's Docker task runner
    sets its own per-task working directory, not the image's WORKDIR, so
    a bare `uv run python scripts/...` fails with FileNotFoundError.
    """
    flow_text = FLOW_PATH.read_text(encoding="utf-8")
    assert "cd /app && uv run python scripts/seed_and_index.py" in flow_text
    assert "cd /app && uv run python -m src.telemetry.dlt_pipeline" in flow_text


def test_nightly_trigger_is_a_valid_schedule(flow):
    triggers = flow["triggers"]
    assert len(triggers) == 1
    trigger = triggers[0]
    assert trigger["type"] == "io.kestra.plugin.core.trigger.Schedule"
    assert len(trigger["cron"].split()) == 5
