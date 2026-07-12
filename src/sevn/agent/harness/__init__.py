"""Harness discipline: run snapshots, boot sweep, zombie-watch queue.

Module: sevn.agent.harness
Depends: sevn.agent.harness.snapshots, sevn.agent.harness.zombie

Exports:
    ActiveRunSnapshotWrite — row-ready snapshot payload (``specs/16-harness-discipline.md`` §2.1).
    BootResumeRunRef — run handle for resume UX.
    HarnessBootSweepResult — GC + resume classification result.
    HarnessSnapshotSanitisationError — rejected ``plan_state`` / ``in_flight_tools``.
    delete_active_run_snapshot — remove row on terminal status (§3.4).
    persist_run_snapshot — upsert ``active_run_snapshots`` (§2.1).
    format_upgrade_paused_notification — single grouped copy for N paused runs (§4.2).
    get_or_create_turn_replay_job_id — stable id per session/turn (§2.3 dedupe).
    ReplayTurnNotFoundError — dashboard replay missing trace history.
    queue_dashboard_turn_replay — validate + stable replay job id (§2.3).
    pause_active_snapshots_for_upgrade — active → pending_resume before restart.
    pending_resume_group_count — ``N`` for grouped upgrade prompt (§4.2).
    redacted_inspect_summary — operator-facing inspect dict (§2.2, §8).
    sanitize_in_flight_tools — allowed-field filter for tool refs (§3.3).
    sanitize_plan_state — allowlist ``plan_state`` keys (§3.2).
    session_has_active_run_for_replay — 409 helper (§2.3).
    sweep_active_run_snapshots — boot GC + resume policy (§2.2, §4.2).
    ZombieTask — zombie-watch work unit.
    ZombieWatchQueue — bounded in-process queue (§4.4).

Examples:
    >>> from sevn.agent.harness import ActiveRunSnapshotWrite
    >>> isinstance(ActiveRunSnapshotWrite.__name__, str)
    True
"""

from __future__ import annotations

from sevn.agent.harness.snapshots import (
    ActiveRunSnapshotWrite,
    BootResumeRunRef,
    HarnessBootSweepResult,
    HarnessSnapshotSanitisationError,
    ReplayTurnNotFoundError,
    delete_active_run_snapshot,
    format_upgrade_paused_notification,
    get_or_create_turn_replay_job_id,
    pause_active_snapshots_for_upgrade,
    pending_resume_group_count,
    persist_run_snapshot,
    queue_dashboard_turn_replay,
    redacted_inspect_summary,
    sanitize_in_flight_tools,
    sanitize_plan_state,
    session_has_active_run_for_replay,
    sweep_active_run_snapshots,
)
from sevn.agent.harness.zombie import ZombieTask, ZombieWatchQueue

__all__ = [
    "ActiveRunSnapshotWrite",
    "BootResumeRunRef",
    "HarnessBootSweepResult",
    "HarnessSnapshotSanitisationError",
    "ReplayTurnNotFoundError",
    "ZombieTask",
    "ZombieWatchQueue",
    "delete_active_run_snapshot",
    "format_upgrade_paused_notification",
    "get_or_create_turn_replay_job_id",
    "pause_active_snapshots_for_upgrade",
    "pending_resume_group_count",
    "persist_run_snapshot",
    "queue_dashboard_turn_replay",
    "redacted_inspect_summary",
    "sanitize_in_flight_tools",
    "sanitize_plan_state",
    "session_has_active_run_for_replay",
    "sweep_active_run_snapshots",
]
