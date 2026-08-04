"""Structural checks on the Kestra synthetic-traffic flow YAML
(orchestration/kestra/synthetic_traffic_flow.yml). Mirrors
tests/test_kestra_flow.py - not a substitute for actually running the
flow against a live Kestra instance, only a guard against YAML
corruption or accidental schema drift on future edits.
"""

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import REPO_ROOT

FLOW_PATH = REPO_ROOT / "orchestration" / "kestra" / "synthetic_traffic_flow.yml"


@pytest.fixture(scope="module")
def flow() -> dict:
    return yaml.safe_load(FLOW_PATH.read_text(encoding="utf-8"))


def test_flow_has_required_top_level_keys(flow):
    assert flow["id"] == "warehouse_synthetic_traffic"
    assert flow["namespace"] == "warehouse.analytics.copilot"
    assert "tasks" in flow
    assert "triggers" in flow


def test_flow_has_exactly_two_tasks_in_order(flow):
    task_ids = [t["id"] for t in flow["tasks"]]
    assert task_ids == ["generate_traffic", "refresh_telemetry"]


@pytest.mark.parametrize("task_id", ["generate_traffic", "refresh_telemetry"])
def test_each_task_runs_in_the_project_docker_image(flow, task_id):
    task = next(t for t in flow["tasks"] if t["id"] == task_id)
    assert task["type"] == "io.kestra.plugin.scripts.shell.Commands"
    assert task["containerImage"] == "warehouse-analytics-copilot:latest"
    assert task["taskRunner"]["type"] == "io.kestra.plugin.scripts.runner.docker.Docker"


def test_tasks_share_the_same_named_volume(flow):
    for task_id in ("generate_traffic", "refresh_telemetry"):
        task = next(t for t in flow["tasks"] if t["id"] == task_id)
        assert task["taskRunner"]["volumes"] == ["warehouse_data:/app/data"]


def test_generate_traffic_overrides_ollama_base_url_for_the_container(flow):
    task = next(t for t in flow["tasks"] if t["id"] == "generate_traffic")
    assert task["env"]["OLLAMA_BASE_URL"] == "http://host.docker.internal:11434"


def test_tasks_cd_into_app_before_running_uv():
    """Same real bug class caught in refresh_flow.yml (Day 19): Kestra's
    Docker task runner sets its own per-task working directory, not the
    image's WORKDIR, so a bare `uv run python ...` fails.
    """
    flow_text = FLOW_PATH.read_text(encoding="utf-8")
    assert "cd /app && uv run python scripts/generate_synthetic_traffic.py" in flow_text
    assert "cd /app && uv run python -m src.telemetry.dlt_pipeline" in flow_text


def test_daily_trigger_is_a_valid_schedule(flow):
    triggers = flow["triggers"]
    assert len(triggers) == 1
    trigger = triggers[0]
    assert trigger["type"] == "io.kestra.plugin.core.trigger.Schedule"
    assert len(trigger["cron"].split()) == 5


def test_trigger_runs_after_the_nightly_warehouse_refresh():
    """Scheduled at 06:00, after refresh_flow.yml's 02:00 warehouse
    refresh, so synthetic traffic runs against that day's freshly seeded
    data rather than racing it (TPC-H reseeding is deterministic so this
    doesn't change correctness, but keeps the two flows' real-world
    ordering sane for anyone reading the schedule).
    """
    flow = yaml.safe_load(FLOW_PATH.read_text(encoding="utf-8"))
    refresh_flow = yaml.safe_load(
        (REPO_ROOT / "orchestration" / "kestra" / "refresh_flow.yml").read_text(encoding="utf-8")
    )
    this_hour = int(flow["triggers"][0]["cron"].split()[1])
    refresh_hour = int(refresh_flow["triggers"][0]["cron"].split()[1])
    assert this_hour > refresh_hour
