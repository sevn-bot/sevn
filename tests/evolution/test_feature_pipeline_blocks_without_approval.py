"""Feature pipeline HITL gate tests (`specs/35-bot-evolution.md` EV-5)."""

from __future__ import annotations

import sqlite3

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.evolution.approvals import resolve_approval
from sevn.evolution.feature_pipeline import (
    FeaturePipelineBlockedError,
    record_pipeline_approval,
    run_feature_pipeline,
)
from sevn.evolution.issues import create_issue, get_issue
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout


def _conn(tmp_path) -> sqlite3.Connection:
    db = tmp_path / "sevn.db"
    conn = sqlite3.connect(str(db))
    apply_migrations(conn)
    return conn


@pytest.mark.asyncio
async def test_feature_pipeline_blocks_without_approval(tmp_path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", '
        '"gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}, '
        '"my_sevn": {"features": {"require_approval": true}}}',
        encoding="utf-8",
    )
    ws = WorkspaceConfig.model_validate_json(sevn_json.read_text(encoding="utf-8"))
    lay = WorkspaceLayout.from_config(sevn_json, ws)
    issue = create_issue(lay, kind="feature", title="Widget", body="Add widget API")
    conn = _conn(tmp_path)

    with pytest.raises(FeaturePipelineBlockedError, match="approval required"):
        await run_feature_pipeline(
            conn,
            ws,
            lay,
            issue.id,
            ci_dry_run=True,
        )

    loaded = get_issue(lay, issue.id)
    assert loaded is not None
    assert loaded.state == "awaiting_approval"
    assert loaded.pipeline_stage == "awaiting_approval"
    assert loaded.approval_id


@pytest.mark.asyncio
async def test_record_pipeline_approval_unblocks_after_mc_approve(tmp_path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", '
        '"gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}, '
        '"my_sevn": {"features": {"require_approval": true}}}',
        encoding="utf-8",
    )
    ws = WorkspaceConfig.model_validate_json(sevn_json.read_text(encoding="utf-8"))
    lay = WorkspaceLayout.from_config(sevn_json, ws)
    issue = create_issue(lay, kind="feature", title="Gate", body="Body")
    conn = _conn(tmp_path)

    with pytest.raises(FeaturePipelineBlockedError):
        await run_feature_pipeline(conn, ws, lay, issue.id, ci_dry_run=True)

    loaded = get_issue(lay, issue.id)
    assert loaded is not None
    approval_id = loaded.approval_id
    assert approval_id
    _approval, _ = resolve_approval(lay, approval_id, "approve")

    unblocked = await record_pipeline_approval(lay, issue.id, approval_id)
    assert unblocked.state == "implementing"
    assert unblocked.approval_id == approval_id
