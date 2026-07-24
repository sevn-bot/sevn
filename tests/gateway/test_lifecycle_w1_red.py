"""PR #46 session-tooling RED tests (green after W12)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from loguru import logger as loguru_logger
from starlette.testclient import TestClient


def test_issue_watch_cron_tick_dispatches_via_handlers() -> None:
    """Exercise register + ``cron_tick`` → ``_CRON_JOB_HANDLERS`` (not hasattr-only)."""
    import asyncio

    from sevn.agent.tracing.sink import NullTraceSink
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.triggers import cron as cron_mod
    from sevn.triggers import issue_watch_cron as watch_cron_mod

    watch_cron_mod.register_issue_watch_cron_handler()
    assert watch_cron_mod.ISSUE_WATCH_CRON_JOB_ID in cron_mod._CRON_JOB_HANDLERS

    called: list[Any] = []

    def _handler(*, workspace: Any) -> None:
        called.append(workspace)

    cron_mod._CRON_JOB_HANDLERS[watch_cron_mod.ISSUE_WATCH_CRON_JOB_ID] = _handler
    row = MagicMock()
    row.job_id = watch_cron_mod.ISSUE_WATCH_CRON_JOB_ID
    row.cron_expr = watch_cron_mod.ISSUE_WATCH_CRON_EXPR
    row.timezone = "UTC"
    store = MagicMock()
    store.list_due.return_value = [row]

    async def _dispatch(_req: Any) -> None:
        raise AssertionError("registered handlers must not fall through to dispatch")

    asyncio.run(
        cron_mod.cron_tick(
            cron_store=store,
            workspace=WorkspaceConfig.minimal(),
            content_root=Path("/tmp"),
            trace=NullTraceSink(),
            dispatch=_dispatch,
        )
    )
    assert called, "issue-watch cron handler must run via cron_tick/_CRON_JOB_HANDLERS"
    store.update_schedule.assert_called()


def test_shutdown_reap_failure_is_logged(
    tmp_workspace: tuple[object, object],
) -> None:
    from sevn.gateway.http_server import create_app

    ws, layout = tmp_workspace
    captured: list[str] = []
    sink_id = loguru_logger.add(lambda rec: captured.append(str(rec)), level="ERROR")
    try:
        with patch(
            "sevn.browser.process.reap_sevn_browsers_on_shutdown",
            side_effect=RuntimeError("reap failed"),
        ):
            app = create_app(workspace=ws, layout=layout)
            with TestClient(app):
                pass
    finally:
        loguru_logger.remove(sink_id)
    assert any("reap" in line.lower() for line in captured)


def test_boot_wires_operator_notify_when_owner_configured(
    tmp_workspace: tuple[object, object],
) -> None:
    import asyncio

    from sevn.gateway.http_server import create_app
    from sevn.triggers import operator_notify

    ws, layout = tmp_workspace
    with patch.object(
        operator_notify, "wire_operator_notify", wraps=operator_notify.wire_operator_notify
    ) as wire:
        app = create_app(workspace=ws, layout=layout)
        with TestClient(app):
            pass
    # Boot path must call wire_operator_notify (owner Telegram id may be empty).
    assert wire.called

    # When an owner id is configured, the sink delivers via route_outgoing.
    routed: list[Any] = []
    router = MagicMock()
    router.route_outgoing = AsyncMock(side_effect=lambda msg: routed.append(msg))

    async def _prove_sink() -> None:
        try:
            wired = operator_notify.wire_operator_notify(
                gateway_router=router,
                owner_telegram_user_id="424242",
            )
            assert wired is True
            operator_notify.deliver_operator_notify(text="issue-watch probe")
            await asyncio.sleep(0.05)
            assert routed, "operator-notify sink must reach gateway_router.route_outgoing"
            assert "issue-watch probe" in routed[0].text
        finally:
            operator_notify.reset_operator_notify_for_tests()

    asyncio.run(_prove_sink())
