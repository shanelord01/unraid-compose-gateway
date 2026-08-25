from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from unraid_compose_gateway import compose_control
from tests.conftest import make_compose_project


def test_list_projects_reports_missing_compose_file(settings):
    projects = compose_control.list_projects(settings)
    names = {p.name: p for p in projects}
    assert set(names) == {"app", "protected"}
    assert names["app"].exists is False
    assert names["protected"].self_excluded is True


def test_list_projects_reports_existing(settings):
    make_compose_project(_dir(settings), "app")
    projects = compose_control.list_projects(settings)
    assert next(p for p in projects if p.name == "app").exists is True


def test_list_projects_autostart_true(settings):
    make_compose_project(_dir(settings), "app")
    (_dir(settings) / "app" / "autostart").write_text("true")
    projects = compose_control.list_projects(settings)
    assert next(p for p in projects if p.name == "app").autostart is True


def test_list_projects_autostart_false(settings):
    make_compose_project(_dir(settings), "app")
    (_dir(settings) / "app" / "autostart").write_text("false")
    projects = compose_control.list_projects(settings)
    assert next(p for p in projects if p.name == "app").autostart is False


def test_list_projects_autostart_missing_file_is_none(settings):
    make_compose_project(_dir(settings), "app")
    projects = compose_control.list_projects(settings)
    assert next(p for p in projects if p.name == "app").autostart is None


def test_list_projects_autostart_malformed_content_is_none(settings):
    make_compose_project(_dir(settings), "app")
    (_dir(settings) / "app" / "autostart").write_text("yes please\n")
    projects = compose_control.list_projects(settings)
    assert next(p for p in projects if p.name == "app").autostart is None


def test_run_action_rejects_project_not_in_allowlist(settings):
    with pytest.raises(compose_control.ProjectNotAllowed):
        compose_control.run_action("not-allowed", "restart", settings)


def test_run_action_rejects_self_excluded_project(settings):
    make_compose_project(_dir(settings), "protected")
    with pytest.raises(compose_control.ProjectSelfExcluded):
        compose_control.run_action("protected", "restart", settings)


def test_run_action_rejects_self_excluded_regardless_of_action(settings):
    make_compose_project(_dir(settings), "protected")
    for action in ("up", "down", "restart"):
        with pytest.raises(compose_control.ProjectSelfExcluded):
            compose_control.run_action("protected", action, settings)


def test_pull_is_exempt_from_self_exclusion(settings):
    """Pulling images does not touch a running container, so a self-excluded
    project can still have its images refreshed - only `up` is blocked."""
    make_compose_project(_dir(settings), "protected")
    with patch("unraid_compose_gateway.compose_control.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="pulled\n", stderr="")
        result = compose_control.run_action("protected", "pull", settings)
    assert result.exit_code == 0
    assert result.action == "pull"


def test_up_still_blocked_after_pull_on_self_excluded_project(settings):
    make_compose_project(_dir(settings), "protected")
    with pytest.raises(compose_control.ProjectSelfExcluded):
        compose_control.run_action("protected", "up", settings)


def test_run_action_rejects_missing_compose_file(settings):
    with pytest.raises(compose_control.ProjectNotFound):
        compose_control.run_action("app", "restart", settings)


def test_get_status_read_only_allowed_even_for_self_excluded(settings):
    """Reading status is not a control operation, so the self-exclude list
    must not block it - only mutating actions are gated."""
    make_compose_project(_dir(settings), "protected")
    with patch("unraid_compose_gateway.compose_control._run_compose") as run_compose:
        run_compose.return_value = compose_control._RunResult(exit_code=0, output="[]")
        services = compose_control.get_status("protected", settings)
    assert services == []


def test_run_action_success_invokes_expected_docker_compose_command(settings):
    make_compose_project(_dir(settings), "app")
    with patch("unraid_compose_gateway.compose_control.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="done\n", stderr="")
        result = compose_control.run_action("app", "restart", settings)

    assert result.exit_code == 0
    assert result.action == "restart"
    called_command = run.call_args.args[0]
    assert called_command[:2] == ["docker", "compose"]
    # Deliberately no -p: the project name is left for Compose to infer from
    # the file's own `name:` field, matching how Unraid's Compose Manager
    # itself invokes compose (directory names and declared project names
    # routinely differ there, e.g. dir "Hermes" / name: hermes).
    assert "-p" not in called_command
    assert called_command[-1] == "restart"


def test_run_action_runs_with_project_directory_as_cwd(settings):
    make_compose_project(_dir(settings), "app")
    with patch("unraid_compose_gateway.compose_control.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="done\n", stderr="")
        compose_control.run_action("app", "restart", settings)
    assert run.call_args.kwargs["cwd"] == str(_dir(settings) / "app")


def test_run_action_includes_override_file_when_present(settings):
    project_dir = _dir(settings) / "app"
    make_compose_project(_dir(settings), "app")
    (project_dir / "docker-compose.override.yml").write_text("services: {}\n")
    with patch("unraid_compose_gateway.compose_control.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="done\n", stderr="")
        compose_control.run_action("app", "up", settings, force=True)
    called_command = run.call_args.args[0]
    assert called_command.count("-f") == 2
    assert str(project_dir / "docker-compose.override.yml") in called_command


def test_run_action_omits_override_flag_when_no_override_file(settings):
    make_compose_project(_dir(settings), "app")
    with patch("unraid_compose_gateway.compose_control.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="done\n", stderr="")
        compose_control.run_action("app", "up", settings, force=True)
    called_command = run.call_args.args[0]
    assert called_command.count("-f") == 1


def test_run_action_raises_on_nonzero_exit(settings):
    make_compose_project(_dir(settings), "app")
    with patch("unraid_compose_gateway.compose_control.subprocess.run") as run:
        run.return_value = MagicMock(returncode=1, stdout="", stderr="boom")
        with pytest.raises(compose_control.ComposeCommandFailed) as excinfo:
            compose_control.run_action("app", "up", settings)
    assert "boom" in excinfo.value.output


def test_parse_ps_output_handles_jsonl():
    raw = '{"Service": "web", "State": "running", "Health": "healthy"}\n{"Service": "db", "State": "exited"}'
    services = compose_control._parse_ps_output(raw)
    assert [s.name for s in services] == ["web", "db"]
    assert services[0].health == "healthy"
    assert services[1].health is None


def test_parse_ps_output_handles_json_array():
    raw = '[{"Service": "web", "State": "running"}]'
    services = compose_control._parse_ps_output(raw)
    assert len(services) == 1
    assert services[0].name == "web"


def test_parse_ps_output_handles_empty():
    assert compose_control._parse_ps_output("") == []
    assert compose_control._parse_ps_output("   ") == []


def _dir(settings):
    from pathlib import Path

    return Path(settings.compose_projects_dir)
