"""Shared settings for the ucg plugin.

Resolution order is file, then environment, then default - the same
convention as the other Hermes plugins in this family. The dashboard, if one
is ever added, would write the file; environment variables remain the
fallback so a headless install needs no UI.
"""

import json
import os
import threading
from typing import Any, Dict

SETTINGS_FILENAME = "ucg_settings.json"

FIELDS = {
    "gateway_url": ("GATEWAY_URL", ""),
    "gateway_token": ("GATEWAY_TOKEN", ""),
    "allow_writes": ("GATEWAY_ALLOW_WRITES", False),
    "timeout_seconds": ("GATEWAY_TIMEOUT_SECONDS", 30),
}

SECRET_FIELDS = ("gateway_token",)
_lock = threading.Lock()


def path() -> str:
    home = (os.environ.get("HERMES_HOME") or "").strip() or os.path.expanduser("~/.hermes")
    return os.path.join(home, SETTINGS_FILENAME)


def _read_file() -> Dict[str, Any]:
    try:
        p = path()
        if os.path.exists(p):
            with open(p) as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - a bad settings file must not break the plugin
        pass
    return {}


def _coerce(value: Any, default: Any) -> Any:
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() not in ("0", "false", "no", "off", "")
    if isinstance(default, int):
        try:
            return max(0, int(str(value).strip()))
        except (TypeError, ValueError):
            return default
    return str(value).strip()


def load() -> Dict[str, Any]:
    stored = _read_file()
    out: Dict[str, Any] = {}
    sources: Dict[str, str] = {}
    for key, (env_var, default) in FIELDS.items():
        if key in stored and str(stored[key]).strip() != "":
            out[key] = _coerce(stored[key], default)
            sources[key] = "settings"
            continue
        raw = os.environ.get(env_var)
        if raw is not None and str(raw).strip() != "":
            out[key] = _coerce(raw, default)
            sources[key] = "env"
            continue
        out[key] = default
        sources[key] = "default"
    out["_sources"] = sources
    return out


def public() -> Dict[str, Any]:
    """Settings safe to send to a browser: secrets reduced to a presence flag."""
    data = load()
    sources = data.pop("_sources", {})
    out = {k: v for k, v in data.items() if k not in SECRET_FIELDS}
    for k in SECRET_FIELDS:
        out[k + "_set"] = bool(data.get(k))
    return {"settings": out, "sources": sources}


def save(patch: Dict[str, Any]) -> Dict[str, Any]:
    with _lock:
        stored = _read_file()
        for key, value in (patch or {}).items():
            if key not in FIELDS:
                continue
            if value is None or str(value).strip() == "":
                stored.pop(key, None)
            else:
                stored[key] = value
        p = path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(stored, fh, indent=2, sort_keys=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
    return public()
