"""Docker runner for the isolated access level (spec §9)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from sevn.domain.errors import DomainError

_IMAGE = "alpine:3.20"
_SHELL = "/bin/sh"


def argv(
    command: str,
    *,
    workspace: Path,
    shared: Path,
    network: bool,
    git_metadata: Path | None = None,
) -> list[str]:
    """``docker run --rm`` with the workspace mounted and the command as pid 1."""
    binary = shutil.which("docker")
    if binary is None or not Path(binary).is_absolute():
        raise DomainError("invalid_params", "docker is not installed")
    args = [
        binary,
        "run",
        "--rm",
        # tini as pid 1 passes the SIGTERM the docker client forwards on a
        # timeout or cancel; a bare ``sh`` as pid 1 would ignore it.
        "--init",
        # Run as the host user so files created in the bind-mounted workspace
        # stay writable by later file tools.
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--env",
        "HOME=/tmp",
        "-v",
        f"{workspace}:{workspace}",
        "-w",
        str(workspace),
        "-v",
        f"{shared}:{shared}",
    ]
    if git_metadata is not None:
        args.extend(["-v", f"{git_metadata}:{git_metadata}"])
    if not network:
        args.extend(["--network", "none"])
    args.extend([_IMAGE, _SHELL, "-c", command])
    return args
