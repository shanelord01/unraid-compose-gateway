"""Host-wide Docker maintenance operations that aren't scoped to a single
compose project.

Kept separate from compose_control.py: these don't go through
ALLOWED_PROJECTS/SELF_EXCLUDE_PROJECTS at all - there's no "project" to
check against, this acts on the whole Docker daemon the gateway's
docker.sock mount already has access to.
"""

from __future__ import annotations

import re
import subprocess

from unraid_compose_gateway.config import Settings
from unraid_compose_gateway.models import PruneResult


class PruneCommandFailed(Exception):
    """Raised when `docker image prune` itself exits non-zero or times out."""

    def __init__(self, message: str, exit_code: int, output: str):
        super().__init__(message)
        self.exit_code = exit_code
        self.output = output


_RECLAIMED_RE = re.compile(r"Total reclaimed space:\s*(.+)", re.IGNORECASE)


def prune_dangling_images(settings: Settings) -> PruneResult:
    """`docker image prune -f` - dangling (untagged AND unreferenced)
    images only. Deliberately never `-a`: that flag also removes any image
    not currently backing a running container, which can include an image
    a stopped-but-not-removed service still references. "Dangling" is the
    safe subset - an image left behind because a compose recreate retagged
    `latest` onto a new digest, orphaning the old layers under `<none>`,
    which is exactly what accumulates from repeated ucg_pull + ucg_up
    cycles over time.
    """
    try:
        completed = subprocess.run(
            ["docker", "image", "prune", "-f"],
            capture_output=True, text=True, timeout=settings.compose_timeout_seconds,
        )
    except subprocess.TimeoutExpired as e:
        raise PruneCommandFailed("docker image prune timed out", -1, str(e)) from e

    if completed.returncode != 0:
        raise PruneCommandFailed(
            f"docker image prune exited {completed.returncode}",
            completed.returncode,
            (completed.stderr or completed.stdout or "").strip(),
        )

    output = completed.stdout.strip()
    deleted_count = output.count("\ndeleted:") + (1 if output.startswith("deleted:") else 0)
    match = _RECLAIMED_RE.search(output)
    reclaimed_display = match.group(1).strip() if match else None
    return PruneResult(output=output, deleted_count=deleted_count, reclaimed_display=reclaimed_display)
