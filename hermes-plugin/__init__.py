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
    ("unraid_compose_gateway_whoami", schemas.WHOAMI, tools.unraid_compose_gateway_whoami),
    ("unraid_compose_gateway_projects", schemas.PROJECTS, tools.unraid_compose_gateway_projects),
    ("unraid_compose_gateway_status", schemas.STATUS, tools.unraid_compose_gateway_status),
    ("unraid_compose_gateway_logs", schemas.LOGS, tools.unraid_compose_gateway_logs),
    ("unraid_compose_gateway_plugin_updates", schemas.PLUGIN_UPDATES, tools.unraid_compose_gateway_plugin_updates),
)

_WRITE_TOOLS = (
    ("unraid_compose_gateway_restart", schemas.RESTART, tools.unraid_compose_gateway_restart),
    ("unraid_compose_gateway_up", schemas.UP, tools.unraid_compose_gateway_up),
    ("unraid_compose_gateway_down", schemas.DOWN, tools.unraid_compose_gateway_down),
    ("unraid_compose_gateway_pull", schemas.PULL, tools.unraid_compose_gateway_pull),
)


def register(ctx):
    for name, schema, handler in _READ_TOOLS:
        ctx.register_tool(name=name, toolset="unraid_compose_gateway", schema=schema, handler=handler)

    if bool(settings.load().get("allow_writes")):
        for name, schema, handler in _WRITE_TOOLS:
            ctx.register_tool(name=name, toolset="unraid_compose_gateway", schema=schema, handler=handler)

    def _handle_gateway(raw_args: str) -> str:
        return tools.unraid_compose_gateway_whoami({})

    ctx.register_command(
        "gateway",
        handler=_handle_gateway,
        description="unraid-compose-gateway status: allowed projects and exclude list",
    )
