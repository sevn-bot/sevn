"""Docker runner for the isolated access level (spec §9)."""

from __future__ import annotations

import shutil
from pathlib import Path

from sevn.domain.errors import DomainError

_IMAGE = "alpine:3.20"
_SHELL = "/bin/sh"


def argv(command: str, *, workspace: Path, shared: Path, network: bool) -> list[str]:
    """``docker run --rm`` with the workspace mounted and the command as pid 1."""
    binary = shutil.which("docker")
    if binary is None or not Path(binary).is_absolute():
        raise DomainError("invalid_params", "docker is not installed")
    args = [
        binary,
        "run",
        "--rm",
        "-v",
        f"{workspace}:{workspace}",
        "-w",
        str(workspace),
        "-v",
        f"{shared}:{shared}",
    ]
    if not network:
        args.extend(["--network", "none"])
    args.extend([_IMAGE, _SHELL, "-c", command])
    return args
