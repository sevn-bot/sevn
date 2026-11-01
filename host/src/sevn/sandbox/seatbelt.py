"""macOS Seatbelt profile for workspace shell (spec §9)."""

from __future__ import annotations

import os
from pathlib import Path

from sevn.paths import Paths

_PROFILE = Path(__file__).resolve().parent / "profiles" / "sevn-workspace.sb"
_SANDBOX_EXEC = "/usr/bin/sandbox-exec"
_SHELL = "/bin/sh"

# macOS mktemp takes _CS_DARWIN_USER_TEMP_DIR before TMPDIR for bare and -t
# calls (mktemp(1)), and the profile keeps that host directory read-only, so
# setting TMPDIR alone cannot fix them. This shim builds those templates inside
# $TMPDIR. Explicit templates and any other flag pass straight through.
_MKTEMP_SHIM = """#!/bin/sh
real=/usr/bin/mktemp
flags=""
prefix=tmp
want_prefix=0
for arg in "$@"; do
  if [ "$want_prefix" = 1 ]; then
    prefix=$arg
    want_prefix=0
    continue
  fi
  case "$arg" in
    -t) want_prefix=1 ;;
    -t*) prefix=${arg#-t} ;;
    -d | -q | -u) flags="$flags $arg" ;;
    *) exec "$real" "$@" ;;
  esac
done
if [ -z "$TMPDIR" ] || [ "$want_prefix" = 1 ]; then
  exec "$real" "$@"
fi
# shellcheck disable=SC2086
exec "$real" $flags "${TMPDIR%/}/$prefix.XXXXXXXXXX"
"""


def argv(command: str, *, workspace: Path, shared: Path, network: bool) -> list[str]:
    """Run ``command`` under ``sevn-workspace.sb``."""
    paths = Paths.from_env()
    home = Path(os.environ.get("HOME", str(Path.home()))).expanduser().resolve()
    return [
        _SANDBOX_EXEC,
        "-f",
        str(_PROFILE),
        "-D",
        f"HOME={home}",
        "-D",
        f"WORKSPACE={workspace}",
        "-D",
        f"SHARED={shared}",
        "-D",
        f"NETWORK={'on' if network else 'off'}",
        "-D",
        f"SEVN_DB={paths.db}",
        "-D",
        f"SEVN_DB_WAL={paths.db.with_name(paths.db.name + '-wal')}",
        "-D",
        f"SEVN_DB_SHM={paths.db.with_name(paths.db.name + '-shm')}",
        "-D",
        f"SEVN_DB_JOURNAL={paths.db.with_name(paths.db.name + '-journal')}",
        "-D",
        f"SEVN_SECRETS={paths.secrets_file}",
        "-D",
        f"SEVN_KEYS={paths.keys}",
        "-D",
        f"SEVN_RUN={paths.run}",
        "-D",
        f"SEVN_LOGS={paths.logs}",
        "-D",
        f"SEVN_HOME={paths.home.expanduser().resolve()}",
        "-D",
        f"SEVN_WORKSPACES={paths.workspaces.expanduser().resolve()}",
        _SHELL,
        "-c",
        command,
    ]


def install_shims(folder: Path) -> Path:
    """Write the shell shims into ``folder`` and return it, for the front of ``PATH``.

    ``folder`` must be inside the workspace: the profile denies reads of the home,
    where a development checkout of the package lives.
    """
    folder.mkdir(parents=True, exist_ok=True)
    shim = folder / "mktemp"
    if not shim.is_file() or shim.read_text(encoding="utf-8") != _MKTEMP_SHIM:
        shim.write_text(_MKTEMP_SHIM, encoding="utf-8")
    shim.chmod(0o755)
    return folder
