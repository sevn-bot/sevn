"""Helpers for the bundled ``proton-management`` skill."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Final

PROTON_MANAGEMENT_SKILL_ID: Final[str] = "proton-management"
_DRY_RUN_ENV: Final[str] = "SEVN_PROTON_DRY_RUN"


@dataclass(frozen=True)
class ProtonProfile:
    id: str
    label: str
    user_env: str
    password_env: str = ""
    totp_env: str = ""


def dry_run_requested(*, cli_flag: bool = False) -> bool:
    if cli_flag:
        return True
    return os.environ.get(_DRY_RUN_ENV, "").strip().lower() in {"1", "true", "yes"}


def resolve_cli() -> str | None:
    for name in ("proton-cli", "python3", "python"):
        path = shutil.which(name)
        if path and name == "proton-cli":
            return path
    module = shutil.which("python3") or shutil.which("python")
    if module:
        return module
    return None


def cli_argv(base: list[str], *, profile: str = "", module_mode: bool = False) -> list[str]:
    argv = ["-m", "proton_cli", *base] if module_mode else list(base)
    if profile:
        argv = [*argv[:1], "--profile", profile, *argv[1:]] if not module_mode else [*argv, "--profile", profile]
    return argv


def run_proton_cli(
    args: list[str],
    *,
    profile: str = "",
    env: dict[str, str] | None = None,
    timeout: float = 120.0,
) -> tuple[int, str, str]:
    """Run proton-cli and return ``(code, stdout, stderr)``."""
    exe = resolve_cli()
    if exe is None:
        return 127, "", "proton-cli not found on PATH"
    module_mode = exe.endswith("python") or exe.endswith("python3")
    argv = cli_argv(args, profile=profile, module_mode=module_mode)
    if module_mode:
        cmd = [exe, *argv]
    else:
        cmd = [exe, *args]
        if profile:
            cmd = [exe, "--profile", profile, *args]
    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=proc_env,
        timeout=timeout,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def status_payload(*, profile: str = "default") -> dict[str, object]:
    exe = resolve_cli()
    session_path = _session_file(profile)
    return {
        "cli": exe,
        "cli_installed": exe is not None,
        "profile": profile,
        "session_file": str(session_path),
        "session_exists": session_path.is_file(),
    }


def _session_file(profile: str) -> "os.PathLike[str]":
    from pathlib import Path

    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "proton-cli" / "sessions" / f"{profile or 'default'}.json"
