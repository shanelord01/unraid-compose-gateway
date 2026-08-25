"""Compose version parity between this gateway and the host's own tooling.

Compose stores a config hash on every container it creates
(`com.docker.compose.config-hash`) and, on `up`, recreates any service whose
current hash differs from what it computes from the files. Different Compose
versions compute different hashes for identical YAML. So when two tools with
different Compose versions manage the same project - this gateway and, on
Unraid, the Compose Manager plugin's own docker-compose binary - each `up`
from either side force-recreates every service the other side last touched.
On a busy boot that turns into orphaned containers and name conflicts.

The image pins its Compose version to match the host (see the Dockerfile),
compose_sync.py can replace it at runtime with the exact version the host
reports, and this module is the runtime check that whichever is active
matches what created a project's containers. `up` is refused on a mismatch
unless the caller explicitly forces it.

This module also owns *which* compose command the gateway runs: the bundled
`docker compose` plugin by default, or a downloaded standalone binary after
a sync. Every subprocess that runs Compose gets its argv prefix from
compose_command().
"""

from __future__ import annotations

import logging
import subprocess
import threading

from unraid_compose_gateway.config import Settings

_LOG = logging.getLogger("unraid_compose_gateway")

VERSION_LABEL = "com.docker.compose.version"
PROJECT_LABEL = "com.docker.compose.project"

_BUNDLED_COMMAND = ["docker", "compose"]
_lock = threading.Lock()
_command: list[str] = list(_BUNDLED_COMMAND)
_source = "bundled"
_version_cache: dict[tuple[str, ...], str] = {}


class ComposeVersionMismatch(Exception):
    """Raised when a project's containers were created by a different Compose
    version than this gateway runs, so `up` would recreate all of them."""

    def __init__(self, project: str, gateway_version: str, container_versions: list[str]):
        self.project = project
        self.gateway_version = gateway_version
        self.container_versions = container_versions
        super().__init__(
            f"'{project}' containers were created by Compose {', '.join(container_versions)} "
            f"but this gateway runs Compose {gateway_version}; `up` would recreate every "
            "service. Align the versions (see README, Compose version parity) or pass "
            "force=true to recreate anyway."
        )


def _run(command: list[str], timeout: int) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "").strip())
    return completed.stdout


def compose_command() -> list[str]:
    """argv prefix for running Compose: `["docker", "compose"]` or the path
    of a synced standalone binary."""
    with _lock:
        return list(_command)


def compose_source() -> str:
    """"bundled" or "synced"."""
    with _lock:
        return _source


def set_compose_command(command: list[str], *, source: str) -> None:
    global _command, _source
    with _lock:
        _command = list(command)
        _source = source


def reset_compose_command() -> None:
    """Back to the image's bundled plugin. Used by tests."""
    global _command, _source
    with _lock:
        _command = list(_BUNDLED_COMMAND)
        _source = "bundled"
        _version_cache.clear()


def version_of(command: list[str]) -> str:
    """`<command> version --short`, cached per command since a given binary
    cannot change version while the process runs."""
    key = tuple(command)
    cached = _version_cache.get(key)
    if cached is not None:
        return cached
    version = _run([*command, "version", "--short"], timeout=30).strip()
    _version_cache[key] = version
    return version


def gateway_compose_version() -> str:
    """The Compose version the gateway currently runs `up` with."""
    return version_of(compose_command())


def versions_for_containers(container_ids: list[str], settings: Settings) -> list[str]:
    """Distinct `com.docker.compose.version` label values across the given
    containers. Empty for an empty id list (a project with nothing created
    yet has nothing to be recreated, so there is nothing to protect)."""
    ids = [c.strip() for c in container_ids if c.strip()]
    if not ids:
        return []
    output = _run(
        ["docker", "inspect", "--format", "{{index .Config.Labels \"" + VERSION_LABEL + "\"}}", *ids],
        timeout=settings.compose_timeout_seconds,
    )
    return sorted({line.strip() for line in output.splitlines() if line.strip()})


def assert_parity(project: str, container_ids: list[str], settings: Settings) -> None:
    """Raise ComposeVersionMismatch if any of the containers was created by
    a Compose version other than this gateway's."""
    versions = versions_for_containers(container_ids, settings)
    if not versions:
        return
    mine = gateway_compose_version()
    if any(v != mine for v in versions):
        raise ComposeVersionMismatch(project, mine, versions)


def host_versions_by_project(settings: Settings) -> dict[str, set[str]]:
    """Every Compose project visible on the daemon, mapped to the set of
    Compose versions that created its containers. Used once at startup to
    warn about projects this gateway would recreate."""
    output = _run(
        [
            "docker", "ps", "-a",
            "--filter", f"label={PROJECT_LABEL}",
            "--format", "{{.Label \"" + PROJECT_LABEL + "\"}}\t{{.Label \"" + VERSION_LABEL + "\"}}",
        ],
        timeout=settings.compose_timeout_seconds,
    )
    result: dict[str, set[str]] = {}
    for line in output.splitlines():
        if "\t" not in line:
            continue
        project, version = line.split("\t", 1)
        project, version = project.strip(), version.strip()
        if not project:
            continue
        result.setdefault(project, set())
        if version:
            result[project].add(version)
    return result


def log_startup_report(settings: Settings) -> None:
    """One log line with this gateway's Compose version, plus a warning per
    project on the host whose containers carry a different version. Never
    raises: a failure to inspect the daemon must not stop the service."""
    try:
        mine = gateway_compose_version()
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("could not determine this gateway's docker compose version: %s", exc)
        return
    _LOG.info("docker compose version in use: %s (%s)", mine, compose_source())
    try:
        by_project = host_versions_by_project(settings)
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("could not read compose versions from the docker daemon: %s", exc)
        return
    for project, versions in sorted(by_project.items()):
        others = sorted(v for v in versions if v != mine)
        if others:
            _LOG.warning(
                "compose version mismatch: project '%s' has containers created by Compose %s, "
                "this gateway runs %s; `up` on it is refused until the versions match "
                "(the host version file, if configured, will pull the gateway into line; "
                "otherwise rebuild with COMPOSE_VERSION=%s)",
                project, ", ".join(others), mine, others[0],
            )
