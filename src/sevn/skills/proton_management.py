"""Helpers for the bundled ``proton-management`` skill.

Module: sevn.skills.proton_management
Depends: dataclasses, os, shutil, subprocess

Exports:
    ProtonProfile — one configured Proton CLI profile (no secret material).
    dry_run_requested — CLI/env dry-run selector.
    resolve_cli — locate ``proton-cli`` or a Python interpreter for ``-m proton_cli``.
    cli_argv — build argv with optional profile and module-mode prefix.
    run_proton_cli — execute proton-cli and capture stdout/stderr (sync wrapper).
    run_proton_cli_async — async subprocess variant for gateway/skill async paths.
    status_payload — JSON-safe install/session status for skill scripts.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess  # nosec B404
from dataclasses import dataclass
from pathlib import Path
from typing import Final

PROTON_MANAGEMENT_SKILL_ID: Final[str] = "proton-management"
_DRY_RUN_ENV: Final[str] = "SEVN_PROTON_DRY_RUN"


@dataclass(frozen=True)
class ProtonProfile:
    """One configured Proton CLI profile (credentials resolved separately).

    Attributes:
        id (str): Stable profile id referenced by skill scripts.
        label (str): Operator-facing display name.
        user_env (str): Environment variable holding Proton username.
        password_env (str): Environment variable holding password (optional).
        totp_env (str): Environment variable holding TOTP secret (optional).
    """

    id: str
    label: str
    user_env: str
    password_env: str = ""
    totp_env: str = ""


def dry_run_requested(*, cli_flag: bool = False) -> bool:
    """Return whether proton-management scripts should plan without side effects.

    Args:
        cli_flag (bool): When True, force dry-run regardless of environment.

    Returns:
        bool: True when dry-run is requested.

    Examples:
        >>> dry_run_requested(cli_flag=True)
        True
    """
    if cli_flag:
        return True
    return os.environ.get(_DRY_RUN_ENV, "").strip().lower() in {"1", "true", "yes"}


def resolve_cli() -> str | None:
    """Locate ``proton-cli`` or a Python interpreter for ``-m proton_cli``.

    Returns:
        str | None: Executable path, or None when neither is on PATH.

    Examples:
        >>> resolve_cli() is None or isinstance(resolve_cli(), str)
        True
    """
    for name in ("proton-cli", "python3", "python"):
        path = shutil.which(name)
        if path and name == "proton-cli":
            return path
    module = shutil.which("python3") or shutil.which("python")
    if module:
        return module
    return None


def cli_argv(base: list[str], *, profile: str = "", module_mode: bool = False) -> list[str]:
    """Build argv with optional profile and module-mode prefix.

    Args:
        base (list[str]): Subcommand argv without executable.
        profile (str): Profile name inserted as ``--profile`` when non-empty.
        module_mode (bool): Prefix with ``-m proton_cli`` when True.

    Returns:
        list[str]: argv suitable for subprocess.

    Examples:
        >>> cli_argv(["pass", "vaults", "list"], profile="work", module_mode=True)
        ['-m', 'proton_cli', '--profile', 'work', 'pass', 'vaults', 'list']
    """
    if module_mode:
        argv = ["-m", "proton_cli"]
        if profile:
            argv.extend(["--profile", profile])
        argv.extend(base)
        return argv
    argv = list(base)
    if profile:
        return ["--profile", profile, *argv]
    return argv


async def run_proton_cli_async(
    args: list[str],
    *,
    profile: str = "",
    env: dict[str, str] | None = None,
    timeout_s: float = 120.0,
) -> tuple[int, str, str]:
    """Run proton-cli asynchronously and return ``(code, stdout, stderr)``.

    Args:
        args (list[str]): Subcommand argv without executable.
        profile (str): Profile name passed as ``--profile`` when non-empty.
        env (dict[str, str] | None): Extra environment variables merged into the child.
        timeout_s (float): Subprocess timeout in seconds.

    Returns:
        tuple[int, str, str]: Exit code, stdout, and stderr text.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(run_proton_cli_async)
        True
    """
    exe = resolve_cli()
    if exe is None:
        return 127, "", "proton-cli not found on PATH"
    module_mode = exe.endswith(("python", "python3"))
    argv = cli_argv(args, profile=profile, module_mode=module_mode)
    cmd = [exe, *argv]
    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=proc_env,
    )
    try:
        async with asyncio.timeout(timeout_s):
            stdout_b, stderr_b = await proc.communicate()
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, "", f"proton-cli timed out after {timeout_s}s"
    return (
        proc.returncode or 0,
        stdout_b.decode("utf-8", errors="replace"),
        stderr_b.decode("utf-8", errors="replace"),
    )


def run_proton_cli(
    args: list[str],
    *,
    profile: str = "",
    env: dict[str, str] | None = None,
    timeout: float = 120.0,
) -> tuple[int, str, str]:
    """Run proton-cli and return ``(code, stdout, stderr)``.

    Args:
        args (list[str]): Subcommand argv without executable.
        profile (str): Profile name passed as ``--profile`` when non-empty.
        env (dict[str, str] | None): Extra environment variables merged into the child.
        timeout (float): Subprocess timeout in seconds.

    Returns:
        tuple[int, str, str]: Exit code, stdout, and stderr text.

    Examples:
        >>> code, out, err = run_proton_cli(["--help"])
        >>> isinstance(code, int) and isinstance(out, str) and isinstance(err, str)
        True
    """
    exe = resolve_cli()
    if exe is None:
        return 127, "", "proton-cli not found on PATH"
    try:
        return asyncio.run(run_proton_cli_async(args, profile=profile, env=env, timeout_s=timeout))
    except RuntimeError:
        # Fallback when already inside a running event loop (skill scripts).
        module_mode = exe.endswith(("python", "python3"))
        argv = cli_argv(args, profile=profile, module_mode=module_mode)
        cmd = [exe, *argv]
        proc_env = os.environ.copy()
        if env:
            proc_env.update(env)
        proc = subprocess.run(  # nosec B603
            cmd,
            capture_output=True,
            text=True,
            env=proc_env,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr


def status_payload(*, profile: str = "default") -> dict[str, object]:
    """Return JSON-safe install and session status for skill scripts.

    Args:
        profile (str): Proton CLI profile name to inspect.

    Returns:
        dict[str, object]: Keys ``cli``, ``cli_installed``, ``profile``,
            ``session_file``, and ``session_exists``.

    Examples:
        >>> payload = status_payload(profile="default")
        >>> "cli_installed" in payload and payload["profile"] == "default"
        True
    """
    exe = resolve_cli()
    session_path = _session_file(profile)
    return {
        "cli": exe,
        "cli_installed": exe is not None,
        "profile": profile,
        "session_file": str(session_path),
        "session_exists": session_path.is_file(),
    }


def _session_file(profile: str) -> Path:
    """Return the on-disk session JSON path for ``profile``.

    Args:
        profile (str): Proton CLI profile name.

    Returns:
        pathlib.Path: Path under XDG config or ``~/.config/proton-cli/sessions/``.

    Examples:
        >>> path = _session_file("default")
        >>> str(path).endswith("default.json")
        True
    """
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "proton-cli" / "sessions" / f"{profile or 'default'}.json"
