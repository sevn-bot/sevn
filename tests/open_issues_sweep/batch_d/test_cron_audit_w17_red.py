"""W17.6 — cron execution audit history (#85 → W21)."""

from __future__ import annotations

import sqlite3
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.config.workspace_config import WorkspaceConfig
from sevn.storage.migrate import apply_migrations
from sevn.triggers.cron import cron_tick
from tests.open_issues_sweep.batch_d.conftest import CRON_RUNS_COLUMNS, table_columns, table_exists


def _cron_row(
    *,
    job_id: str = "job-a",
    overlap_policy: str = "skip",
) -> MagicMock:
    row = MagicMock()
    row.job_id = job_id
    row.cron_expr = "* * * * *"
    row.timezone = "UTC"
    row.payload_template = "ping"
    row.routing_mode = "default"
    row.delivery_mode = "notify_only"
    row.permission_template_ref = None
    row.allow_tier_cd = False
    row.overlap_policy = overlap_policy
    row.result_channel_json = '{"kind":"LOG"}'
    return row


def test_cron_runs_table_has_issue_named_columns() -> None:
    """Migration 28 creates ``cron_runs`` with #85 field names."""
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    assert table_exists(conn, "cron_runs")
    cols = set(table_columns(conn, "cron_runs"))
    assert cols >= CRON_RUNS_COLUMNS


@pytest.mark.asyncio
async def test_cron_tick_writes_run_row_on_start_and_completion() -> None:
    """``cron_tick`` persists claimed and completed audit rows with summaries."""
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    store = MagicMock()
    store.list_due.return_value = [_cron_row()]
    store._conn = conn

    dispatch = AsyncMock()

    await cron_tick(
        cron_store=store,
        workspace=WorkspaceConfig.minimal(),
        content_root=MagicMock(),
        trace=NullTraceSink(),
        dispatch=dispatch,
    )

    rows = conn.execute(
        "SELECT job_id, status, result_summary, error FROM cron_runs ORDER BY claimed_at",
    ).fetchall()
    assert len(rows) >= 1
    statuses = {str(r[1]) for r in rows}
    assert "ok" in statuses
    assert dispatch.await_count == 1


@pytest.mark.asyncio
async def test_stale_cron_claim_recovered_at_startup() -> None:
    """Crashed claim rows are reconciled beside ``run_cron_reconciles`` on boot."""
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    now_ns = time.time_ns()
    conn.execute(
        """
        INSERT INTO cron_runs (
            job_id, run_id, claimed_at, completed_at, status,
            transcript_path, result_summary, error
        ) VALUES ('job-stale', 'run-stale', ?, NULL, 'running', NULL, NULL, NULL)
        """,
        (now_ns - 10_000_000_000,),
    )
    conn.commit()

    from sevn.triggers.cron import recover_stale_cron_claims

    recovered = recover_stale_cron_claims(conn, now_ns=now_ns)
    assert recovered >= 1
    row = conn.execute(
        "SELECT status, error FROM cron_runs WHERE run_id = 'run-stale'",
    ).fetchone()
    assert row is not None
    assert str(row[0]) in {"failed", "stale", "recovered"}
    assert row[1] is not None


@pytest.mark.parametrize(
    ("overlap_policy", "expect_second_dispatch"),
    [
        ("skip", False),
        ("queue", True),
        ("allow", True),
    ],
)
@pytest.mark.asyncio
async def test_overlap_policy_controls_concurrent_dispatch(
    overlap_policy: str,
    expect_second_dispatch: bool,
) -> None:
    """``overlap_policy`` column must be honored — today it is only passed in meta."""
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    store = MagicMock()
    store.list_due.return_value = [_cron_row(overlap_policy=overlap_policy)]
    store._conn = conn

    gate: dict[str, Any] = {"in_flight": True}
    dispatch_calls: list[Any] = []

    async def _dispatch(req: Any) -> None:
        dispatch_calls.append(req)
        gate["in_flight"] = True

    from sevn.triggers.cron import cron_tick_with_overlap_gate

    await cron_tick_with_overlap_gate(
        cron_store=store,
        workspace=WorkspaceConfig.minimal(),
        content_root=MagicMock(),
        trace=NullTraceSink(),
        dispatch=_dispatch,
        overlap_gate=gate,
    )
    if expect_second_dispatch:
        assert dispatch_calls
    else:
        assert dispatch_calls == []


@pytest.mark.asyncio
async def test_overlap_skip_allows_second_tick_after_first_completes() -> None:
    """DB-backed overlap skip must clear in-flight rows when a run completes."""
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    store = MagicMock()
    store.list_due.return_value = [_cron_row(overlap_policy="skip")]
    store._conn = conn
    dispatch = AsyncMock()

    await cron_tick(
        cron_store=store,
        workspace=WorkspaceConfig.minimal(),
        content_root=MagicMock(),
        trace=NullTraceSink(),
        dispatch=dispatch,
    )
    assert dispatch.await_count == 1

    from sevn.triggers.cron_runs import cron_has_in_flight_run

    assert cron_has_in_flight_run(conn, "job-a") is False

    await cron_tick(
        cron_store=store,
        workspace=WorkspaceConfig.minimal(),
        content_root=MagicMock(),
        trace=NullTraceSink(),
        dispatch=dispatch,
    )
    assert dispatch.await_count == 2
