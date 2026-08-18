"""Docker Compose project control via the `docker compose` CLI.

There is no stable, official Python API for Compose v2 - it ships as a Docker
CLI plugin, not a library - so this shells out to the CLI the same way the
Unraid Compose Manager plugin itself does. What matters for the security
model is not *how* it calls compose, it is that every mutating call passes
through `_check_target` first, and that check cannot be skipped by any
combination of arguments a caller sends: the project name is looked up
against ALLOWED_PROJECTS and SELF_EXCLUDE_PROJECTS before a single
subprocess is started.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

from unraid_compose_gateway.config import Settings
from unraid_compose_gateway.models import ComposeActionResult, ComposeProject, ComposeService

_COMPOSE_FILE_NAMES = (
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
)


class ProjectNotAllowed(Exception):
    """Raised when a project name is not in ALLOWED_PROJECTS."""


class ProjectSelfExcluded(Exception):
    """Raised when a project is in SELF_EXCLUDE_PROJECTS and the caller
    asked for a mutating action."""


class ProjectNotFound(Exception):
    """Raised when a project is allowed but has no compose file on disk."""


class ComposeCommandFailed(Exception):
    """Raised when `docker compose` itself exits non-zero."""

    def __init__(self, message: str, exit_code: int, output: str):
        super().__init__(message)
        self.exit_code = exit_code
        self.output = output


@dataclass(frozen=True)
class ResolvedProject:
    name: str
    dir_path: str
    compose_file: str


def _find_compose_file(project_dir: str) -> str | None:
    import os

    for candidate in _COMPOSE_FILE_NAMES:
        full = os.path.join(project_dir, candidate)
        if os.path.isfile(full):
            return full
    return None


def _resolve(project: str, settings: Settings) -> ResolvedProject:
    import os

    project_dir = os.path.join(settings.compose_projects_dir, project)
    compose_file = _find_compose_file(project_dir)
    if compose_file is None:
        raise ProjectNotFound(f"no compose file found under {project_dir}")
    return ResolvedProject(name=project, dir_path=project_dir, compose_file=compose_file)


def _check_target(project: str, settings: Settings, *, mutating: bool) -> None:
    if not settings.is_allowed(project):
        raise ProjectNotAllowed(f"'{project}' is not in ALLOWED_PROJECTS")
    if mutating and settings.is_self_excluded(project):
        raise ProjectSelfExcluded(f"'{project}' is in SELF_EXCLUDE_PROJECTS and cannot be controlled")


def list_projects(settings: Settings) -> list[ComposeProject]:
    import os

    projects = []
    for name in settings.allowed_projects:
        project_dir = os.path.join(settings.compose_projects_dir, name)
        compose_file = _find_compose_file(project_dir)
        projects.append(
            ComposeProject(
                name=name,
                path=project_dir,
                exists=compose_file is not None,
                self_excluded=settings.is_self_excluded(name),
            )
        )
    return projects


def get_status(project: str, settings: Settings) -> list[ComposeService]:
    _check_target(project, settings, mutating=False)
    resolved = _resolve(project, settings)
    result = _run_compose(resolved, ["ps", "--format", "json"], settings)
    return _parse_ps_output(result.output)


def run_action(project: str, action: str, settings: Settings) -> ComposeActionResult:
    if action not in ("up", "down", "restart"):
        raise ValueError(f"unsupported action: {action}")
    _check_target(project, settings, mutating=True)
    resolved = _resolve(project, settings)
    args = {"up": ["up", "-d"], "down": ["down"], "restart": ["restart"]}[action]
    result = _run_compose(resolved, args, settings)
    return ComposeActionResult(
        project=project, action=action, exit_code=result.exit_code, output=result.output
    )


@dataclass(frozen=True)
class _RunResult:
    exit_code: int
    output: str


def _run_compose(resolved: ResolvedProject, args: list[str], settings: Settings) -> _RunResult:
    command = ["docker", "compose", "-p", resolved.name, "-f", resolved.compose_file, *args]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=settings.compose_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ComposeCommandFailed(
            f"docker compose timed out after {settings.compose_timeout_seconds}s",
            exit_code=-1,
            output=(exc.output or "") + (exc.stderr or ""),
        ) from exc

    output = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode != 0:
        raise ComposeCommandFailed(
            f"docker compose exited {completed.returncode}", exit_code=completed.returncode, output=output
        )
    return _RunResult(exit_code=completed.returncode, output=output)


def _parse_ps_output(raw: str) -> list[ComposeService]:
    """`docker compose ps --format json` emits one JSON object per line in
    current Compose versions, but has emitted a single JSON array in others.
    Handle both rather than pinning to one Compose release.
    """
    raw = raw.strip()
    if not raw:
        return []

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            records = parsed
        else:
            records = [parsed]
    except json.JSONDecodeError:
        records = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    services = []
    for record in records:
        services.append(
            ComposeService(
                name=record.get("Service") or record.get("Name") or "unknown",
                state=record.get("State") or record.get("Status") or "unknown",
                health=record.get("Health") or None,
            )
        )
    return services
