"""RED suite for ``my_sevn`` repo-sync cron divergence handling (D9; green after W7)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sevn.cli.repo_sync import RepoSyncError

if TYPE_CHECKING:
    from loguru import Record


def _capture_loguru(*, level: str) -> tuple[list[str], int]:
    from loguru import logger as loguru_logger

    captured: list[str] = []

    def _sink(message: Record) -> None:
        captured.append(str(message))

    sink_id = loguru_logger.add(_sink, level=level)
    return captured, sink_id


@pytest.mark.xfail(reason="green after W7: cron divergence self-recovers", strict=False)
def test_diverged_my_sevn_sync_self_recovers_with_latest() -> None:
    """D9: when cron owns the checkout, divergence auto-recovers instead of daily failure."""
    from sevn.evolution.repo_sync_scheduler import run_scheduled_repo_sync_with_recovery

    detail = run_scheduled_repo_sync_with_recovery(home=None, dry_run=True)
    assert "diverged" not in detail.lower()
    assert "failed" not in detail.lower()


@pytest.mark.xfail(reason="green after W7: one actionable cron notice", strict=False)
def test_diverged_my_sevn_sync_surfaces_single_actionable_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D9: non-owned divergence emits one actionable notice — not a silent recurring WARNING."""
    from loguru import logger as loguru_logger

    from sevn.evolution.repo_sync_scheduler import run_scheduled_repo_sync_with_recovery

    warnings, sink_id = _capture_loguru(level="WARNING")

    def _raise_diverged(*, home: object = None, dry_run: bool = False) -> str:
        _ = home, dry_run
        msg = (
            "local history diverged from origin/test-pre; pass --latest to reset to the remote tip"
        )
        raise RepoSyncError(msg)

    monkeypatch.setattr(
        "sevn.evolution.repo_sync_scheduler.run_scheduled_repo_sync",
        _raise_diverged,
    )
    try:
        run_scheduled_repo_sync_with_recovery(home=None, dry_run=True)
    except RepoSyncError:
        pass
    finally:
        loguru_logger.remove(sink_id)

    actionable = [line for line in warnings if "my_sevn" in line.lower()]
    assert len(actionable) == 1
    assert any("action" in line.lower() or "--latest" in line for line in actionable)


@pytest.mark.xfail(reason="green after W7: no recurring cron WARNING spam", strict=False)
def test_repo_sync_cron_failure_is_not_logged_every_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D9: guaranteed daily ``--ff-only`` WARNING must stop after W7."""
    from loguru import logger as loguru_logger

    from sevn.gateway.http_server import handle_my_sevn_sync_cron_failure

    warnings, sink_id = _capture_loguru(level="WARNING")
    exc = RepoSyncError(
        "local history diverged from origin/test-pre; pass --latest to reset to the remote tip",
    )
    try:
        for _ in range(3):
            handle_my_sevn_sync_cron_failure(exc)
    finally:
        loguru_logger.remove(sink_id)
    assert len([line for line in warnings if "repo sync cron failed" in line.lower()]) <= 1
