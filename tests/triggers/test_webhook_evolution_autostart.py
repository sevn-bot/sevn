"""Webhook auto-run integration tests (`plan/dev_eval_14062026/evolution-auto-run-import-wave-plan.md` AR-1)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sevn.config.workspace_config import (
    MySevnIssuesWorkspaceConfig,
    MySevnWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.triggers.webhook_router import maybe_import_github_issue_event
from sevn.workspace.layout import WorkspaceLayout


def _layout(tmp_path: Path, *, auto_run: bool = False) -> tuple[WorkspaceLayout, WorkspaceConfig]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
        my_sevn=MySevnWorkspaceConfig(
            repo_url="https://github.com/owner/repo",
            issues=MySevnIssuesWorkspaceConfig(
                webhook_import=True,
                auto_run_on_import=auto_run,
            ),
        ),
    )
    return WorkspaceLayout.from_config(sevn_json, cfg), cfg


def _opened_payload(number: int = 7) -> dict[str, object]:
    return {
        "action": "opened",
        "issue": {"number": number, "title": "New bug", "labels": []},
        "repository": {"full_name": "owner/repo"},
    }


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(":memory:", check_same_thread=False)


_IMPORT_FN = "sevn.evolution.github_sync.import_github_issue_with_created"


@pytest.mark.asyncio
async def test_auto_run_not_triggered_when_flag_off(tmp_path: Path) -> None:
    lay, cfg = _layout(tmp_path, auto_run=False)
    conn = _conn()
    fake_issue = _make_fake_issue()
    with (
        patch(_IMPORT_FN, new_callable=AsyncMock, return_value=(fake_issue, True)),
        patch("sevn.evolution.pipeline_autostart.spawn_logged") as mock_spawn,
    ):
        await maybe_import_github_issue_event(
            cfg, lay, event="issues", payload=_opened_payload(), conn=conn
        )
    mock_spawn.assert_not_called()


@pytest.mark.asyncio
async def test_auto_run_triggered_when_flag_on_and_created(tmp_path: Path) -> None:
    import asyncio

    lay, cfg = _layout(tmp_path, auto_run=True)
    conn = _conn()
    fake_issue = _make_fake_issue()
    with (
        patch(_IMPORT_FN, new_callable=AsyncMock, return_value=(fake_issue, True)),
        patch("sevn.evolution.pipeline_autostart.spawn_logged") as mock_spawn,
    ):
        await maybe_import_github_issue_event(
            cfg, lay, event="issues", payload=_opened_payload(), conn=conn
        )
    mock_spawn.assert_called_once()
    assert "auto_run:gh-7" in mock_spawn.call_args.kwargs.get("label", "")
    coro = mock_spawn.call_args.args[0]
    if asyncio.iscoroutine(coro):
        coro.close()


@pytest.mark.asyncio
async def test_auto_run_not_triggered_for_labeled_action(tmp_path: Path) -> None:
    """labeled action → auto-run guard requires action=="opened"; no spawn."""
    lay, cfg = _layout(tmp_path, auto_run=True)
    conn = _conn()
    fake_issue = _make_fake_issue()
    labeled_payload: dict[str, object] = {
        "action": "labeled",
        "issue": {"number": 7, "title": "Bug", "labels": []},
        "repository": {"full_name": "owner/repo"},
    }
    with (
        patch(_IMPORT_FN, new_callable=AsyncMock, return_value=(fake_issue, False)),
        patch("sevn.evolution.pipeline_autostart.spawn_logged") as mock_spawn,
    ):
        await maybe_import_github_issue_event(
            cfg, lay, event="issues", payload=labeled_payload, conn=conn
        )
    mock_spawn.assert_not_called()


@pytest.mark.asyncio
async def test_auto_run_skipped_when_conn_is_none(tmp_path: Path) -> None:
    """Without a DB connection, auto-run is not attempted."""
    lay, cfg = _layout(tmp_path, auto_run=True)
    fake_issue = _make_fake_issue()
    with (
        patch(_IMPORT_FN, new_callable=AsyncMock, return_value=(fake_issue, True)),
        patch("sevn.evolution.pipeline_autostart.spawn_logged") as mock_spawn,
    ):
        await maybe_import_github_issue_event(
            cfg, lay, event="issues", payload=_opened_payload(), conn=None
        )
    mock_spawn.assert_not_called()


@pytest.mark.asyncio
async def test_non_issue_event_is_noop(tmp_path: Path) -> None:
    lay, cfg = _layout(tmp_path, auto_run=True)
    with patch(_IMPORT_FN) as mock_import:
        await maybe_import_github_issue_event(
            cfg, lay, event="push", payload={"action": "opened"}, conn=_conn()
        )
    mock_import.assert_not_called()


def _make_fake_issue() -> object:
    from sevn.evolution.issues import EvolutionIssue

    return EvolutionIssue(
        id="gh-7",
        kind="bug",
        title="New bug",
        body="",
        state="open",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        source="github",
        github={"number": 7, "url": ""},
    )
