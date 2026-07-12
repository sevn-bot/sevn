"""My Sevn.bot onboarding step (`specs/22-onboarding.md` §4.1 step 3b)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from sevn.cli.repo_sync import SyncResult
from sevn.config.workspace_config import WorkspaceConfig
from sevn.evolution.repo_sync_scheduler import (
    MY_SEVN_SYNC_CRON_JOB_ID,
    reconcile_my_sevn_sync_cron_job,
    run_scheduled_repo_sync,
)
from sevn.onboarding.validate import validate_workspace_document
from sevn.onboarding.web_app import _merge_wizard_payload, create_onboarding_app
from sevn.storage.migrate import apply_migrations


def test_merge_wizard_payload_includes_my_sevn_defaults() -> None:
    """Wizard fields merge into ``my_sevn`` and ``self_improve`` subtrees."""
    doc = _merge_wizard_payload(
        {
            "fields": {
                "agent.display_name": "Nova",
                "my_sevn.repo_url": "https://github.com/sevn-bot/sevn",
                "my_sevn.sync.enabled": True,
                "self_improve.enabled": True,
                "self_improve.hub.use_github": True,
            },
        },
        profile_id=None,
    )
    assert doc["agent"]["display_name"] == "Nova"
    assert doc["my_sevn"]["repo_url"] == "https://github.com/sevn-bot/sevn"
    assert doc["my_sevn"]["sync"]["enabled"] is True
    assert doc["self_improve"]["enabled"] is True
    assert doc["self_improve"]["hub"]["use_github"] is True


def test_schema_accepts_my_sevn_subtree() -> None:
    """``infra/sevn.schema.json`` validates the full ``my_sevn`` block."""
    doc = {
        "schema_version": 1,
        "workspace_root": ".",
        "agent": {"display_name": "Nova"},
        "my_sevn": {
            "repo_url": "https://github.com/sevn-bot/sevn",
            "sync": {"enabled": True, "cron": "0 4 * * *"},
            "executors": {"bug": "local", "feature": "cursor_cloud"},
        },
        "self_improve": {
            "enabled": True,
            "hub": {"use_github": True, "provider": "github", "repo": "sevn-bot/sevn"},
        },
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    validate_workspace_document(doc)


def test_api_meta_lists_my_sevn_step() -> None:
    """Web wizard bootstrap exposes the renamed step id."""
    client = TestClient(create_onboarding_app("test-token"))
    res = client.get("/api/meta", headers={"X-Onboard-Token": "test-token"})
    assert res.status_code == 200
    steps = res.json()["steps"]
    ids = [row["id"] for row in steps]
    assert "my_sevn" in ids
    assert "agent" not in ids
    my_row = next(row for row in steps if row["id"] == "my_sevn")
    assert my_row["title"] == "My Sevn.bot"


def test_reconcile_my_sevn_sync_cron_job_registers_when_enabled() -> None:
    """Gateway reconcile inserts the daily repo-sync cron row."""
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    reconcile_my_sevn_sync_cron_job(
        conn,
        WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        ),
    )
    row = conn.execute(
        "SELECT job_id, cron_expr, payload_template FROM trigger_cron_jobs WHERE job_id = ?",
        (MY_SEVN_SYNC_CRON_JOB_ID,),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == MY_SEVN_SYNC_CRON_JOB_ID
    assert row[1] == "0 4 * * *"
    assert row[2] == MY_SEVN_SYNC_CRON_JOB_ID


def test_reconcile_my_sevn_sync_cron_job_deletes_when_disabled() -> None:
    """Disabled sync removes the cron row."""
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    ws = WorkspaceConfig.model_validate(
        {
            "schema_version": 1,
            "my_sevn": {"sync": {"enabled": False}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    reconcile_my_sevn_sync_cron_job(conn, ws)
    count = conn.execute("SELECT COUNT(*) FROM trigger_cron_jobs").fetchone()[0]
    conn.close()
    assert int(count) == 0


def test_run_scheduled_repo_sync_does_not_call_git(monkeypatch) -> None:
    """Cron handler must not invoke real ``git fetch`` (no GitHub credential prompt)."""

    def _fake_sync(**kwargs: object) -> SyncResult:
        assert kwargs.get("restart_gateway") is True
        return SyncResult(
            updated=False,
            local_rev="abc",
            remote_rev="abc",
            detail="mocked",
        )

    monkeypatch.setattr(
        "sevn.evolution.repo_sync_scheduler.sync_source_tree",
        lambda **kwargs: _fake_sync(**kwargs),
    )
    monkeypatch.setattr(
        "sevn.evolution.repo_sync_scheduler._resolve_sync_repo_root",
        lambda **_kwargs: Path("/tmp/sevn-checkout"),
    )
    assert run_scheduled_repo_sync(home=Path("/tmp")) == "mocked"
