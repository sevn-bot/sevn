"""macOS Seatbelt profile for workspace shell (spec §9)."""

from __future__ import annotations

import os
from pathlib import Path

from sevn.paths import Paths

_PROFILE = Path(__file__).resolve().parent / "profiles" / "sevn-workspace.sb"
_SANDBOX_EXEC = "/usr/bin/sandbox-exec"
_SHELL = "/bin/sh"


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
