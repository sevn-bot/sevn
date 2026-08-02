"""W16 — cron status propagation (#135, D13/D14)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.config.workspace_config import WorkspaceConfig
from sevn.storage.migrate import apply_migrations
from sevn.triggers.cron import SqliteCronStore, add_cron_job, cron_tick
from sevn.triggers.dispatch_outcome import (
    DispatchOutcome,
    assess_agent_pass_outcome,
    cron_failure_notify_text,
)
from sevn.triggers.huggingnews_cron import (
    HUGGINGNEWS_CANONICAL_PROMPT,
    HUGGINGNEWS_CRON_JOB_ID,
    reconcile_huggingnews_cron_job,
)
from sevn.triggers.operator_notify import reset_operator_notify_for_tests, set_operator_notify
from sevn.triggers.request import DispatchRequest, ResultChannel


def _cron_row(*, job_id: str = "job-a") -> MagicMock:
    row = MagicMock()
    row.job_id = job_id
    row.cron_expr = "* * * * *"
    row.timezone = "UTC"
    row.next_fire_at_ns = 1
    row.payload_template = "ping"
    row.routing_mode = "fixed"
    row.delivery_mode = "agent_pass"
    row.permission_template_ref = "default"
    row.allow_tier_cd = False
    row.overlap_policy = "skip"
    row.result_channel_json = '{"kind":"LOG"}'
    return row


@pytest.mark.asyncio
async def test_cron_tick_agent_failure_sets_agent_failed_not_ok() -> None:
    """Dispatch ok at transport layer but agent outcome failed → not ``ok``/``completed``."""
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    add_cron_job(
        conn,
        job_id="fail-job",
        cron_expr="* * * * *",
        next_fire_at_ns=1,
        payload_template="do work",
    )
    store = SqliteCronStore(conn)
    store.list_due = MagicMock(return_value=[_cron_row(job_id="fail-job")])  # type: ignore[method-assign]
    store._conn = conn

    async def _dispatch(_req: DispatchRequest) -> DispatchOutcome:
        return DispatchOutcome(agent_ok=False, delivery_ok=False, error="no_assistant_output")

    await cron_tick(
        cron_store=store,
        workspace=WorkspaceConfig.minimal(),
        content_root=Path("."),
        trace=NullTraceSink(),
        dispatch=_dispatch,
    )

    last_status = conn.execute(
        "SELECT last_status FROM trigger_cron_jobs WHERE job_id = 'fail-job'",
    ).fetchone()[0]
    assert last_status == "agent_failed"
    assert last_status != "ok"


@pytest.mark.asyncio
async def test_cron_tick_delivery_failure_visible_and_notifies() -> None:
    """Delivery failure → ``delivery_failed`` + operator notify."""
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    add_cron_job(
        conn,
        job_id="deliver-fail",
        cron_expr="* * * * *",
        next_fire_at_ns=1,
        result_channel_json='{"kind":"TELEGRAM_TOPIC","telegram_topic_id":12345}',
    )
    store = SqliteCronStore(conn)
    store.list_due = MagicMock(return_value=[_cron_row(job_id="deliver-fail")])  # type: ignore[method-assign]
    store._conn = conn
    notified: list[str] = []
    set_operator_notify(lambda text: notified.append(text))
    try:

        async def _dispatch(_req: DispatchRequest) -> DispatchOutcome:
            return DispatchOutcome(
                agent_ok=True,
                delivery_ok=False,
                error="no_telegram_delivery",
            )

        await cron_tick(
            cron_store=store,
            workspace=WorkspaceConfig.minimal(),
            content_root=Path("."),
            trace=NullTraceSink(),
            dispatch=_dispatch,
        )
    finally:
        reset_operator_notify_for_tests()

    last_status = conn.execute(
        "SELECT last_status FROM trigger_cron_jobs WHERE job_id = 'deliver-fail'",
    ).fetchone()[0]
    assert last_status == "delivery_failed"
    assert notified
    assert "delivery_failed" in notified[0]


def test_assess_agent_pass_outcome_empty_output_is_agent_failed() -> None:
    """No assistant text after run → agent failure."""
    outcome = assess_agent_pass_outcome(
        None,
        req=DispatchRequest(
            prompt="x",
            result_channel=ResultChannel(kind="LOG"),
            correlation_id="c1",
        ),
        session_id="sess-1",
        agent_exception=None,
        assistant_texts=[],
    )
    assert outcome.cron_last_status() == "agent_failed"


def test_reconcile_huggingnews_replaces_defuddle_prompt() -> None:
    """Boot reconcile patches defuddle-based HuggingNews cron prompt (D14)."""
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    conn.execute(
        """
        INSERT INTO trigger_cron_jobs (
            job_id, enabled, cron_expr, timezone, next_fire_at_ns, jitter_s,
            routing_mode, delivery_mode, permission_template_ref, allow_tier_cd,
            overlap_policy, result_channel_json, payload_template
        ) VALUES (?, 1, '0 10 * * *', 'Europe/Amsterdam', 1, 0,
            'fixed', 'agent_pass', 'default', 0, 'skip', '{}',
            'Use defuddle parse https://huggingnews.com/')
        """,
        (HUGGINGNEWS_CRON_JOB_ID,),
    )
    conn.commit()
    reconcile_huggingnews_cron_job(conn, WorkspaceConfig.minimal())
    payload = conn.execute(
        "SELECT payload_template FROM trigger_cron_jobs WHERE job_id = ?",
        (HUGGINGNEWS_CRON_JOB_ID,),
    ).fetchone()[0]
    assert "defuddle parse" not in str(payload).lower()
    assert "get_page_content" in str(payload)
    assert payload == HUGGINGNEWS_CANONICAL_PROMPT


def test_cron_failure_notify_text_includes_status() -> None:
    body = cron_failure_notify_text(
        job_id="daily",
        correlation_id="abc",
        status="agent_failed",
        error="boom",
    )
    assert "agent_failed" in body
    assert "abc" in body
