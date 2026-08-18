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


class ComposeProject(BaseModel):
    name: str
    path: str
    exists: bool
    self_excluded: bool


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
