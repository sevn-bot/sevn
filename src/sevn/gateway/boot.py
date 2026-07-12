"""Gateway boot integration for harness discipline (`specs/16-harness-discipline.md` §2.2).

Module: sevn.gateway.boot
Depends: sqlite3, sevn.agent.harness.snapshots, sevn.agent.tracing.sink, sevn.config.workspace_config,
    sevn.workspace.layout, sevn.workspace.layout_validate

Exports:
    run_harness_boot_sweep — call after ``open_sevn_sqlite`` to GC + classify resumes.
    run_workspace_layout_validation — canonical layout check on boot-resume.

Examples:
    >>> import inspect
    >>> from sevn.gateway.boot import run_harness_boot_sweep
    >>> inspect.iscoroutinefunction(run_harness_boot_sweep)
    True
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sevn.agent.harness.snapshots import HarnessBootSweepResult, sweep_active_run_snapshots
from sevn.workspace.layout_validate import (
    WorkspaceLayoutValidationResult,
    validate_workspace_layout_at_boot,
)

if TYPE_CHECKING:
    import sqlite3

    from sevn.agent.tracing.sink import TraceSink
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.workspace.layout import WorkspaceLayout


async def run_harness_boot_sweep(
    *,
    conn: sqlite3.Connection,
    trace: TraceSink,
    workspace: WorkspaceConfig | None = None,
    now_ns: int | None = None,
) -> HarnessBootSweepResult:
    """Run snapshot GC and resume classification after opening ``sevn.db``.

    Args:
        conn (sqlite3.Connection): Migrated ``sevn.db`` handle.
        trace (TraceSink): Trace sink (``harness.snapshot.*``, ``harness.boot.*``).
        workspace (WorkspaceConfig | None): Effective workspace for ``auto_resume_b``.
        now_ns (int | None): Test clock override.

    Returns:
        HarnessBootSweepResult: Deleted orphan count + UX routing lists.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(run_harness_boot_sweep)
        True
    """
    return await sweep_active_run_snapshots(
        conn=conn,
        trace=trace,
        workspace=workspace,
        now_ns=now_ns,
    )


async def run_workspace_layout_validation(
    *,
    layout: WorkspaceLayout,
    trace: TraceSink,
) -> WorkspaceLayoutValidationResult:
    """Validate canonical workspace folders and markdown files on boot-resume.

    Args:
        layout (WorkspaceLayout): Resolved workspace layout.
        trace (TraceSink): Gateway trace sink.

    Returns:
        WorkspaceLayoutValidationResult: Missing paths, if any.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(run_workspace_layout_validation)
        True
    """
    return await validate_workspace_layout_at_boot(layout=layout, trace=trace)
