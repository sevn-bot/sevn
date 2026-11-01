"""Linux bubblewrap confinement for workspace shell (spec §9)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from sevn.domain.errors import DomainError
from sevn.paths import Paths

_SHELL = "/bin/sh"
_RUNTIME_DIRS = (Path("/run"), Path("/var/run"))
_RESOLV_CONF = Path("/etc/resolv.conf")
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


def argv(
    command: str,
    *,
    workspace: Path,
    shared: Path,
    network: bool,
    git_metadata: Path | None = None,
) -> list[str]:
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
    # A read-only bind still permits connecting to filesystem UNIX sockets.
    # Hide host service sockets even when IP networking is explicitly allowed.
    runtime_roots = {path.resolve() for path in _RUNTIME_DIRS if path.is_dir()}
    for runtime_dir in sorted(runtime_roots):
        args.extend(["--tmpfs", str(runtime_dir)])
    paths = Paths.from_env()
    home = Path(os.environ.get("HOME", str(Path.home()))).expanduser().resolve()
    masked_home = home != Path("/") and home.is_dir()
    # The sevn home and the workspaces folder hold every bot's files. Hide both
    # before the user's home is masked (one may contain the other) and before
    # this bot's workspace and Shared are bound back in.
    masked: list[Path] = []
    for root in _sevn_roots(paths, home):
        args.extend(["--tmpfs", str(root)])
        masked.append(root)
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
    if git_metadata is not None:
        args.extend(["--bind", str(git_metadata), str(git_metadata)])
    # The host home holds the database, the secret store, the age key and the
    # run token. Under the user's home the tmpfs already hides them; SEVN_HOME
    # can move them anywhere, so mask them again.
    hidden = [*masked, home] if masked_home else masked
    sidecars = tuple(
        paths.db.with_name(paths.db.name + suffix) for suffix in ("-wal", "-shm", "-journal")
    )
    for secret_file in (paths.db, *sidecars, paths.secrets_file):
        if secret_file.is_file() and not _inside_any(secret_file, hidden):
            args.extend(["--ro-bind", "/dev/null", str(secret_file)])
    for secret_dir in (paths.keys, paths.run, paths.logs):
        if secret_dir.is_dir() and not _inside_any(secret_dir, hidden):
            args.extend(["--tmpfs", str(secret_dir)])
    # /etc/resolv.conf commonly points into /run. Restore just that regular
    # file, read-only, while leaving service sockets hidden.
    resolver = _RESOLV_CONF.resolve()
    if (
        network
        and resolver.is_file()
        and any(resolver.is_relative_to(root) for root in runtime_roots)
    ):
        args.extend(["--ro-bind", str(resolver), str(resolver)])
    args.extend(["--chdir", str(workspace)])
    args.extend([_SHELL, "-c", command])
    return args


def _sevn_roots(paths: Paths, home: Path) -> list[Path]:
    """Existing sevn home and workspaces folder, outermost only.

    ``/``, the user's home and any ancestor of the user's home are skipped:
    masking them would hide the system or the readable toolchain paths. The
    user's home is masked separately.
    """
    chosen: list[Path] = []
    for raw in (paths.home, paths.workspaces):
        root = raw.expanduser().resolve()
        if not root.is_dir() or root == Path("/") or _inside(home, root):
            continue
        if any(_inside(root, kept) for kept in chosen):
            continue
        chosen = [kept for kept in chosen if not _inside(kept, root)]
        chosen.append(root)
    return chosen


def _inside_any(path: Path, roots: list[Path]) -> bool:
    return any(_inside(path, root) for root in roots)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return False
    return True
