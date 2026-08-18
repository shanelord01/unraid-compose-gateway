"""Process-wide settings singleton, exposed as a FastAPI dependency.

Routing it through a dependency rather than a bare module-level import means
tests can swap in a `Settings` instance with `app.dependency_overrides`
without touching environment variables or reloading modules.
"""

from __future__ import annotations

from unraid_compose_gateway.config import Settings, load_settings

_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def set_settings(settings: Settings) -> None:
    """Used at startup, and by tests to inject a fixed configuration."""
    global _settings
    _settings = settings
