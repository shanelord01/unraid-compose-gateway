"""Unraid plugin update detection.

Unraid's own "Check for Updates" button does nothing more sophisticated than
this: every installed plugin has a local descriptor at
`/boot/config/plugins/<name>.plg`, an XML file whose DOCTYPE defines a
`version` entity and a `pluginURL` entity pointing at the canonical copy of
that same file (typically on GitHub). Checking for an update means fetching
`pluginURL` and comparing its `version` entity against the local one - no
registry, no auth, no semantic version comparison. This module does exactly
that and nothing more.

The gap this fills: Unraid's own API (GraphQL `installedUnraidPlugins`)
returns bare plugin names with no version or update information at all, so
that check is not reachable programmatically except by reimplementing it
here against the local `.plg` files directly.

This module is read-only. It never writes to PLUGIN_DIR and never installs
anything - applying an update is a separate, deliberately-not-automated step
left to whatever already has permission to install Unraid plugins.
"""

from __future__ import annotations

import asyncio
import glob
import os
import re
import time
from datetime import datetime, timezone

import httpx

from compose_sentry.config import Settings
from compose_sentry.models import PluginUpdate

_ENTITY_RE = re.compile(r'<!ENTITY\s+(\S+)\s+"([^"]*)"\s*>')
_ENTITY_REF_RE = re.compile(r"&(\w+);")
_FETCH_TIMEOUT_SECONDS = 10.0
_MAX_ENTITY_PASSES = 5

_cache: dict[str, object] = {"checked_at": 0.0, "results": []}


class PluginUpdatesDisabled(Exception):
    """Raised when PLUGIN_DIR was not configured or does not exist."""


def _extract_entities(text: str) -> dict[str, str]:
    return dict(_ENTITY_RE.findall(text))


def _resolve(value: str | None, entities: dict[str, str]) -> str | None:
    if value is None:
        return None
    for _ in range(_MAX_ENTITY_PASSES):
        resolved = _ENTITY_REF_RE.sub(lambda m: entities.get(m.group(1), m.group(0)), value)
        if resolved == value:
            break
        value = resolved
    return value


def _extract_root_attr(text: str, attr: str) -> str | None:
    match = re.search(rf'<PLUGIN\b[^>]*\b{re.escape(attr)}="([^"]*)"', text, re.IGNORECASE)
    return match.group(1) if match else None


def parse_plg(text: str) -> tuple[str | None, str | None, str | None]:
    """Returns (name, version, pluginURL), each resolved through the file's
    own entity table. Any of the three may be None if the file does not
    follow the conventional layout.
    """
    entities = _extract_entities(text)
    name = _resolve(_extract_root_attr(text, "name") or entities.get("name"), entities)
    version = _resolve(_extract_root_attr(text, "version") or entities.get("version"), entities)
    plugin_url = _resolve(_extract_root_attr(text, "pluginURL") or entities.get("pluginURL"), entities)
    return name, version, plugin_url


async def _check_one(path: str, client: httpx.AsyncClient) -> PluginUpdate:
    checked_at = datetime.now(timezone.utc).isoformat()
    filename = os.path.splitext(os.path.basename(path))[0]

    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            local_text = fh.read()
    except OSError as exc:
        return PluginUpdate(
            name=filename,
            installed_version=None,
            latest_version=None,
            update_available=False,
            plugin_url=None,
            checked_at=checked_at,
            error=f"could not read local plugin file: {exc}",
        )

    name, installed_version, plugin_url = parse_plg(local_text)
    name = name or filename

    if not plugin_url:
        return PluginUpdate(
            name=name,
            installed_version=installed_version,
            latest_version=None,
            update_available=False,
            plugin_url=None,
            checked_at=checked_at,
            error="no pluginURL found in local .plg file",
        )

    try:
        response = await client.get(plugin_url, timeout=_FETCH_TIMEOUT_SECONDS)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return PluginUpdate(
            name=name,
            installed_version=installed_version,
            latest_version=None,
            update_available=False,
            plugin_url=plugin_url,
            checked_at=checked_at,
            error=f"could not fetch pluginURL: {exc}",
        )

    _, remote_version, _ = parse_plg(response.text)

    return PluginUpdate(
        name=name,
        installed_version=installed_version,
        latest_version=remote_version,
        update_available=bool(
            installed_version and remote_version and installed_version != remote_version
        ),
        plugin_url=plugin_url,
        checked_at=checked_at,
        error=None if remote_version else "remote .plg had no readable version entity",
    )


async def check_updates(settings: Settings, *, force: bool = False) -> tuple[list[PluginUpdate], float]:
    if not settings.plugin_dir:
        raise PluginUpdatesDisabled("PLUGIN_DIR is not configured")

    age = time.monotonic() - float(_cache["checked_at"])
    if not force and age < settings.plugin_cache_seconds and _cache["results"]:
        return list(_cache["results"]), age  # type: ignore[arg-type]

    plg_files = sorted(glob.glob(os.path.join(settings.plugin_dir, "*.plg")))

    async with httpx.AsyncClient(follow_redirects=True) as client:
        results = await asyncio.gather(*(_check_one(path, client) for path in plg_files))

    _cache["checked_at"] = time.monotonic()
    _cache["results"] = list(results)
    return list(results), 0.0
