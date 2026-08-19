"""Hermes Agent plugin: talk to a running unraid-compose-gateway sidecar.

Scoped Docker Compose control (start/stop/restart/pull for named projects),
container log access, and Unraid plugin update detection - all through the
gateway's HTTP API, never through docker.sock directly. The gateway enforces
its own allowlist and self-exclude list server-side; GATEWAY_ALLOW_WRITES
here only controls whether this plugin will attempt a mutating call at all,
the same intent-layer role UNRAID_SCOPES plays in the sibling hermes-unraid
plugin.
"""

from . import schemas, settings, tools

_READ_TOOLS = (
    ("ucg_whoami", schemas.WHOAMI, tools.ucg_whoami),
    ("ucg_projects", schemas.PROJECTS, tools.ucg_projects),
    ("ucg_status", schemas.STATUS, tools.ucg_status),
    ("ucg_logs", schemas.LOGS, tools.ucg_logs),
    ("ucg_plugin_updates", schemas.PLUGIN_UPDATES, tools.ucg_plugin_updates),
)

_WRITE_TOOLS = (
    ("ucg_restart", schemas.RESTART, tools.ucg_restart),
    ("ucg_up", schemas.UP, tools.ucg_up),
    ("ucg_down", schemas.DOWN, tools.ucg_down),
    ("ucg_pull", schemas.PULL, tools.ucg_pull),
    ("ucg_prune_dangling_images", schemas.PRUNE_IMAGES, tools.ucg_prune_dangling_images),
)


def register(ctx):
    for name, schema, handler in _READ_TOOLS:
        ctx.register_tool(name=name, toolset="ucg", schema=schema, handler=handler)

    if bool(settings.load().get("allow_writes")):
        for name, schema, handler in _WRITE_TOOLS:
            ctx.register_tool(name=name, toolset="ucg", schema=schema, handler=handler)

    def _handle_ucg(raw_args: str) -> str:
        return tools.ucg_whoami({})

    ctx.register_command(
        "ucg",
        handler=_handle_ucg,
        description="unraid-compose-gateway status: allowed projects and exclude list",
    )
