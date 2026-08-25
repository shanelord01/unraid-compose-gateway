from __future__ import annotations

import hashlib
from dataclasses import replace
from unittest.mock import patch

import pytest

from unraid_compose_gateway import compose_sync, compose_version


def test_read_host_version_accepts_plain_and_v_prefixed(tmp_path):
    f = tmp_path / "v"
    f.write_text("2.40.3\n")
    assert compose_sync.read_host_version(str(f)) == "2.40.3"
    f.write_text("v2.41.0")
    assert compose_sync.read_host_version(str(f)) == "2.41.0"


@pytest.mark.parametrize("content", ["", "latest", "2.40", "2.40.3-rc1", "Docker Compose version v2.40.3", "; rm -rf /"])
def test_read_host_version_rejects_anything_that_is_not_a_version(tmp_path, content):
    f = tmp_path / "v"
    f.write_text(content)
    assert compose_sync.read_host_version(str(f)) is None


def test_read_host_version_missing_file_is_none(tmp_path):
    assert compose_sync.read_host_version(str(tmp_path / "nope")) is None


def _fake_fetch_factory(binary: bytes, checksum_line: str | None = None):
    calls = []

    def fetch(url, timeout):  # noqa: ANN001
        calls.append(url)
        if url.endswith(".sha256"):
            line = checksum_line if checksum_line is not None else f"{hashlib.sha256(binary).hexdigest()}  {compose_sync.asset_name()}\n"
            return line.encode()
        return binary

    fetch.calls = calls
    return fetch


def test_download_release_verifies_sha256_and_writes_executable(tmp_path):
    fetch = _fake_fetch_factory(b"#!/bin/sh\necho fake\n")
    result = compose_sync.download_release("2.41.0", str(tmp_path), fetch=fetch)
    assert result.version == "2.41.0"
    assert result.path == str(tmp_path / "2.41.0" / "docker-compose")
    assert (tmp_path / "2.41.0" / "docker-compose").read_bytes() == b"#!/bin/sh\necho fake\n"
    assert (tmp_path / "2.41.0" / "docker-compose").stat().st_mode & 0o111
    assert fetch.calls[0].endswith(f"/v2.41.0/{compose_sync.asset_name()}")
    assert fetch.calls[1].endswith(f"/v2.41.0/{compose_sync.asset_name()}.sha256")


def test_download_release_rejects_bad_checksum(tmp_path):
    fetch = _fake_fetch_factory(b"binary", checksum_line="0" * 64 + "  " + compose_sync.asset_name())
    with pytest.raises(RuntimeError, match="sha256 mismatch"):
        compose_sync.download_release("2.41.0", str(tmp_path), fetch=fetch)
    assert not (tmp_path / "2.41.0" / "docker-compose").exists()


def test_download_release_rejects_non_version():
    with pytest.raises(ValueError):
        compose_sync.download_release("../etc", "/tmp/x", fetch=lambda u, t: b"")


def test_expected_sha256_accepts_bare_hex_and_sha256sum_format():
    h = "a" * 64
    assert compose_sync._expected_sha256(h + "\n", "x") == h
    assert compose_sync._expected_sha256(f"{h}  x\n", "x") == h
    assert compose_sync._expected_sha256(f"{h} *x\n", "x") == h
    with pytest.raises(RuntimeError):
        compose_sync._expected_sha256(f"{h}  other\n", "x")


def _settings_with_file(settings, tmp_path, version: str):
    f = tmp_path / "host-compose-version"
    f.write_text(version + "\n")
    return replace(settings, host_compose_version_file=str(f), compose_sync_dir=str(tmp_path / "sync"))


def test_sync_once_is_off_without_a_file_path(settings):
    with patch("unraid_compose_gateway.compose_version.version_of") as version_of:
        assert compose_sync.sync_once(settings) is None
        version_of.assert_not_called()


def test_sync_once_does_nothing_when_versions_match(settings, tmp_path):
    s = _settings_with_file(settings, tmp_path, "2.40.3")
    downloader = patch("unraid_compose_gateway.compose_sync.download_release")
    with patch("unraid_compose_gateway.compose_version.version_of", return_value="2.40.3"), downloader as dl:
        assert compose_sync.sync_once(s) == "2.40.3"
        dl.assert_not_called()
    assert compose_version.compose_source() == "bundled"


def test_sync_once_downloads_and_switches_on_difference(settings, tmp_path):
    s = _settings_with_file(settings, tmp_path, "2.41.0")
    binary_path = str(tmp_path / "sync" / "2.41.0" / "docker-compose")

    def fake_download(version, dest_dir):
        assert version == "2.41.0" and dest_dir == str(tmp_path / "sync")
        return compose_sync.Downloaded(version=version, path=binary_path)

    def fake_version_of(command):
        return "2.41.0" if command == [binary_path] else "2.40.3"

    with patch("unraid_compose_gateway.compose_version.version_of", side_effect=fake_version_of):
        assert compose_sync.sync_once(s, downloader=fake_download) == "2.41.0"
    assert compose_version.compose_command() == [binary_path]
    assert compose_version.compose_source() == "synced"


def test_sync_once_reuses_a_cached_download(settings, tmp_path):
    s = _settings_with_file(settings, tmp_path, "2.41.0")
    cached = tmp_path / "sync" / "2.41.0" / "docker-compose"
    cached.parent.mkdir(parents=True)
    cached.write_text("fake")
    downloader = patch("unraid_compose_gateway.compose_sync.download_release")

    def fake_version_of(command):
        return "2.41.0" if command == [str(cached)] else "2.40.3"

    with patch("unraid_compose_gateway.compose_version.version_of", side_effect=fake_version_of), downloader as dl:
        assert compose_sync.sync_once(s) == "2.41.0"
        dl.assert_not_called()
    assert compose_version.compose_command() == [str(cached)]


def test_sync_once_keeps_bundled_when_download_fails(settings, tmp_path, caplog):
    s = _settings_with_file(settings, tmp_path, "2.41.0")

    def failing_download(version, dest_dir):
        raise RuntimeError("github unreachable")

    with patch("unraid_compose_gateway.compose_version.version_of", return_value="2.40.3"):
        with caplog.at_level("WARNING", logger="unraid_compose_gateway"):
            assert compose_sync.sync_once(s, downloader=failing_download) == "2.40.3"
    assert compose_version.compose_source() == "bundled"
    assert any("github unreachable" in r.getMessage() for r in caplog.records)


def test_sync_once_rejects_binary_reporting_wrong_version(settings, tmp_path):
    s = _settings_with_file(settings, tmp_path, "2.41.0")
    binary_path = str(tmp_path / "sync" / "2.41.0" / "docker-compose")

    def fake_download(version, dest_dir):
        return compose_sync.Downloaded(version=version, path=binary_path)

    with patch("unraid_compose_gateway.compose_version.version_of", return_value="2.40.3"):
        assert compose_sync.sync_once(s, downloader=fake_download) == "2.40.3"
    assert compose_version.compose_source() == "bundled"


def test_compose_control_uses_the_synced_command(settings, tmp_path):
    from tests.conftest import make_compose_project
    from unraid_compose_gateway import compose_control
    from unittest.mock import MagicMock

    make_compose_project(tmp_path / "projects", "app")
    compose_version.set_compose_command(["/opt/compose/docker-compose"], source="synced")
    completed = MagicMock(stdout="ok", stderr="", returncode=0)
    with patch("unraid_compose_gateway.compose_control.subprocess.run", return_value=completed) as run:
        compose_control.run_action("app", "restart", settings)
    assert run.call_args.args[0][:2] == ["/opt/compose/docker-compose", "-f"]
