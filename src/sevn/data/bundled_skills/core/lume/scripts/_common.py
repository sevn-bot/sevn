#!/usr/bin/env python3
"""Shared helpers for bundled ``lume`` skill scripts.

Module: sevn.data.bundled_skills.core.lume.scripts._common
Depends: subprocess, sevn.config.loader, sevn.lcm.script_cli, sevn.skills.lume, sevn.skills.errors

Exports:
    ensure_lume_ready — Load workspace config and validate lume preconditions.
    run_lume_cli — Run the resolved ``lume`` executable with args.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Any

from sevn.config.loader import SevnJsonNotFoundError, load_workspace
from sevn.lcm.script_cli import workspace_from_env
from sevn.skills.errors import SKILL_VALIDATION, SkillExecutionError
from sevn.skills.lume import lume_config_enabled, resolve_lume_command, validate_lume_host

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig


def ensure_lume_ready() -> WorkspaceConfig:
    """Load workspace config and validate that lume may run on this host.

    Returns:
        WorkspaceConfig: Parsed workspace config after validation.

    Raises:
        SkillExecutionError: When config is missing, disabled, or host preconditions fail.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(ensure_lume_ready)
        True
    """
    workspace = workspace_from_env()
    try:
        cfg, _layout = load_workspace(start_dir=workspace)
    except SevnJsonNotFoundError as exc:
        raise SkillExecutionError(str(exc), code=SKILL_VALIDATION) from exc
    except Exception as exc:
        raise SkillExecutionError(str(exc), code=SKILL_VALIDATION) from exc
    if not lume_config_enabled(cfg):
        msg = "skills.lume.enabled is false"
        raise SkillExecutionError(msg, code=SKILL_VALIDATION)
    validate_lume_host(cfg=cfg)
    return cfg


def run_lume_cli(
    cfg: WorkspaceConfig,
    args: list[str],
    *,
    timeout: int = 3600,
) -> subprocess.CompletedProcess[str]:
    """Run the ``lume`` CLI with ``args`` and capture stdout/stderr.

    Args:
        cfg (WorkspaceConfig): Workspace config for command resolution.
        args (list[str]): Subcommand arguments after ``argv[0]``.
        timeout (int, optional): Subprocess timeout in seconds.

    Returns:
        subprocess.CompletedProcess[str]: Completed process with captured streams.

    Raises:
        SkillExecutionError: When the subprocess fails or times out.

    Examples:
        >>> import inspect
        >>> sig = inspect.signature(run_lume_cli)
        >>> "timeout" in sig.parameters
        True
    """
    command = resolve_lume_command(cfg)
    try:
        return subprocess.run(
            [command, *args],
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        msg = f"lume {' '.join(args)} failed: {detail}"
        raise SkillExecutionError(msg, code=SKILL_VALIDATION) from exc
    except subprocess.TimeoutExpired as exc:
        msg = f"lume {' '.join(args)} timed out after {timeout}s"
        raise SkillExecutionError(msg, code=SKILL_VALIDATION) from exc
    except OSError as exc:
        msg = f"failed to spawn lume: {exc}"
        raise SkillExecutionError(msg, code=SKILL_VALIDATION) from exc


def cli_output_payload(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """Build a JSON-friendly payload from a completed ``lume`` subprocess.

    Args:
        proc (subprocess.CompletedProcess[str]): Completed ``lume`` invocation.

    Returns:
        dict[str, Any]: stdout/stderr/exit_code fields for skill runners.

    Examples:
        >>> import subprocess
        >>> proc = subprocess.CompletedProcess(args=["lume"], returncode=0, stdout="ok\\n")
        >>> cli_output_payload(proc)["stdout"]
        'ok\\n'
    """
    return {
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "exit_code": proc.returncode,
    }
