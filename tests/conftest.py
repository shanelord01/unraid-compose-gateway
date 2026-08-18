from __future__ import annotations

import pytest

from compose_sentry.config import Settings


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
