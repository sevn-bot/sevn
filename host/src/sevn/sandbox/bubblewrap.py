"""Linux bubblewrap confinement for workspace shell (spec §9)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from sevn.domain.errors import DomainError
from sevn.paths import Paths

_SHELL = "/bin/sh"
# Home paths a command may read: git's config and the usual toolchain installs.
# The rest of the home, including .ssh, .aws and the CLI credential folders,
# is replaced by an empty tmpfs.
_HOME_READABLE = (
    ".gitconfig",
    ".config/git",
    ".local/bin",
    ".local/share/uv",
    ".local/share/pnpm",
    ".cargo/bin",
    ".rustup/toolchains",
    ".nvm/versions",
    ".pyenv/versions",
    ".pyenv/shims",
    ".bun/bin",
    ".deno/bin",
    "go/bin",
)


def argv(command: str, *, workspace: Path, shared: Path, network: bool) -> list[str]:
    """Run ``command`` with a read-only system and a writable workspace.

    Every namespace is new, so the command cannot see or signal host processes
    or read their ``/proc`` entries. ``--new-session`` stops it from pushing
    input into the host's terminal.
    """
    binary = shutil.which("bwrap")
    if binary is None or not Path(binary).is_absolute():
        raise DomainError("invalid_params", "bubblewrap is not installed")
    args = [binary, "--die-with-parent", "--new-session", "--unshare-all"]
    if network:
        args.append("--share-net")
    args.extend(
        [
            "--ro-bind",
            "/",
            "/",
            # Mask /tmp before binding the workspace and shared dirs. Pytest (and
            # some users) put those under /tmp; a later tmpfs would hide them.
            "--tmpfs",
            "/tmp",  # noqa: S108  # writable tmp inside the container, not a host file
        ]
    )
    home = Path(os.environ.get("HOME", str(Path.home()))).expanduser().resolve()
    masked_home = home != Path("/") and home.is_dir()
    if masked_home:
        args.extend(["--tmpfs", str(home)])
        for name in _HOME_READABLE:
            readable = home / name
            if readable.exists():
                args.extend(["--ro-bind", str(readable), str(readable)])
    args.extend(
        [
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
    )
    # The host home holds the database, the secret store, the age key and the
    # run token. Under the user's home the tmpfs already hides them; SEVN_HOME
    # can move them anywhere, so mask them again.
    paths = Paths.from_env()
    sidecars = tuple(
        paths.db.with_name(paths.db.name + suffix) for suffix in ("-wal", "-shm", "-journal")
    )
    for secret_file in (paths.db, *sidecars, paths.secrets_file):
        if secret_file.is_file() and not (masked_home and _inside(secret_file, home)):
            args.extend(["--ro-bind", "/dev/null", str(secret_file)])
    for secret_dir in (paths.keys, paths.run, paths.logs):
        if secret_dir.is_dir() and not (masked_home and _inside(secret_dir, home)):
            args.extend(["--tmpfs", str(secret_dir)])
    args.extend(["--chdir", str(workspace)])
    args.extend([_SHELL, "-c", command])
    return args


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return False
    return True
