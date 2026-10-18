"""macOS Seatbelt profile for workspace shell (spec §9)."""

from __future__ import annotations

from pathlib import Path

_PROFILE = Path(__file__).resolve().parent / "profiles" / "sevn-workspace.sb"
_SANDBOX_EXEC = "/usr/bin/sandbox-exec"
_SHELL = "/bin/sh"


def argv(command: str, *, workspace: Path, shared: Path, network: bool) -> list[str]:
    """Run ``command`` under ``sevn-workspace.sb``."""
    return [
        _SANDBOX_EXEC,
        "-f",
        str(_PROFILE),
        "-D",
        f"WORKSPACE={workspace}",
        "-D",
        f"SHARED={shared}",
        "-D",
        f"NETWORK={'on' if network else 'off'}",
        _SHELL,
        "-c",
        command,
    ]
