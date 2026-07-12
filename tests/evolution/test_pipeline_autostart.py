"""Tests for auto-run scheduling on issue import (`plan/dev_eval_14062026/evolution-auto-run-import-wave-plan.md` AR-1)."""

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
from sevn.evolution.issues import EvolutionIssue
from sevn.evolution.pipeline_autostart import maybe_auto_run_pipeline_after_import
from sevn.workspace.layout import WorkspaceLayout


def _layout(tmp_path: Path) -> tuple[WorkspaceLayout, WorkspaceConfig]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    return WorkspaceLayout.from_config(sevn_json, cfg), cfg


def _cfg_with_auto_run(tmp_path: Path, *, enabled: bool) -> tuple[WorkspaceLayout, WorkspaceConfig]:
    lay, cfg = _layout(tmp_path)
    cfg = cfg.model_copy(
        update={
            "my_sevn": MySevnWorkspaceConfig(
                issues=MySevnIssuesWorkspaceConfig(auto_run_on_import=enabled),
            )
        }
    )
    return lay, cfg


def _open_issue(issue_id: str = "gh-1") -> EvolutionIssue:
    return EvolutionIssue(
        id=issue_id,
        kind="bug",
        title="Test",
        body="",
        state="open",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        source="github",
    )


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(":memory:", check_same_thread=False)


def test_flag_off_no_spawn(tmp_path: Path) -> None:
    lay, cfg = _cfg_with_auto_run(tmp_path, enabled=False)
    issue = _open_issue()
    with patch("sevn.evolution.pipeline_autostart.spawn_logged") as mock_spawn:
        result = maybe_auto_run_pipeline_after_import(lay, cfg, _conn(), issue, created=True)
    assert result is False
    mock_spawn.assert_not_called()


def test_flag_on_created_true_spawns(tmp_path: Path) -> None:
    lay, cfg = _cfg_with_auto_run(tmp_path, enabled=True)
    issue = _open_issue()
    with patch("sevn.evolution.pipeline_autostart.spawn_logged") as mock_spawn:
        result = maybe_auto_run_pipeline_after_import(lay, cfg, _conn(), issue, created=True)
    assert result is True
    mock_spawn.assert_called_once()
    assert mock_spawn.call_args.kwargs.get("label") == "auto_run:gh-1"


def test_created_false_no_spawn(tmp_path: Path) -> None:
    lay, cfg = _cfg_with_auto_run(tmp_path, enabled=True)
    issue = _open_issue()
    with patch("sevn.evolution.pipeline_autostart.spawn_logged") as mock_spawn:
        result = maybe_auto_run_pipeline_after_import(lay, cfg, _conn(), issue, created=False)
    assert result is False
    mock_spawn.assert_not_called()


def test_non_open_state_no_spawn(tmp_path: Path) -> None:
    lay, cfg = _cfg_with_auto_run(tmp_path, enabled=True)
    for state in ("done", "cancelled", "implementing"):
        issue = EvolutionIssue(
            id="gh-2",
            kind="bug",
            title="T",
            body="",
            state=state,  # type: ignore[arg-type]
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
            source="github",
        )
        with patch("sevn.evolution.pipeline_autostart.spawn_logged") as mock_spawn:
            result = maybe_auto_run_pipeline_after_import(lay, cfg, _conn(), issue, created=True)
        assert result is False, f"expected no spawn for state={state}"
        mock_spawn.assert_not_called()


def test_awaiting_approval_stage_no_spawn(tmp_path: Path) -> None:
    lay, cfg = _cfg_with_auto_run(tmp_path, enabled=True)
    issue = EvolutionIssue(
        id="gh-3",
        kind="feature",
        title="T",
        body="",
        state="open",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        source="github",
        pipeline_stage="awaiting_approval",
    )
    with patch("sevn.evolution.pipeline_autostart.spawn_logged") as mock_spawn:
        result = maybe_auto_run_pipeline_after_import(lay, cfg, _conn(), issue, created=True)
    assert result is False
    mock_spawn.assert_not_called()


@pytest.mark.asyncio
async def test_pipeline_blocked_error_is_swallowed(tmp_path: Path) -> None:
    """PipelineBlockedError inside the spawned coroutine is caught, not propagated."""
    import asyncio

    from sevn.evolution.pipeline_common import PipelineBlockedError

    lay, cfg = _cfg_with_auto_run(tmp_path, enabled=True)
    issue = _open_issue()
    conn = _conn()

    spawned_coros: list[object] = []

    def capture_spawn(coro: object, *, label: str) -> None:
        spawned_coros.append(coro)

    with (
        patch("sevn.evolution.pipeline_autostart.spawn_logged", side_effect=capture_spawn),
        patch(
            "sevn.evolution.pipeline_runner.run_pipeline",
            new_callable=AsyncMock,
            side_effect=PipelineBlockedError("approval required"),
        ),
    ):
        result = maybe_auto_run_pipeline_after_import(lay, cfg, conn, issue, created=True)
        assert result is True
        assert len(spawned_coros) == 1
        coro = spawned_coros[0]
        if asyncio.iscoroutine(coro):
            await coro
