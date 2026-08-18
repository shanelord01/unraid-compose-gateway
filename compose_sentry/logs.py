"""Container log access via the Docker SDK.

Deliberately unrestricted by ALLOWED_PROJECTS: reading a container's own
stdout/stderr is not a control operation, and Hermes reading its own logs is
the same "harmless" case called out in the design - the thing that needs
gating is *changing* container state, not *observing* it. If you want to
restrict which containers can be read, put a reverse proxy or network policy
in front of this sidecar rather than encoding a second allowlist here.
"""

from __future__ import annotations

import docker
from docker.errors import NotFound

from compose_sentry.config import Settings


class ContainerNotFound(Exception):
    pass


def get_logs(container_name: str, tail: int, since: str | None, settings: Settings) -> list[str]:
    tail = max(1, min(tail, settings.log_tail_max))
    client = docker.from_env()
    try:
        container = client.containers.get(container_name)
    except NotFound as exc:
        raise ContainerNotFound(f"no container named '{container_name}'") from exc

    kwargs: dict = {"tail": tail, "timestamps": True, "stdout": True, "stderr": True}
    if since:
        kwargs["since"] = since

    raw = container.logs(**kwargs)
    text = raw.decode("utf-8", errors="replace")
    return text.splitlines()
