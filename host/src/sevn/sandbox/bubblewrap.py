"""Linux bubblewrap confinement for workspace shell (spec §9)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from sevn.domain.errors import DomainError

_SHELL = "/bin/sh"
_HIDDEN = (
    ".ssh",
    ".aws",
    "Library/Keychains",
    ".config/gh",
    ".config/opencode",
    ".codex",
    ".claude",
    ".config/claude",
)


def argv(command: str, *, workspace: Path, shared: Path, network: bool) -> list[str]:
    """Run ``command`` with a read-only system and a writable workspace."""
    binary = shutil.which("bwrap")
    if binary is None or not Path(binary).is_absolute():
        raise DomainError("invalid_params", "bubblewrap is not installed")
    args = [
        binary,
        "--die-with-parent",
        "--ro-bind",
        "/",
        "/",
        "--bind",
        str(workspace),
        str(workspace),
        "--bind",
        str(shared),
        str(shared),
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        "--tmpfs",
        "/tmp",  # noqa: S108  # writable tmp inside the container, not a host file
        "--chdir",
        str(workspace),
    ]
    home = Path(os.environ.get("HOME", str(Path.home()))).expanduser().resolve()
    for name in _HIDDEN:
        secret = home / name
        if secret.is_dir():
            args.extend(["--tmpfs", str(secret)])
    if not network:
        args.append("--unshare-net")
    args.extend([_SHELL, "-c", command])
    return args
