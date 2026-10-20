"""Linux bubblewrap confinement for workspace shell (spec §9)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from sevn.domain.errors import DomainError
from sevn.paths import Paths

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
        # Mask /tmp before binding the workspace and shared dirs. Pytest (and
        # some users) put those under /tmp; a later tmpfs would hide them.
        "--tmpfs",
        "/tmp",  # noqa: S108  # writable tmp inside the container, not a host file
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
    ]
    # The host home holds the database, the secret store, the age key and the
    # run token. Mask them: ``--ro-bind / /`` would expose the rest of the host.
    paths = Paths.from_env()
    sidecars = tuple(
        paths.db.with_name(paths.db.name + suffix) for suffix in ("-wal", "-shm", "-journal")
    )
    for secret_file in (paths.db, *sidecars, paths.secrets_file):
        if secret_file.is_file():
            args.extend(["--ro-bind", "/dev/null", str(secret_file)])
    for secret_dir in (paths.keys, paths.run, paths.logs):
        if secret_dir.is_dir():
            args.extend(["--tmpfs", str(secret_dir)])
    args.extend(["--chdir", str(workspace)])
    home = Path(os.environ.get("HOME", str(Path.home()))).expanduser().resolve()
    for name in _HIDDEN:
        secret = home / name
        if secret.is_dir():
            args.extend(["--tmpfs", str(secret)])
    if not network:
        args.append("--unshare-net")
    args.extend([_SHELL, "-c", command])
    return args
