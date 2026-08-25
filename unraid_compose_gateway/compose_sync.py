"""Keep the gateway's Compose binary matched to the host's.

Compose Manager on Unraid ships its own `docker-compose` binary and updates
it with the plugin. The gateway's image pins a version at build time, which
is right until the host moves. To follow the host without a rebuild, a host
side script writes `docker-compose version --short` to a file the gateway
can read (see contrib/ensure-compose-stacks-up.sh, mounted read-only via
PLUGIN_DIR). This module reads that file, and when it names a version other
than the one currently active, downloads that exact Compose release into the
container's own filesystem, verifies the published sha256, and switches the
gateway's compose command to it.

Nothing from the host is executed and nothing is bind-mounted: the binary
comes from the docker/compose GitHub release, verified, into a directory
the container owns. If anything fails the gateway keeps the version it has,
and the parity guard in compose_version.py still refuses a mismatched `up`.
"""

from __future__ import annotations

import hashlib
import logging
import os
import platform
import re
import threading
import time
import urllib.request
from dataclasses import dataclass

from unraid_compose_gateway import compose_version
from unraid_compose_gateway.config import Settings

_LOG = logging.getLogger("unraid_compose_gateway")

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_RELEASE_URL = "https://github.com/docker/compose/releases/download/v{version}/{asset}"
_DEFAULT_SYNC_DIR = "/var/lib/unraid-compose-gateway/compose"


def _arch() -> str:
    machine = platform.machine()
    return {"amd64": "x86_64", "arm64": "aarch64"}.get(machine, machine)


def asset_name() -> str:
    return f"docker-compose-linux-{_arch()}"


def read_host_version(path: str) -> str | None:
    """The version the host tool reports, or None if the file is missing,
    unreadable, or does not look like a version. A malformed file must
    never trigger a download."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read().strip()
    except OSError:
        return None
    raw = raw[1:] if raw.startswith("v") else raw
    return raw if _VERSION_RE.match(raw) else None


@dataclass(frozen=True)
class Downloaded:
    version: str
    path: str


def _fetch(url: str, timeout: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "unraid-compose-gateway"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https host
        return resp.read()


def download_release(version: str, dest_dir: str, timeout: int = 120, fetch=_fetch) -> Downloaded:
    """Download `docker-compose-linux-<arch>` for `version` and verify it
    against the `.sha256` file published alongside it. Written atomically
    to `<dest_dir>/<version>/docker-compose`. Raises on any failure."""
    if not _VERSION_RE.match(version):
        raise ValueError(f"not a version: {version!r}")
    asset = asset_name()
    binary = fetch(_RELEASE_URL.format(version=version, asset=asset), timeout)
    checksum_doc = fetch(_RELEASE_URL.format(version=version, asset=asset + ".sha256"), timeout).decode()
    expected = _expected_sha256(checksum_doc, asset)
    actual = hashlib.sha256(binary).hexdigest()
    if actual != expected:
        raise RuntimeError(f"sha256 mismatch for {asset} v{version}: expected {expected}, got {actual}")

    target_dir = os.path.join(dest_dir, version)
    os.makedirs(target_dir, exist_ok=True)
    final = os.path.join(target_dir, "docker-compose")
    tmp = final + ".part"
    with open(tmp, "wb") as fh:
        fh.write(binary)
    os.chmod(tmp, 0o755)
    os.replace(tmp, final)
    return Downloaded(version=version, path=final)


def _expected_sha256(checksum_doc: str, asset: str) -> str:
    """The release publishes `<asset>.sha256` in `sha256sum` format:
    `<hex>  <asset>`. Accept a bare hex line too."""
    for line in checksum_doc.splitlines():
        parts = line.split()
        if not parts:
            continue
        if len(parts) == 1 and re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            return parts[0]
        if len(parts) >= 2 and parts[-1].lstrip("*") == asset and re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            return parts[0]
    raise RuntimeError(f"no sha256 for {asset} in checksum file")


def sync_once(settings: Settings, *, downloader=download_release) -> str | None:
    """Compare the host's version file with the active Compose version and
    switch to a downloaded copy if they differ. Returns the version now
    active, or None if the feature is off or the file gave no version.
    Never raises."""
    path = settings.host_compose_version_file
    if not path:
        return None
    host = read_host_version(path)
    if host is None:
        return None
    try:
        active = compose_version.gateway_compose_version()
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("compose sync: cannot determine active compose version: %s", exc)
        return None
    if host == active:
        return active

    cached = os.path.join(settings.compose_sync_dir, host, "docker-compose")
    try:
        if os.path.isfile(cached):
            downloaded = Downloaded(version=host, path=cached)
        else:
            _LOG.info("compose sync: host reports Compose %s, gateway has %s; downloading v%s", host, active, host)
            downloaded = downloader(host, settings.compose_sync_dir)
        reported = compose_version.version_of([downloaded.path])
        if reported != host:
            raise RuntimeError(f"downloaded binary reports {reported}, expected {host}")
        compose_version.set_compose_command([downloaded.path], source="synced")
        _LOG.info("compose sync: now running Compose %s from %s (matches host)", host, downloaded.path)
        return host
    except Exception as exc:  # noqa: BLE001
        _LOG.warning(
            "compose sync: could not switch to Compose %s (%s); staying on %s, `up` on projects "
            "created by %s stays refused",
            host, exc, active, host,
        )
        return active


def start_background_sync(settings: Settings) -> threading.Thread | None:
    """Run sync_once now and then every `compose_sync_interval_seconds`.
    Returns the thread, or None when the feature is off."""
    if not settings.host_compose_version_file:
        return None

    def loop() -> None:
        while True:
            sync_once(settings)
            time.sleep(settings.compose_sync_interval_seconds)

    thread = threading.Thread(target=loop, name="compose-sync", daemon=True)
    thread.start()
    return thread


def main(argv: list[str]) -> int:
    """`python -m unraid_compose_gateway.compose_sync <version> [dest_dir]`:
    download and verify one release, then print the version the binary
    reports. Used by CI to exercise the real download path."""
    if len(argv) < 2:
        print("usage: compose_sync <version> [dest_dir]")
        return 2
    version = argv[1]
    dest = argv[2] if len(argv) > 2 else _DEFAULT_SYNC_DIR
    downloaded = download_release(version, dest)
    print(compose_version.version_of([downloaded.path]))
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv))
