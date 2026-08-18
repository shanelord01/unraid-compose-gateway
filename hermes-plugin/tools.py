"""Tool handlers for the compose_gateway plugin.

Contract per Hermes plugin rules: handlers accept (args: dict, **kwargs),
always return a JSON string, and never raise.

Every handler is a thin HTTP call to a running unraid-compose-gateway
instance. The actual security boundary - which projects can be touched at
all, and which of those can never be mutated - lives entirely on the gateway
side (ALLOWED_PROJECTS / SELF_EXCLUDE_PROJECTS, enforced server-side on every
request). GATEWAY_ALLOW_WRITES here is a client-side intent layer only: it
decides whether this plugin will even attempt a mutating call, the same way
UNRAID_SCOPES works in the sibling hermes-unraid plugin. Turning it on does
not grant anything the gateway itself would refuse.
"""

import json
import urllib.error
import urllib.parse
import urllib.request

try:  # package import when loaded as a Hermes plugin
    from . import settings as _settings_mod
except ImportError:  # direct import when testing standalone
    import settings as _settings_mod

_USER_AGENT = "hermes-compose-gateway/0.1 (+https://github.com/shanelord01/unraid-compose-gateway)"


def _config() -> dict:
    return _settings_mod.load()


def _base_url() -> str:
    return str(_config().get("gateway_url") or "").rstrip("/")


def _token() -> str:
    return str(_config().get("gateway_token") or "").strip()


def _timeout() -> int:
    try:
        return int(_config().get("timeout_seconds") or 30)
    except (TypeError, ValueError):
        return 30


def _writes_allowed() -> bool:
    return bool(_config().get("allow_writes"))


def _request(method: str, path: str, params: dict | None = None) -> dict:
    """Call the gateway. Returns the decoded JSON body, or {"error": ...}.

    The gateway reports problems as FastAPI's standard {"detail": "..."}
    body, on both 4xx (policy refusals - not allowed, self-excluded, not
    found) and 5xx (the compose command itself failed). Surfacing `detail`
    verbatim is what lets the model see *why* a call was refused instead of
    just that it was, which is the difference between it giving up and it
    trying a different, allowed project.
    """
    base = _base_url()
    if not base:
        return {"error": "GATEWAY_URL is not set"}
    if not _token():
        return {"error": "GATEWAY_TOKEN is not set"}

    url = base + path
    if params:
        clean = {k: v for k, v in params.items() if v not in (None, "")}
        if clean:
            url += "?" + urllib.parse.urlencode(clean)

    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {_token()}",
            "User-Agent": _USER_AGENT,
            "Accept": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=_timeout()) as resp:
            raw = resp.read().decode() or "{}"
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            payload = json.loads(e.read().decode() or "{}")
            detail = str(payload.get("detail") or "")
        except Exception:  # noqa: BLE001
            detail = ""
        return {"error": f"HTTP {e.code} from unraid-compose-gateway: {detail or e.reason}"}
    except urllib.error.URLError as e:
        return {"error": f"could not reach unraid-compose-gateway at {base}: {e.reason}"}
    except Exception as e:  # noqa: BLE001 - handlers must never raise
        return {"error": f"{type(e).__name__}: {e}"}


def _require_writes() -> dict | None:
    """Returns an error dict if writes are disabled, else None."""
    if not _writes_allowed():
        return {
            "error": (
                "compose control is disabled for this agent - set "
                "GATEWAY_ALLOW_WRITES=true to enable restart/up/down/pull"
            )
        }
    return None


def _require_project(args: dict) -> str | None:
    project = str((args or {}).get("project") or "").strip()
    return project or None


# --- always-registered, read-only tools -------------------------------------

def compose_gateway_whoami(args: dict, **kwargs) -> str:
    """This gateway instance's allowed projects, exclude list, and whether
    plugin update checking is enabled."""
    return json.dumps(_request("GET", "/v1/whoami"))


def compose_gateway_projects(args: dict, **kwargs) -> str:
    """List every project the gateway is configured to act on, whether it
    has a compose file on disk, and whether it is self-excluded from
    mutating calls."""
    return json.dumps(_request("GET", "/v1/compose/projects"))


def compose_gateway_status(args: dict, **kwargs) -> str:
    """Per-service state (running/exited/etc, health) for one compose
    project."""
    project = _require_project(args)
    if not project:
        return json.dumps({"error": "project is required"})
    return json.dumps(_request("GET", f"/v1/compose/{urllib.parse.quote(project)}/status"))


def compose_gateway_logs(args: dict, **kwargs) -> str:
    """Tail logs for any container by name - not restricted to the compose
    allowlist, since reading output is not a control operation."""
    name = str((args or {}).get("name") or "").strip()
    if not name:
        return json.dumps({"error": "name is required"})
    params = {"tail": args.get("tail"), "since": args.get("since")}
    return json.dumps(_request("GET", f"/v1/containers/{urllib.parse.quote(name)}/logs", params))


def compose_gateway_plugin_updates(args: dict, **kwargs) -> str:
    """Check installed Unraid plugins for available updates, by replicating
    the same local-.plg-vs-remote-.plg version check Unraid's own web UI
    uses. Read-only. Pass force=true to bypass the cache."""
    force = bool((args or {}).get("force"))
    return json.dumps(_request("GET", "/v1/plugins/updates", {"force": "true" if force else None}))


# --- mutating tools, gated on GATEWAY_ALLOW_WRITES --------------------------

def _run_action(action: str, args: dict) -> str:
    gate_error = _require_writes()
    if gate_error:
        return json.dumps(gate_error)
    project = _require_project(args)
    if not project:
        return json.dumps({"error": "project is required"})
    return json.dumps(_request("POST", f"/v1/compose/{urllib.parse.quote(project)}/{action}"))


def compose_gateway_restart(args: dict, **kwargs) -> str:
    """Restart a compose project's services. Refused by the gateway itself
    if the project is in its SELF_EXCLUDE_PROJECTS list."""
    return _run_action("restart", args)


def compose_gateway_up(args: dict, **kwargs) -> str:
    """Bring a compose project up (`docker compose up -d`). Refused by the
    gateway itself if the project is in its SELF_EXCLUDE_PROJECTS list."""
    return _run_action("up", args)


def compose_gateway_down(args: dict, **kwargs) -> str:
    """Stop a compose project (`docker compose down`). Refused by the
    gateway itself if the project is in its SELF_EXCLUDE_PROJECTS list."""
    return _run_action("down", args)


def compose_gateway_pull(args: dict, **kwargs) -> str:
    """Pull the latest images for a compose project's services. Not blocked
    by SELF_EXCLUDE_PROJECTS - pulling only downloads images, it does not
    recreate a running container. Follow with compose_gateway_up to actually
    run the pulled image, which is where self-exclusion applies."""
    return _run_action("pull", args)
