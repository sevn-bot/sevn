"""Gateway boot and cron reconcile hook registry (CW-2).

Module: sevn.gateway.boot_registry
Depends: sevn.config.workspace_config

Exports:
    BootContext — startup context for boot hooks.
    register_boot_hook — append an async lifespan startup callback.
    register_cron_job — append a sync cron-row reconcile callback.
    clear_boot_registry — reset registries (tests only).
    run_boot_hooks — invoke registered boot hooks in priority order.
    run_cron_reconciles — invoke registered cron reconcile hooks.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from sevn.agent.tracing.sink import TraceSink
from sevn.config.settings import ProcessSettings
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.channel_router import ChannelRouter
from sevn.workspace.layout import WorkspaceLayout

BootHook = Callable[["BootContext"], Awaitable[None]]
CronReconcileHook = Callable[[sqlite3.Connection, WorkspaceConfig], None]

_BOOT_HOOKS: list[tuple[int, str, BootHook]] = []
_CRON_JOBS: list[tuple[int, str, CronReconcileHook]] = []


@dataclass(frozen=True, slots=True)
class BootContext:
    """Context passed to boot hooks during gateway lifespan startup."""

    app: Any
    workspace: WorkspaceConfig
    layout: WorkspaceLayout
    conn: sqlite3.Connection
    trace: TraceSink
    gateway_router: ChannelRouter
    process_settings: ProcessSettings | None
    content_root: Path


def register_boot_hook(name: str, hook: BootHook, *, priority: int = 0) -> None:
    """Register a gateway lifespan startup hook.

    Args:
        name (str): Stable hook id (must be unique).
        hook (BootHook): Async callback receiving :class:`BootContext`.
        priority (int): Lower runs first.

    Examples:
        >>> async def _noop(_ctx: BootContext) -> None:
        ...     return None
        >>> register_boot_hook("test-boot", _noop)
        >>> any(entry[1] == "test-boot" for entry in _BOOT_HOOKS)
        True
    """
    if not name.strip():
        msg = "boot hook name must be non-empty"
        raise ValueError(msg)
    if any(existing_name == name for _, existing_name, _ in _BOOT_HOOKS):
        msg = f"boot hook already registered: {name}"
        raise ValueError(msg)
    _BOOT_HOOKS.append((priority, name, hook))


def register_cron_job(name: str, hook: CronReconcileHook, *, priority: int = 0) -> None:
    """Register a cron-row reconcile hook (runs at gateway boot).

    Args:
        name (str): Stable hook id (must be unique).
        hook (CronReconcileHook): Sync callback ``(conn, workspace) -> None``.
        priority (int): Lower runs first.

    Examples:
        >>> def _noop(_conn: sqlite3.Connection, _ws: WorkspaceConfig) -> None:
        ...     return None
        >>> register_cron_job("test-cron", _noop)
        >>> any(entry[1] == "test-cron" for entry in _CRON_JOBS)
        True
    """
    if not name.strip():
        msg = "cron job name must be non-empty"
        raise ValueError(msg)
    if any(existing_name == name for _, existing_name, _ in _CRON_JOBS):
        msg = f"cron job already registered: {name}"
        raise ValueError(msg)
    _CRON_JOBS.append((priority, name, hook))


def clear_boot_registry() -> None:
    """Clear boot and cron registries (test isolation only).

    Restores prior registrations after the example runs so this module's own
    doctest stays order-independent under ``pytest-randomly`` alongside sibling
    modules that register hooks at import time (e.g. ``subagents_boot``'s
    ``subagents_supervisor`` boot hook) — W3 (`plan/sub-agents-orchestration-
    wave-plan.md`) hit this exact flake once ``subagents_boot`` joined
    ``boot_registry``'s bottom import chain.

    Examples:
        >>> from sevn.gateway import boot_registry as br
        >>> saved_hooks, saved_jobs = list(br._BOOT_HOOKS), list(br._CRON_JOBS)
        >>> clear_boot_registry()
        >>> (br._BOOT_HOOKS, br._CRON_JOBS)
        ([], [])
        >>> br._BOOT_HOOKS.extend(saved_hooks)
        >>> br._CRON_JOBS.extend(saved_jobs)
    """
    _BOOT_HOOKS.clear()
    _CRON_JOBS.clear()


async def run_boot_hooks(ctx: BootContext) -> None:
    """Run registered boot hooks in priority order with exception isolation.

    Args:
        ctx (BootContext): Lifespan startup context.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(run_boot_hooks)
        True
    """
    for _priority, hook_name, hook in sorted(_BOOT_HOOKS, key=lambda row: (row[0], row[1])):
        try:
            await hook(ctx)
        except Exception:
            logger.exception("boot_hook_failed name={}", hook_name)


def run_cron_reconciles(conn: sqlite3.Connection, workspace: WorkspaceConfig) -> None:
    """Run registered cron reconcile hooks in priority order.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle.
        workspace (WorkspaceConfig): Parsed workspace config.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(run_cron_reconciles)
        False
    """
    for _priority, hook_name, hook in sorted(_CRON_JOBS, key=lambda row: (row[0], row[1])):
        try:
            hook(conn, workspace)
        except Exception:
            logger.exception("cron_reconcile_failed name={}", hook_name)


def _register_builtin_cron_jobs() -> None:
    """Register built-in gateway cron reconcile hooks.

    The doctest saves/restores ``_CRON_JOBS`` around its own call so the
    assertion never depends on whether this ran already at module import, or
    on execution order relative to other doctests in this module (see
    :func:`clear_boot_registry`'s docstring for the ``pytest-randomly`` flake
    this fixes).

    Examples:
        >>> from sevn.gateway import boot_registry as br
        >>> saved = list(br._CRON_JOBS)
        >>> br._CRON_JOBS.clear()
        >>> _register_builtin_cron_jobs()
        >>> any(name == 'dreaming' for _, name, _ in br._CRON_JOBS)
        True
        >>> br._CRON_JOBS.clear()
        >>> br._CRON_JOBS.extend(saved)
    """
    from sevn.evolution.repo_sync_scheduler import (
        reconcile_my_sevn_issues_sync_cron_job,
        reconcile_my_sevn_sync_cron_job,
    )
    from sevn.memory.dreaming.scheduler import reconcile_dreaming_cron_job
    from sevn.triggers.issue_watch_cron import (
        ensure_issue_watch_cron_job,
        register_issue_watch_cron_handler,
    )

    register_issue_watch_cron_handler()
    register_cron_job("dreaming", reconcile_dreaming_cron_job, priority=0)
    register_cron_job("my_sevn_sync", reconcile_my_sevn_sync_cron_job, priority=10)
    register_cron_job("my_sevn_issues_sync", reconcile_my_sevn_issues_sync_cron_job, priority=20)
    register_cron_job("gh_issue_watch", ensure_issue_watch_cron_job, priority=30)


_register_builtin_cron_jobs()

import sevn.gateway.channel_boot  # noqa: E402 — M1 multi-adapter boot
import sevn.gateway.hooks.trajectory_ingest_hooks  # noqa: E402 — Batch C lane #3
import sevn.gateway.replay.replay_worker_hooks  # noqa: E402 — Batch D lane #5
import sevn.gateway.runtime.telemetry_boot  # noqa: E402 — CW-2 lane #1 channel boot hooks
import sevn.gateway.subagents.subagents_boot  # noqa: E402 — W3 sub-agent supervisor boot activation
import sevn.gateway.turn.turn_bundle_hooks  # noqa: E402 — turn-bundle W1
import sevn.gateway.user.user_model_hooks  # noqa: E402, F401 — Batch D lane #6

__all__ = [
    "BootContext",
    "BootHook",
    "CronReconcileHook",
    "clear_boot_registry",
    "register_boot_hook",
    "register_cron_job",
    "run_boot_hooks",
    "run_cron_reconciles",
]
