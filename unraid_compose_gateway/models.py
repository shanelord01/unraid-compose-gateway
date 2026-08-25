"""Response shapes. Kept separate from the route handlers so the API
contract is one place to read, independent of how each value gets produced.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class WhoAmI(BaseModel):
    allowed_projects: list[str]
    self_exclude_projects: list[str]
    plugin_updates_enabled: bool
    compose_version: str | None = None
    """The Docker Compose version this gateway runs `up` with. Must match
    the host's own Compose tool for shared projects; None only if it could
    not be determined."""
    compose_version_source: str = "bundled"
    """"bundled" (the image's pinned plugin) or "synced" (a release binary
    downloaded at runtime to match host_compose_version)."""
    host_compose_version: str | None = None
    """What the host's own Compose tool reports, read from
    HOST_COMPOSE_VERSION_FILE. None if sync is not configured or the file
    is missing or malformed."""


class ComposeProject(BaseModel):
    name: str
    path: str
    exists: bool
    self_excluded: bool
    autostart: bool | None = None
    """Unraid Compose Manager's own "Auto Start" checkbox for this project,
    read from the plain true/false `autostart` file the plugin writes
    alongside each project's compose file. None if the project doesn't
    exist, or the file is missing/unreadable - never guess a value in that
    case, since guessing wrong either direction is worse than admitting we
    don't know: a caller must treat None as "don't assume, ask/skip", not
    as false."""


class ComposeService(BaseModel):
    name: str
    state: str
    health: str | None = None


class ComposeProjectStatus(BaseModel):
    project: str
    services: list[ComposeService]


class ComposeActionResult(BaseModel):
    project: str
    action: Literal["up", "down", "restart", "pull"]
    exit_code: int
    output: str


class ContainerLogs(BaseModel):
    container: str
    tail: int
    lines: list[str]


class PruneResult(BaseModel):
    output: str
    deleted_count: int
    reclaimed_display: str | None = None
    """Docker's own human-readable size string (e.g. "7.566GB"), not a
    byte count - `docker image prune`'s output doesn't give one, and
    parsing a display string into exact bytes isn't worth the fragility
    for a number that's purely informational."""


class PluginUpdate(BaseModel):
    name: str
    installed_version: str | None
    latest_version: str | None
    update_available: bool
    plugin_url: str | None
    checked_at: str
    error: str | None = None


class PluginUpdatesResponse(BaseModel):
    plugins: list[PluginUpdate]
    cache_age_seconds: float


class ErrorResponse(BaseModel):
    detail: str
