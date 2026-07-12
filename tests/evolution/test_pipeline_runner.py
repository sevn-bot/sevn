"""Evolution pipeline résumé façade tests (`plan/full-loop-evolution-wave-plan.md` FL-2.6)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.evolution.issues import create_issue, save_issue
from sevn.evolution.pipeline_common import PipelineBlockedError
from sevn.evolution.pipeline_runner import _resolve_dry_runs, run_pipeline
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


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ---------------------------------------------------------------------------
# _resolve_dry_runs helper
# ---------------------------------------------------------------------------


def test_resolve_dry_runs_defaults_from_config(tmp_path: Path) -> None:
    """Unset flags pick up my_sevn.pipelines defaults (ci=True, sk=False, promo=True)."""
    _, ws = _layout(tmp_path)
    ci, sk, promo = _resolve_dry_runs(
        ws, ci_dry_run=None, spec_kit_dry_run=None, promotion_dry_run=None
    )
    assert ci is True
    assert sk is False
    assert promo is True


def test_resolve_dry_runs_explicit_overrides(tmp_path: Path) -> None:
    """Explicitly passed flags beat the config defaults."""
    _, ws = _layout(tmp_path)
    ci, sk, promo = _resolve_dry_runs(
        ws, ci_dry_run=False, spec_kit_dry_run=True, promotion_dry_run=False
    )
    assert ci is False
    assert sk is True
    assert promo is False


# ---------------------------------------------------------------------------
# run_pipeline — stage routing table
# ---------------------------------------------------------------------------


async def test_run_pipeline_issue_not_found_raises(tmp_path: Path) -> None:
    """Missing issue raises PipelineBlockedError."""
    lay, ws = _layout(tmp_path)
    with pytest.raises(PipelineBlockedError, match="issue not found"):
        await run_pipeline(_conn(), ws, lay, "missing-id")


async def test_run_pipeline_awaiting_approval_raises(tmp_path: Path) -> None:
    """Issue in awaiting_approval raises PipelineBlockedError (HITL required)."""
    lay, ws = _layout(tmp_path)
    issue = create_issue(lay, kind="bug", title="Needs approval", state="awaiting_approval")
    issue.pipeline_stage = "awaiting_approval"
    save_issue(lay, issue)

    with pytest.raises(PipelineBlockedError, match="awaiting_approval"):
        await run_pipeline(_conn(), ws, lay, issue.id)


async def test_run_pipeline_done_is_noop(tmp_path: Path) -> None:
    """Issue in done state returns unchanged without dispatching."""
    lay, ws = _layout(tmp_path)
    issue = create_issue(lay, kind="bug", title="Done", state="done")
    issue.pipeline_stage = "done"
    save_issue(lay, issue)

    result = await run_pipeline(_conn(), ws, lay, issue.id)
    assert result.state == "done"


async def test_run_pipeline_cancelled_is_noop(tmp_path: Path) -> None:
    """Issue in cancelled state returns unchanged without dispatching."""
    lay, ws = _layout(tmp_path)
    issue = create_issue(lay, kind="bug", title="Cancelled", state="cancelled")
    save_issue(lay, issue)

    result = await run_pipeline(_conn(), ws, lay, issue.id)
    assert result.state == "cancelled"


async def test_run_pipeline_open_bug_calls_run_bug_pipeline(tmp_path: Path) -> None:
    """Open bug issue dispatches to run_bug_pipeline."""
    lay, ws = _layout(tmp_path)
    issue = create_issue(lay, kind="bug", title="Open bug", state="open")
    issue.pipeline_stage = "open"
    save_issue(lay, issue)

    mock_issue = MagicMock()
    mock_issue.state = "done"
    mock_issue.pipeline_stage = "done"

    with patch(
        "sevn.evolution.pipeline_runner.run_bug_pipeline",
        new_callable=AsyncMock,
        return_value=mock_issue,
    ) as mock_bug:
        result = await run_pipeline(_conn(), ws, lay, issue.id)
        mock_bug.assert_called_once()
        assert result.state == "done"


async def test_run_pipeline_open_feature_calls_run_feature_pipeline(tmp_path: Path) -> None:
    """Open feature issue dispatches to run_feature_pipeline."""
    lay, ws = _layout(tmp_path)
    issue = create_issue(lay, kind="feature", title="Open feature", state="open")
    issue.pipeline_stage = "open"
    save_issue(lay, issue)

    mock_issue = MagicMock()
    mock_issue.state = "awaiting_approval"
    mock_issue.pipeline_stage = "awaiting_approval"

    with patch(
        "sevn.evolution.pipeline_runner.run_feature_pipeline",
        new_callable=AsyncMock,
        return_value=mock_issue,
    ) as mock_feat:
        result = await run_pipeline(_conn(), ws, lay, issue.id)
        mock_feat.assert_called_once()
        assert result.state == "awaiting_approval"


async def test_run_pipeline_implementing_with_cursor_id_polls(tmp_path: Path) -> None:
    """Implementing issue with cursor_agent_id set calls poll_cursor_cloud_for_issue."""
    lay, ws = _layout(tmp_path)
    issue = create_issue(lay, kind="bug", title="Cursor", state="implementing")
    issue.pipeline_stage = "implementing"
    issue.cursor_agent_id = "agent-abc"
    save_issue(lay, issue)

    mock_issue = MagicMock()
    mock_issue.state = "implementing"

    with patch(
        "sevn.evolution.pipeline_runner.poll_cursor_cloud_for_issue",
        return_value=mock_issue,
    ) as mock_poll:
        result = await run_pipeline(_conn(), ws, lay, issue.id)
        mock_poll.assert_called_once()
        assert result is mock_issue


async def test_run_pipeline_open_stage_dispatches_bug_pipeline(tmp_path: Path) -> None:
    """Explicit stage='plan' on open bug dispatches to run_bug_pipeline (not blocked)."""
    lay, ws = _layout(tmp_path)
    issue = create_issue(lay, kind="bug", title="Plan bug", state="open")
    issue.pipeline_stage = "open"
    save_issue(lay, issue)

    mock_issue = MagicMock()
    mock_issue.state = "awaiting_approval"

    with patch(
        "sevn.evolution.pipeline_runner.run_bug_pipeline",
        new_callable=AsyncMock,
        return_value=mock_issue,
    ) as mock_bug:
        result = await run_pipeline(_conn(), ws, lay, issue.id, stage="plan")
        mock_bug.assert_called_once()
        assert result.state == "awaiting_approval"


async def test_run_pipeline_dry_run_flags_passed_through(tmp_path: Path) -> None:
    """Explicit dry-run flags are forwarded to run_bug_pipeline."""
    lay, ws = _layout(tmp_path)
    issue = create_issue(lay, kind="bug", title="Live run", state="open")
    save_issue(lay, issue)

    mock_issue = MagicMock()
    mock_issue.state = "done"

    with patch(
        "sevn.evolution.pipeline_runner.run_bug_pipeline",
        new_callable=AsyncMock,
        return_value=mock_issue,
    ) as mock_bug:
        await run_pipeline(
            _conn(),
            ws,
            lay,
            issue.id,
            ci_dry_run=False,
            spec_kit_dry_run=False,
            promotion_dry_run=False,
        )
        _args, kwargs = mock_bug.call_args
        assert kwargs["ci_dry_run"] is False
        assert kwargs["spec_kit_dry_run"] is False
        assert kwargs["promotion_dry_run"] is False
