from __future__ import annotations

from unittest.mock import patch

import pytest

from unraid_compose_gateway import compose_version
from unraid_compose_gateway.config import Settings


@pytest.fixture(autouse=True)
def _no_real_docker_for_version_checks():
    """Unit tests must never reach a real Docker daemon. compose_version._run
    is stubbed to fail unless a test patches it itself (an inner patch wins),
    and the cached gateway version is cleared around every test so nothing
    leaks between them."""
    compose_version.gateway_compose_version.cache_clear()
    with patch(
        "unraid_compose_gateway.compose_version._run",
        side_effect=RuntimeError("docker is not available in unit tests"),
    ):
        yield
    compose_version.gateway_compose_version.cache_clear()


@pytest.fixture
def settings(tmp_path) -> Settings:
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    return Settings(
        token="test-token-value",
        allowed_projects=["app", "protected"],
        self_exclude_projects=["protected"],
        compose_projects_dir=str(projects_dir),
        plugin_dir=None,
        plugin_cache_seconds=1800,
        log_tail_default=200,
        log_tail_max=5000,
        compose_timeout_seconds=5,
        port=8080,
    )


def make_compose_project(base_dir, name: str) -> None:
    project_dir = base_dir / name
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "docker-compose.yml").write_text("services: {}\n")
