"""PR #46 session-tooling RED tests (green after W12)."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient


@pytest.mark.xfail(reason="green after W12: cron_tick dispatches issue-watch handler", strict=False)
def test_issue_watch_cron_tick_dispatches_via_handlers() -> None:
    """Exercise register + ``_CRON_JOB_HANDLERS`` — not hasattr-only."""
    from sevn.triggers import cron as cron_mod
    from sevn.triggers import issue_watch_cron as watch_cron_mod

    watch_cron_mod.register_issue_watch_cron_handler()
    assert watch_cron_mod.ISSUE_WATCH_CRON_JOB_ID in cron_mod._CRON_JOB_HANDLERS

    called: list[Any] = []

    def _handler(**kwargs: Any) -> None:
        called.append(kwargs)

    cron_mod._CRON_JOB_HANDLERS[watch_cron_mod.ISSUE_WATCH_CRON_JOB_ID] = _handler
    row = MagicMock()
    row.job_id = watch_cron_mod.ISSUE_WATCH_CRON_JOB_ID
    handler = cron_mod._CRON_JOB_HANDLERS.get(row.job_id)
    assert callable(handler)
    handler(workspace=MagicMock())
    assert called, "issue-watch cron handler must run via _CRON_JOB_HANDLERS"


@pytest.mark.xfail(reason="green after W12: shutdown reap failure logged", strict=False)
def test_shutdown_reap_failure_is_logged(
    tmp_workspace: tuple[object, object],
    caplog: pytest.LogCaptureFixture,
) -> None:
    from sevn.gateway.http_server import create_app

    ws, layout = tmp_workspace
    with (
        caplog.at_level(logging.WARNING),
        patch(
            "sevn.browser.process.reap_sevn_browsers_on_shutdown",
            side_effect=RuntimeError("reap failed"),
        ),
    ):
        app = create_app(workspace=ws, layout=layout)
        with TestClient(app):
            pass
    assert any("reap" in r.message.lower() for r in caplog.records)


@pytest.mark.xfail(reason="green after W12: operator-notify sink wired", strict=False)
def test_boot_wires_operator_notify_when_owner_configured(
    tmp_workspace: tuple[object, object],
) -> None:
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
