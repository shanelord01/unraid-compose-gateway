from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from compose_sentry import compose_control, logs
from compose_sentry.app import app
from compose_sentry.state import get_settings


@pytest.fixture
def client(settings):
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def auth_headers(settings):
    return {"Authorization": f"Bearer {settings.token}"}


def test_healthz_requires_no_auth(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_whoami_rejects_missing_token(client):
    response = client.get("/v1/whoami")
    assert response.status_code == 401


def test_whoami_rejects_wrong_token(client):
    response = client.get("/v1/whoami", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


def test_whoami_accepts_correct_token(client, settings):
    response = client.get("/v1/whoami", headers=auth_headers(settings))
    assert response.status_code == 200
    body = response.json()
    assert body["allowed_projects"] == settings.allowed_projects
    assert body["self_exclude_projects"] == settings.self_exclude_projects
    assert body["plugin_updates_enabled"] is False


def test_compose_restart_on_self_excluded_project_returns_403(client, settings):
    response = client.post("/v1/compose/protected/restart", headers=auth_headers(settings))
    assert response.status_code == 403
    assert "SELF_EXCLUDE_PROJECTS" in response.json()["detail"]


def test_compose_restart_on_disallowed_project_returns_403(client, settings):
    response = client.post("/v1/compose/unknown-project/restart", headers=auth_headers(settings))
    assert response.status_code == 403
    assert "ALLOWED_PROJECTS" in response.json()["detail"]


def test_compose_restart_success(client, settings):
    with patch.object(compose_control, "run_action") as run_action:
        from compose_sentry.models import ComposeActionResult

        run_action.return_value = ComposeActionResult(
            project="app", action="restart", exit_code=0, output="ok"
        )
        response = client.post("/v1/compose/app/restart", headers=auth_headers(settings))
    assert response.status_code == 200
    assert response.json()["exit_code"] == 0


def test_container_logs_not_found_returns_404(client, settings):
    with patch.object(logs, "get_logs", side_effect=logs.ContainerNotFound("no container named 'x'")):
        response = client.get("/v1/containers/x/logs", headers=auth_headers(settings))
    assert response.status_code == 404


def test_container_logs_success_uses_default_tail(client, settings):
    with patch.object(logs, "get_logs", return_value=["line1", "line2"]) as get_logs:
        response = client.get("/v1/containers/web/logs", headers=auth_headers(settings))
    assert response.status_code == 200
    body = response.json()
    assert body["lines"] == ["line1", "line2"]
    assert body["tail"] == settings.log_tail_default
    get_logs.assert_called_once_with("web", settings.log_tail_default, None, settings)


def test_plugin_updates_disabled_returns_501(client, settings):
    # settings fixture has plugin_dir=None
    response = client.get("/v1/plugins/updates", headers=auth_headers(settings))
    assert response.status_code == 501
