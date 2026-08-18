"""Configuration, resolved entirely from environment variables.

This is a standalone sidecar rather than a plugin with a dashboard overlay, so
there is only one source of truth: the environment the container was started
with. Keeping it that way means the running config is always exactly what is
in the compose file or systemd unit - nothing hidden in a settings file that
drifts from what is checked into version control.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    token: str
    allowed_projects: list[str] = field(default_factory=list)
    self_exclude_projects: list[str] = field(default_factory=list)
    compose_projects_dir: str = "/compose-projects"
    plugin_dir: str | None = None
    plugin_cache_seconds: int = 1800
    log_tail_default: int = 200
    log_tail_max: int = 5000
    compose_timeout_seconds: int = 120
    port: int = 8080

    def is_allowed(self, project: str) -> bool:
        return project in self.allowed_projects

    def is_self_excluded(self, project: str) -> bool:
        return project in self.self_exclude_projects


def load_settings() -> Settings:
    token = os.environ.get("GATEWAY_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "GATEWAY_TOKEN is required - set it to a long random value. "
            "Every request must present it as 'Authorization: Bearer <token>'."
        )

    plugin_dir = os.environ.get("PLUGIN_DIR", "").strip() or None
    if plugin_dir and not os.path.isdir(plugin_dir):
        # Not fatal: the plugin-update endpoints report themselves as
        # disabled rather than the whole service failing to start over an
        # optional feature.
        plugin_dir = None

    return Settings(
        token=token,
        allowed_projects=_split_csv(os.environ.get("ALLOWED_PROJECTS", "")),
        self_exclude_projects=_split_csv(os.environ.get("SELF_EXCLUDE_PROJECTS", "")),
        compose_projects_dir=os.environ.get("COMPOSE_PROJECTS_DIR", "/compose-projects").strip()
        or "/compose-projects",
        plugin_dir=plugin_dir,
        plugin_cache_seconds=int(os.environ.get("PLUGIN_CACHE_SECONDS", "1800")),
        log_tail_default=int(os.environ.get("LOG_TAIL_DEFAULT", "200")),
        log_tail_max=int(os.environ.get("LOG_TAIL_MAX", "5000")),
        compose_timeout_seconds=int(os.environ.get("COMPOSE_TIMEOUT_SECONDS", "120")),
        port=int(os.environ.get("PORT", "8080")),
    )
