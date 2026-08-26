"""Settings round-trip for the ucg plugin.

Covers what the dashboard tab actually does: POST a partial patch and get the
effective settings back. Regression cover for long_timeout_seconds, added
2026-08-26 - the dashboard previously only knew four fields, so the value had
to be set via environment.
"""

from __future__ import annotations

import os
import sys

import pytest

_HERMES_PLUGIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hermes-plugin")
if _HERMES_PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _HERMES_PLUGIN_DIR)

import settings as plugin_settings  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    for env_var, _ in plugin_settings.FIELDS.values():
        monkeypatch.delenv(env_var, raising=False)
    yield


def test_long_timeout_defaults_to_600():
    assert plugin_settings.load()["long_timeout_seconds"] == 600


def test_long_timeout_round_trips_through_save():
    plugin_settings.save({"long_timeout_seconds": 900})
    assert plugin_settings.load()["long_timeout_seconds"] == 900
    assert plugin_settings.load()["_sources"]["long_timeout_seconds"] == "settings"


def test_long_timeout_is_exposed_to_the_dashboard():
    """public() is what GET /settings returns - the field must be in there."""
    body = plugin_settings.public()
    assert "long_timeout_seconds" in body["settings"]
    assert "long_timeout_seconds" in body["sources"]


def test_dashboard_patch_does_not_clear_the_other_fields():
    plugin_settings.save({"gateway_url": "http://gw:8080", "long_timeout_seconds": 900})
    plugin_settings.save({"timeout_seconds": 45})
    data = plugin_settings.load()
    assert data["gateway_url"] == "http://gw:8080"
    assert data["long_timeout_seconds"] == 900
    assert data["timeout_seconds"] == 45


def test_env_is_used_when_no_stored_value(monkeypatch):
    monkeypatch.setenv("GATEWAY_LONG_TIMEOUT_SECONDS", "240")
    data = plugin_settings.load()
    assert data["long_timeout_seconds"] == 240
    assert data["_sources"]["long_timeout_seconds"] == "env"


def test_stored_value_wins_over_env(monkeypatch):
    monkeypatch.setenv("GATEWAY_LONG_TIMEOUT_SECONDS", "240")
    plugin_settings.save({"long_timeout_seconds": 900})
    assert plugin_settings.load()["long_timeout_seconds"] == 900


def test_blank_value_returns_the_key_to_env_or_default():
    plugin_settings.save({"long_timeout_seconds": 900})
    plugin_settings.save({"long_timeout_seconds": ""})
    data = plugin_settings.load()
    assert data["long_timeout_seconds"] == 600
    assert data["_sources"]["long_timeout_seconds"] == "default"


def test_garbage_value_falls_back_to_the_default():
    plugin_settings.save({"long_timeout_seconds": "not-a-number"})
    assert plugin_settings.load()["long_timeout_seconds"] == 600
