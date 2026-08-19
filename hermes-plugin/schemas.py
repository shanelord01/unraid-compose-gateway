"""Tool schemas for the ucg plugin. Descriptions are what the
LLM reads - they say when to use each tool and what it returns."""

_PROJECT = {
    "type": "string",
    "description": "Compose project name, as returned by ucg_projects",
}

WHOAMI = {
    "name": "ucg_whoami",
    "description": (
        "Check what this unraid-compose-gateway instance is configured to do: "
        "which compose projects it can act on, which of those are excluded "
        "from mutating calls, and whether Unraid plugin update checking is "
        "enabled. Call this first if unsure what's available."
    ),
    "parameters": {"type": "object", "properties": {}},
}

PROJECTS = {
    "name": "ucg_projects",
    "description": (
        "List the Docker Compose projects this gateway is allowed to act on, "
        "whether each actually has a compose file on disk, whether it is "
        "self-excluded (protected from restart/up/down), and its Unraid "
        "Compose Manager 'Auto Start' checkbox state as `autostart` "
        "(true/false/null). null means unknown (file missing/unreadable) - "
        "treat that as 'do not assume', not as false. If a project's "
        "autostart is explicitly false, do not call ucg_up for it after a "
        "pull, even if its image or config changed - the operator has "
        "deliberately chosen not to have this stack come up automatically, "
        "and applying an update is not the same as consenting to a start."
    ),
    "parameters": {"type": "object", "properties": {}},
}

STATUS = {
    "name": "ucg_status",
    "description": (
        "Per-service status for one compose project: running/exited state and "
        "health, if the project defines a healthcheck. Use before or after a "
        "restart/up/down/pull call to confirm the result."
    ),
    "parameters": {
        "type": "object",
        "properties": {"project": _PROJECT},
        "required": ["project"],
    },
}

LOGS = {
    "name": "ucg_logs",
    "description": (
        "Tail recent log lines for any container by name - not limited to "
        "compose-managed ones. Use for troubleshooting a specific service."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Container name"},
            "tail": {"type": "integer", "description": "Number of lines to return"},
            "since": {
                "type": "string",
                "description": "Only return logs after this time, e.g. an RFC3339 timestamp or a duration like '10m'",
            },
        },
        "required": ["name"],
    },
}

PLUGIN_UPDATES = {
    "name": "ucg_plugin_updates",
    "description": (
        "Check every installed Unraid plugin for an available update, by "
        "comparing the locally installed .plg version against the current one "
        "at its pluginURL - the same check Unraid's own 'Check for Updates' "
        "button performs. Read-only; it does not install anything. Results "
        "are cached on the gateway - pass force=true to bypass that and check "
        "immediately. Returns 'disabled' if the gateway does not have "
        "PLUGIN_DIR configured."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "force": {"type": "boolean", "description": "Bypass the cache and check now"},
        },
    },
}

_MUTATING_NOTE = (
    " Refused by the gateway if this project is in its SELF_EXCLUDE_PROJECTS "
    "list, regardless of what this agent asks for - that boundary is not "
    "something a tool call can talk its way around."
)

RESTART = {
    "name": "ucg_restart",
    "description": "Restart a compose project's services (`docker compose restart`)." + _MUTATING_NOTE,
    "parameters": {
        "type": "object",
        "properties": {"project": _PROJECT},
        "required": ["project"],
    },
}

UP = {
    "name": "ucg_up",
    "description": (
        "Bring a compose project up in detached mode (`docker compose up -d`). "
        "Recreates containers whose image or config changed; leaves others "
        "alone. Run ucg_pull first to actually refresh images."
    )
    + _MUTATING_NOTE,
    "parameters": {
        "type": "object",
        "properties": {"project": _PROJECT},
        "required": ["project"],
    },
}

DOWN = {
    "name": "ucg_down",
    "description": "Stop and remove a compose project's containers (`docker compose down`)." + _MUTATING_NOTE,
    "parameters": {
        "type": "object",
        "properties": {"project": _PROJECT},
        "required": ["project"],
    },
}

PULL = {
    "name": "ucg_pull",
    "description": (
        "Pull the latest images for a compose project's services "
        "(`docker compose pull`). Only downloads images - does not restart or "
        "recreate anything, so this is not blocked by SELF_EXCLUDE_PROJECTS. "
        "Follow with ucg_up to actually run the pulled image."
    ),
    "parameters": {
        "type": "object",
        "properties": {"project": _PROJECT},
        "required": ["project"],
    },
}

PRUNE_IMAGES = {
    "name": "ucg_prune_dangling_images",
    "description": (
        "Remove dangling (untagged, unreferenced) Docker images host-wide "
        "(`docker image prune -f`, never -a). This is what accumulates from "
        "repeated ucg_pull + ucg_up cycles recreating containers on new "
        "image digests, orphaning the old layers - a real, growing disk-"
        "space cost if never cleaned up. Not project-scoped - there is no "
        "per-project allowlist or SELF_EXCLUDE_PROJECTS check here, it acts "
        "on the whole Docker daemon - and it never removes an image backing "
        "a running OR stopped-but-referenced container, only genuinely "
        "unreferenced ones. Safe to call any time; a reasonable place is "
        "once after a batch of pull/up calls."
    ),
    "parameters": {"type": "object", "properties": {}},
}
