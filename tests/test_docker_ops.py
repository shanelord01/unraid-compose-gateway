from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from unraid_compose_gateway import docker_ops

_SAMPLE_OUTPUT = (
    "Deleted Images:\n"
    "untagged: myimage:old\n"
    "deleted: sha256:aaaa\n"
    "deleted: sha256:bbbb\n"
    "\n"
    "Total reclaimed space: 7.566GB"
)


def test_prune_parses_deleted_count_and_reclaimed_space(settings):
    with patch("unraid_compose_gateway.docker_ops.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout=_SAMPLE_OUTPUT, stderr="")
        result = docker_ops.prune_dangling_images(settings)
    assert result.deleted_count == 2
    assert result.reclaimed_display == "7.566GB"
    assert "Total reclaimed space" in result.output


def test_prune_handles_nothing_to_remove(settings):
    with patch("unraid_compose_gateway.docker_ops.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="Total reclaimed space: 0B", stderr="")
        result = docker_ops.prune_dangling_images(settings)
    assert result.deleted_count == 0
    assert result.reclaimed_display == "0B"


def test_prune_uses_dangling_only_never_dash_a(settings):
    """The single most important safety property of this function: it must
    never pass -a/--all, which would also remove images not currently
    backing any running container."""
    with patch("unraid_compose_gateway.docker_ops.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout=_SAMPLE_OUTPUT, stderr="")
        docker_ops.prune_dangling_images(settings)
    args = run.call_args[0][0]
    assert args == ["docker", "image", "prune", "-f"]
    assert "-a" not in args
    assert "--all" not in args


def test_prune_raises_on_nonzero_exit(settings):
    with patch("unraid_compose_gateway.docker_ops.subprocess.run") as run:
        run.return_value = MagicMock(returncode=1, stdout="", stderr="permission denied")
        with pytest.raises(docker_ops.PruneCommandFailed) as excinfo:
            docker_ops.prune_dangling_images(settings)
    assert "permission denied" in excinfo.value.output


def test_prune_raises_on_timeout(settings):
    with patch("unraid_compose_gateway.docker_ops.subprocess.run") as run:
        run.side_effect = subprocess.TimeoutExpired(cmd="docker", timeout=5)
        with pytest.raises(docker_ops.PruneCommandFailed):
            docker_ops.prune_dangling_images(settings)
