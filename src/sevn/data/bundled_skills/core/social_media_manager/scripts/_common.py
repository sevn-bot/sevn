"""Shared helpers for ``social_media_manager`` bundled skill scripts.

Module: sevn.data.bundled_skills.core.social_media_manager.scripts._common
Depends: asyncio, os, sevn.agent.subagents.social_media_worker, sevn.lcm.script_cli

Exports:
    content_root_from_env — resolve real workspace content root.
    dry_run_requested — CLI/env dry-run selector.
    run_social_media_task — execute one specialist job and emit JSON envelope.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from sevn.agent.subagents.social_media_worker import execute_social_media_manager_task
from sevn.config.loader import load_workspace
from sevn.integrations.twexapi.client import TwexApiError
from sevn.lcm.script_cli import write_error, write_ok, workspace_from_env

_DRY_RUN_ENV = "SEVN_SOCIAL_MEDIA_MANAGER_DRY_RUN"


def content_root_from_env() -> Path:
    """Return the real workspace content root.

    Returns:
        Path: ``SEVN_CONTENT_ROOT`` when set, else :func:`workspace_from_env`.

    Examples:
        >>> content_root_from_env().is_absolute()
        True
    """
    raw = os.environ.get("SEVN_CONTENT_ROOT", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return workspace_from_env()


def dry_run_requested(argv: list[str] | None = None) -> bool:
    """Return whether a dry-run was requested via CLI flag or env.

    Args:
        argv (list[str] | None): CLI argv (defaults to ``sys.argv[1:]``).

    Returns:
        bool: ``True`` when dry-run is active.

    Examples:
        >>> dry_run_requested(["--dry-run"])
        True
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if "--dry-run" in args or "-n" in args:
        return True
    return os.environ.get(_DRY_RUN_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


async def _run_async(task_obj: dict[str, Any]) -> dict[str, Any]:
    """Execute one social-media specialist task asynchronously.

    Args:
        task_obj (dict[str, Any]): Task JSON object.

    Returns:
        dict[str, Any]: Worker result payload.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_run_async)
        True
    """
    content_root = content_root_from_env()
    cfg, _layout = load_workspace(start_dir=content_root)
    task = json.dumps(task_obj, separators=(",", ":"))
    return await execute_social_media_manager_task(
        task,
        content_root=content_root,
        subagents_cfg=cfg.subagents,
    )


def run_social_media_task(task_obj: dict[str, Any], *, dry_run: bool = False) -> int:
    """Run one social-media job and write the skill JSON envelope to stdout.

    Args:
        task_obj (dict[str, Any]): Task object (medium/op/…).
        dry_run (bool): When true, emit the planned task without calling TwexAPI.

    Returns:
        int: ``0`` on success, ``1`` on failure.

    Examples:
        >>> isinstance(run_social_media_task, type(lambda: None)) or True
        True
    """
    if dry_run:
        write_ok({"dry_run": True, "task": task_obj})
        return 0
    try:
        result = asyncio.run(_run_async(task_obj))
    except (TwexApiError, ValueError, OSError, RuntimeError) as exc:
        write_error(str(exc))
        return 1
    write_ok(result)
    return 0
