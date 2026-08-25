from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from unraid_compose_gateway import compose_control, compose_version
from tests.conftest import make_compose_project


def _completed(stdout: str = "", returncode: int = 0, stderr: str = "") -> MagicMock:
    m = MagicMock()
    m.stdout = stdout
    m.stderr = stderr
    m.returncode = returncode
    return m


def _fake_run(version: str, inspect_output: str = "", ps_output: str = ""):
    """Stand-in for compose_version._run keyed on the docker subcommand, so a
    test can patch it without also capturing compose_control's subprocess
    calls (both modules share the one `subprocess.run`)."""

    def run(command, timeout):  # noqa: ANN001
        if command[:3] == ["docker", "compose", "version"]:
            return version + "\n"
        if command[:2] == ["docker", "inspect"]:
            return inspect_output
        if command[:2] == ["docker", "ps"]:
            return ps_output
        raise AssertionError(f"unexpected command {command}")

    return run


def test_versions_for_containers_dedupes_and_sorts(settings):
    with patch("unraid_compose_gateway.compose_version._run") as run:
        run.return_value = "2.40.3\n5.5.0\n2.40.3\n"
        assert compose_version.versions_for_containers(["a", "b", "c"], settings) == ["2.40.3", "5.5.0"]
        assert run.call_args.args[0][:3] == ["docker", "inspect", "--format"]
        assert run.call_args.args[0][-3:] == ["a", "b", "c"]


def test_versions_for_containers_empty_ids_never_calls_docker(settings):
    with patch("unraid_compose_gateway.compose_version._run") as run:
        assert compose_version.versions_for_containers([], settings) == []
        assert compose_version.versions_for_containers(["", "  "], settings) == []
        run.assert_not_called()


def test_assert_parity_passes_when_versions_match(settings):
    with patch("unraid_compose_gateway.compose_version._run", _fake_run("2.40.3", "2.40.3\n2.40.3\n")):
        compose_version.assert_parity("app", ["a", "b"], settings)


def test_assert_parity_passes_when_project_has_no_containers(settings):
    with patch("unraid_compose_gateway.compose_version._run") as run:
        compose_version.assert_parity("app", [], settings)
        run.assert_not_called()


def test_assert_parity_raises_on_mismatch(settings):
    with patch("unraid_compose_gateway.compose_version._run", _fake_run("2.40.3", "5.5.0\n")):
        with pytest.raises(compose_version.ComposeVersionMismatch) as excinfo:
            compose_version.assert_parity("app", ["a"], settings)
    assert excinfo.value.gateway_version == "2.40.3"
    assert excinfo.value.container_versions == ["5.5.0"]
    assert "force=true" in str(excinfo.value)


def test_up_is_refused_on_version_mismatch_before_running_up(settings):
    make_compose_project(Path(settings.compose_projects_dir), "app")
    with patch("unraid_compose_gateway.compose_control.subprocess.run") as run_compose, patch(
        "unraid_compose_gateway.compose_version._run", _fake_run("2.40.3", "5.5.0\n")
    ):
        run_compose.return_value = _completed("abc123\n")  # docker compose ps -a -q
        with pytest.raises(compose_version.ComposeVersionMismatch):
            compose_control.run_action("app", "up", settings)
    # Only the `ps -a -q` call happened; `up -d` was never issued.
    assert run_compose.call_count == 1
    assert run_compose.call_args.args[0][-3:] == ["ps", "-a", "-q"]


def test_up_runs_when_versions_match(settings):
    make_compose_project(Path(settings.compose_projects_dir), "app")
    with patch("unraid_compose_gateway.compose_control.subprocess.run") as run_compose, patch(
        "unraid_compose_gateway.compose_version._run", _fake_run("2.40.3", "2.40.3\n")
    ):
        run_compose.side_effect = [_completed("abc123\n"), _completed("done\n")]
        result = compose_control.run_action("app", "up", settings)
    assert result.exit_code == 0
    assert run_compose.call_args_list[-1].args[0][-2:] == ["up", "-d"]


def test_up_with_force_skips_the_version_check(settings):
    make_compose_project(Path(settings.compose_projects_dir), "app")
    with patch("unraid_compose_gateway.compose_control.subprocess.run") as run_compose, patch(
        "unraid_compose_gateway.compose_version._run"
    ) as run_version:
        run_compose.return_value = _completed("done\n")
        compose_control.run_action("app", "up", settings, force=True)
    run_version.assert_not_called()
    assert run_compose.call_count == 1
    assert run_compose.call_args.args[0][-2:] == ["up", "-d"]


@pytest.mark.parametrize("action", ["restart", "down", "pull"])
def test_other_actions_are_not_version_guarded(settings, action):
    make_compose_project(Path(settings.compose_projects_dir), "app")
    with patch("unraid_compose_gateway.compose_control.subprocess.run") as run_compose, patch(
        "unraid_compose_gateway.compose_version._run"
    ) as run_version:
        run_compose.return_value = _completed("ok\n")
        compose_control.run_action("app", action, settings)
    run_version.assert_not_called()
    assert run_compose.call_count == 1


def test_host_versions_by_project_groups_versions(settings):
    with patch("unraid_compose_gateway.compose_version._run") as run:
        run.return_value = "observability\t5.5.0\nobservability\t5.5.0\nmealie\t2.40.3\n\t2.40.3\nbare\t\n"
        result = compose_version.host_versions_by_project(settings)
    assert result == {"observability": {"5.5.0"}, "mealie": {"2.40.3"}, "bare": set()}


def test_startup_report_warns_per_mismatched_project(settings, caplog):
    with patch(
        "unraid_compose_gateway.compose_version._run",
        _fake_run("2.40.3", ps_output="observability\t5.5.0\nmealie\t2.40.3\n"),
    ):
        with caplog.at_level("INFO", logger="unraid_compose_gateway"):
            compose_version.log_startup_report(settings)
    messages = [r.getMessage() for r in caplog.records]
    assert any("docker compose version in use: 2.40.3 (bundled)" in m for m in messages)
    assert any("project 'observability'" in m and "5.5.0" in m for m in messages)
    assert not any("project 'mealie'" in m for m in messages)


def test_startup_report_never_raises_when_docker_is_unavailable(settings, caplog):
    with patch("unraid_compose_gateway.compose_version._run", side_effect=RuntimeError("Cannot connect to the Docker daemon")):
        with caplog.at_level("WARNING", logger="unraid_compose_gateway"):
            compose_version.log_startup_report(settings)
    assert any("could not determine" in r.getMessage() for r in caplog.records)


def test_up_refuses_when_versions_cannot_be_read(settings):
    # conftest stubs compose_version._run to fail; the guard must turn that
    # into a ComposeCommandFailed, not run `up` and not leak a RuntimeError.
    make_compose_project(Path(settings.compose_projects_dir), "app")
    with patch("unraid_compose_gateway.compose_control.subprocess.run") as run_compose:
        run_compose.return_value = _completed("abc123\n")
        with pytest.raises(compose_control.ComposeCommandFailed) as excinfo:
            compose_control.run_action("app", "up", settings)
    assert "verify compose version parity" in str(excinfo.value)
    assert run_compose.call_count == 1
