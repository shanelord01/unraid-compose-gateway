"""Tests for hermes-plugin/tools.py.

Lives in the main tests/ directory rather than nested inside hermes-plugin/
itself: hermes-plugin/__init__.py must stay a real package (Hermes imports
it as one), and pytest treats any __init__.py-bearing directory as a
collectible Package, which forces it to import that __init__.py directly -
and its `from . import schemas, settings, tools` fails outside a real
package context. Keeping the plugin's tests here, with the plugin directory
added to sys.path for a flat, top-level `import tools`, sidesteps that
entirely.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
from unittest.mock import MagicMock, patch

_HERMES_PLUGIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hermes-plugin")
if _HERMES_PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _HERMES_PLUGIN_DIR)

import tools as gateway_tools  # noqa: E402 - must follow the sys.path insert above


def _response(body: dict):
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(body).encode()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False
    return mock_resp


def _config(**overrides):
    base = {
        "gateway_url": "http://gateway.local:8080",
        "gateway_token": "test-token",
        "allow_writes": False,
        "timeout_seconds": 30,
    }
    base.update(overrides)
    return base


def test_request_returns_error_when_url_not_set():
    with patch.object(gateway_tools, "_config", return_value=_config(gateway_url="")):
        result = gateway_tools._request("GET", "/v1/whoami")
    assert "GATEWAY_URL" in result["error"]


def test_request_returns_error_when_token_not_set():
    with patch.object(gateway_tools, "_config", return_value=_config(gateway_token="")):
        result = gateway_tools._request("GET", "/v1/whoami")
    assert "GATEWAY_TOKEN" in result["error"]


def test_request_success():
    with patch.object(gateway_tools, "_config", return_value=_config()):
        with patch("urllib.request.urlopen", return_value=_response({"ok": True})):
            result = gateway_tools._request("GET", "/v1/whoami")
    assert result == {"ok": True}


def test_request_sends_bearer_token_header():
    captured = {}

    def fake_urlopen(req, timeout):
        captured["headers"] = dict(req.header_items())
        captured["url"] = req.full_url
        return _response({"ok": True})

    with patch.object(gateway_tools, "_config", return_value=_config()):
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            gateway_tools._request("GET", "/v1/whoami")

    assert captured["headers"]["Authorization"] == "Bearer test-token"
    assert captured["url"] == "http://gateway.local:8080/v1/whoami"


def test_request_extracts_detail_from_http_error():
    error_body = json.dumps(
        {"detail": "'protected' is in SELF_EXCLUDE_PROJECTS and cannot be controlled"}
    ).encode()
    http_error = urllib.error.HTTPError(
        url="http://gateway.local:8080/v1/compose/protected/restart",
        code=403,
        msg="Forbidden",
        hdrs=None,
        fp=None,
    )
    http_error.read = lambda: error_body

    with patch.object(gateway_tools, "_config", return_value=_config()):
        with patch("urllib.request.urlopen", side_effect=http_error):
            result = gateway_tools._request("POST", "/v1/compose/protected/restart")

    assert "SELF_EXCLUDE_PROJECTS" in result["error"]
    assert "403" in result["error"]


def test_request_handles_connection_failure():
    with patch.object(gateway_tools, "_config", return_value=_config()):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
            result = gateway_tools._request("GET", "/v1/whoami")
    assert "could not reach" in result["error"]


def test_status_requires_project():
    result = json.loads(gateway_tools.ucg_status({}))
    assert "project is required" in result["error"]


def test_logs_requires_name():
    result = json.loads(gateway_tools.ucg_logs({}))
    assert "name is required" in result["error"]


def test_restart_blocked_when_writes_disabled():
    with patch.object(gateway_tools, "_config", return_value=_config(allow_writes=False)):
        result = json.loads(gateway_tools.ucg_restart({"project": "app"}))
    assert "GATEWAY_ALLOW_WRITES" in result["error"]


def test_restart_calls_gateway_when_writes_enabled():
    with patch.object(gateway_tools, "_config", return_value=_config(allow_writes=True)):
        with patch("urllib.request.urlopen", return_value=_response({"exit_code": 0})) as urlopen:
            result = json.loads(gateway_tools.ucg_restart({"project": "app"}))
    assert result == {"exit_code": 0}
    called_request = urlopen.call_args.args[0]
    assert called_request.full_url == "http://gateway.local:8080/v1/compose/app/restart"
    assert called_request.get_method() == "POST"


def test_pull_still_requires_client_side_write_gate():
    """The gateway exempts `pull` from its own SELF_EXCLUDE_PROJECTS check,
    but this plugin's GATEWAY_ALLOW_WRITES gate applies uniformly to all
    four mutating tools - pull included - since it is a client-side intent
    switch, not a re-implementation of the gateway's per-project policy."""
    with patch.object(gateway_tools, "_config", return_value=_config(allow_writes=False)):
        result = json.loads(gateway_tools.ucg_pull({"project": "app"}))
    assert "GATEWAY_ALLOW_WRITES" in result["error"]


def test_whoami_calls_expected_path():
    with patch.object(gateway_tools, "_config", return_value=_config()):
        with patch(
            "urllib.request.urlopen", return_value=_response({"allowed_projects": []})
        ) as urlopen:
            gateway_tools.ucg_whoami({})
    assert urlopen.call_args.args[0].full_url == "http://gateway.local:8080/v1/whoami"


def test_plugin_updates_passes_force_flag():
    with patch.object(gateway_tools, "_config", return_value=_config()):
        with patch("urllib.request.urlopen", return_value=_response({"plugins": []})) as urlopen:
            gateway_tools.ucg_plugin_updates({"force": True})
    assert "force=true" in urlopen.call_args.args[0].full_url
