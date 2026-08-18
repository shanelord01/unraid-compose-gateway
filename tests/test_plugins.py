from __future__ import annotations

import pytest
import respx
from httpx import Response

from compose_sentry import plugins

SAMPLE_PLG = """<?xml version="1.0" encoding="utf-8" standalone="yes"?>
<!DOCTYPE PLUGIN [
<!ENTITY name      "community.applications">
<!ENTITY github     "unraid/community.applications">
<!ENTITY version   "2026.07.21">
<!ENTITY pluginURL "https://raw.githubusercontent.com/&github;/master/plugins/&name;.plg">
]>
<PLUGIN name="&name;" author="someone" version="&version;" pluginURL="&pluginURL;">
  <CHANGES>
  ###2026.07.21
  - initial
  </CHANGES>
</PLUGIN>
"""

SAMPLE_PLG_NEWER = SAMPLE_PLG.replace("2026.07.21", "2026.08.01")


def test_parse_plg_resolves_nested_entities():
    name, version, url = plugins.parse_plg(SAMPLE_PLG)
    assert name == "community.applications"
    assert version == "2026.07.21"
    assert url == "https://raw.githubusercontent.com/unraid/community.applications/master/plugins/community.applications.plg"


def test_parse_plg_handles_missing_fields_gracefully():
    name, version, url = plugins.parse_plg("<PLUGIN>not a real plugin file</PLUGIN>")
    assert name is None
    assert version is None
    assert url is None


@pytest.mark.asyncio
async def test_check_updates_flags_available_update(settings, tmp_path):
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "community.applications.plg").write_text(SAMPLE_PLG)
    from dataclasses import replace

    s = replace(settings, plugin_dir=str(plugin_dir))

    plugins._cache["checked_at"] = 0.0
    plugins._cache["results"] = []

    with respx.mock:
        respx.get(
            "https://raw.githubusercontent.com/unraid/community.applications/master/plugins/community.applications.plg"
        ).mock(return_value=Response(200, text=SAMPLE_PLG_NEWER))

        results, _ = await plugins.check_updates(s, force=True)

    assert len(results) == 1
    result = results[0]
    assert result.name == "community.applications"
    assert result.installed_version == "2026.07.21"
    assert result.latest_version == "2026.08.01"
    assert result.update_available is True
    assert result.error is None


@pytest.mark.asyncio
async def test_check_updates_no_update_when_versions_match(settings, tmp_path):
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "community.applications.plg").write_text(SAMPLE_PLG)
    from dataclasses import replace

    s = replace(settings, plugin_dir=str(plugin_dir))
    plugins._cache["checked_at"] = 0.0
    plugins._cache["results"] = []

    with respx.mock:
        respx.get(
            "https://raw.githubusercontent.com/unraid/community.applications/master/plugins/community.applications.plg"
        ).mock(return_value=Response(200, text=SAMPLE_PLG))

        results, _ = await plugins.check_updates(s, force=True)

    assert results[0].update_available is False


@pytest.mark.asyncio
async def test_check_updates_reports_fetch_error_without_raising(settings, tmp_path):
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "broken.plg").write_text(SAMPLE_PLG.replace("community.applications", "broken"))
    from dataclasses import replace

    s = replace(settings, plugin_dir=str(plugin_dir))
    plugins._cache["checked_at"] = 0.0
    plugins._cache["results"] = []

    with respx.mock:
        respx.get(
            "https://raw.githubusercontent.com/unraid/broken/master/plugins/broken.plg"
        ).mock(return_value=Response(404))

        results, _ = await plugins.check_updates(s, force=True)

    assert results[0].update_available is False
    assert results[0].error is not None


@pytest.mark.asyncio
async def test_check_updates_disabled_when_no_plugin_dir(settings):
    with pytest.raises(plugins.PluginUpdatesDisabled):
        await plugins.check_updates(settings)


@pytest.mark.asyncio
async def test_check_updates_uses_cache_until_ttl_expires(settings, tmp_path):
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "community.applications.plg").write_text(SAMPLE_PLG)
    from dataclasses import replace

    s = replace(settings, plugin_dir=str(plugin_dir), plugin_cache_seconds=3600)
    plugins._cache["checked_at"] = 0.0
    plugins._cache["results"] = []

    with respx.mock:
        route = respx.get(
            "https://raw.githubusercontent.com/unraid/community.applications/master/plugins/community.applications.plg"
        ).mock(return_value=Response(200, text=SAMPLE_PLG))

        await plugins.check_updates(s, force=True)
        await plugins.check_updates(s, force=False)

    assert route.call_count == 1
