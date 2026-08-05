"""Structural checks on render.yaml, mirroring tests/test_docker_compose.py.
Pure YAML parsing - not a substitute for an actual Render deploy, which
needs an account and GitHub connection no test or agent can automate
(see docs/setup.md's "Deploying to Render").
"""

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import REPO_ROOT

RENDER_YAML_PATH = REPO_ROOT / "render.yaml"


@pytest.fixture(scope="module")
def blueprint() -> dict:
    return yaml.safe_load(RENDER_YAML_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def service(blueprint) -> dict:
    assert len(blueprint["services"]) == 1
    return blueprint["services"][0]


def test_service_uses_the_project_dockerfile(service):
    assert service["runtime"] == "docker"
    assert service["dockerfilePath"] == "./Dockerfile"


def test_service_is_on_the_free_plan(service):
    assert service["plan"] == "free"


def test_service_has_a_health_check(service):
    assert service["healthCheckPath"] == "/health"


def test_openai_api_key_is_never_committed_as_a_value(service):
    """Regression check, same spirit as docker-compose.yml's equivalent
    test: OPENAI_API_KEY must be sync: false (Render prompts for it in
    the dashboard) and never given a literal value in this file.
    """
    env_vars = {v["key"]: v for v in service["envVars"]}
    assert env_vars["OPENAI_API_KEY"]["sync"] is False
    assert "value" not in env_vars["OPENAI_API_KEY"]


def test_public_deploy_defaults_to_the_paid_backend_with_a_query_cap(service):
    """Local Ollama isn't deployable on a free-tier host (see docs/setup.md),
    so the public deploy must default to the paid backend - and must set a
    cap, since an anonymous public URL on an uncapped paid backend is an
    open-ended cost/abuse exposure.
    """
    env_vars = {v["key"]: v for v in service["envVars"]}
    assert env_vars["AGENT_CHAT_BACKEND"]["value"] == "openai"
    assert "MAX_DAILY_QUERIES" in env_vars
    assert int(env_vars["MAX_DAILY_QUERIES"]["value"]) > 0
