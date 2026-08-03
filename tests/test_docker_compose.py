"""Structural checks on docker-compose.yml. Mostly pure YAML parsing
(fast, no Docker dependency) plus one live syntax-validation test that
skips if Docker isn't available. Never prints resolved config, since
`docker compose config` (without --quiet) interpolates secrets from
.env directly into its output - see SESSION_LOG.md, Day 20, for why
that matters here.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import REPO_ROOT

COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
APP_IMAGE = "warehouse-analytics-copilot:latest"
APP_SERVICES = ("seed", "api", "ui", "monitoring")


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def test_compose_defines_the_expected_services(compose):
    expected = {"seed", "api", "ui", "monitoring", "kestra-db", "kestra"}
    assert expected <= set(compose["services"].keys())


@pytest.mark.parametrize("service_name", APP_SERVICES)
def test_app_services_are_built_and_tagged_consistently(compose, service_name):
    """All four app services must resolve to the same explicit image
    tag, not compose's default per-service naming - the Kestra flow
    (orchestration/kestra/refresh_flow.yml) references this exact tag.
    """
    service = compose["services"][service_name]
    assert service["build"] == "."
    assert service["image"] == APP_IMAGE


@pytest.mark.parametrize("service_name", APP_SERVICES)
def test_app_services_share_the_named_data_volume(compose, service_name):
    service = compose["services"][service_name]
    assert "warehouse_data:/app/data" in service["volumes"]


def test_openai_api_key_is_never_interpolated_in_compose():
    """Regression check: docker compose config prints fully-resolved
    env values, including secrets from .env, unless a variable is left
    un-interpolated. OPENAI_API_KEY must never appear as ${...} here.
    """
    text = COMPOSE_PATH.read_text(encoding="utf-8")
    assert "${OPENAI_API_KEY" not in text


def test_kestra_uses_postgres_backend_and_enables_docker_volumes(compose):
    kestra = compose["services"]["kestra"]
    config_text = kestra["environment"]["KESTRA_CONFIGURATION"]
    config = yaml.safe_load(config_text)
    assert config["kestra"]["repository"]["type"] == "postgres"
    assert config["kestra"]["queue"]["type"] == "postgres"
    docker_runner_config = config["kestra"]["plugins"]["configurations"][0]
    assert docker_runner_config["type"] == "io.kestra.plugin.scripts.runner.docker.Docker"
    assert docker_runner_config["values"]["volume-enabled"] is True


def test_kestra_mounts_the_docker_socket_and_runs_as_root(compose):
    """Both needed for Kestra to launch the flow's sibling task
    containers under Docker Desktop - see SESSION_LOG.md, Days 19-20."""
    kestra = compose["services"]["kestra"]
    assert "/var/run/docker.sock:/var/run/docker.sock" in kestra["volumes"]
    assert kestra["user"] == "root"


def test_kestra_db_is_healthchecked_before_kestra_starts(compose):
    kestra = compose["services"]["kestra"]
    assert kestra["depends_on"]["kestra-db"]["condition"] == "service_healthy"
    assert "healthcheck" in compose["services"]["kestra-db"]


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI not available")
def test_compose_file_is_syntactically_valid():
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_PATH), "config", "--quiet"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
