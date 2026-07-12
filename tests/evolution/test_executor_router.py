"""Executor routing for evolution issues (`specs/35-bot-evolution.md` EV-7)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from sevn.config.workspace_config import (
    MySevnExecutorsWorkspaceConfig,
    MySevnWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.evolution.issues import create_issue, get_issue
from sevn.evolution.router import (
    ExecutorBlockedError,
    build_cursor_cloud_prompt,
    dispatch_cursor_cloud_implement,
    resolve_executor,
    resolve_target_repo_url,
)
from sevn.integrations.cursor_cloud.jobs import CursorCloudJob
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout


def _workspace(
    tmp_path: Path, *, cursor_enabled: bool = True
) -> tuple[WorkspaceConfig, WorkspaceLayout]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "my_sevn": {
                    "repo_url": "https://github.com/sevn-bot/sevn",
                    "executors": {"bug": "local", "feature": "cursor_cloud"},
                },
                "skills": {
                    "cursor_cloud": {
                        "enabled": cursor_enabled,
                        "default_repo_url": "https://github.com/sevn-bot/sevn",
                        "default_ref": "main",
                    },
                },
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            },
        ),
        encoding="utf-8",
    )
    ws = WorkspaceConfig.model_validate_json(sevn_json.read_text(encoding="utf-8"))
    layout = WorkspaceLayout.from_config(sevn_json, ws)
    dot_sevn = layout.dot_sevn
    dot_sevn.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(dot_sevn / "sevn.db"))
    apply_migrations(conn)
    conn.close()
    return ws, layout


def test_resolve_executor_defaults() -> None:
    ws = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    assert resolve_executor(ws, "bug") == "local"
    assert resolve_executor(ws, "feature") == "cursor_cloud"


def test_resolve_executor_from_config() -> None:
    ws = WorkspaceConfig(
        schema_version=1,
        my_sevn=MySevnWorkspaceConfig(
            executors=MySevnExecutorsWorkspaceConfig(bug="cursor_cloud", feature="local"),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    assert resolve_executor(ws, "bug") == "cursor_cloud"
    assert resolve_executor(ws, "feature") == "local"


def test_resolve_target_repo_url_prefers_my_sevn(tmp_path: Path) -> None:
    ws, layout = _workspace(tmp_path)
    url = resolve_target_repo_url(ws, layout.content_root)
    assert url == "https://github.com/sevn-bot/sevn"


def test_build_cursor_cloud_prompt_includes_body(tmp_path: Path) -> None:
    ws, layout = _workspace(tmp_path)
    issue = create_issue(layout, kind="feature", title="Add widget", body="Implement widget API")
    text = build_cursor_cloud_prompt(ws, layout, issue)
    assert "Implement widget API" in text
    assert "Constitution excerpt" in text


def test_dispatch_cursor_cloud_writes_issue_fields(tmp_path: Path) -> None:
    ws, layout = _workspace(tmp_path)
    issue = create_issue(layout, kind="feature", title="Cloud feature", body="Ship it")
    conn = sqlite3.connect(str(layout.dot_sevn / "sevn.db"))
    job = CursorCloudJob(
        job_id="job-1",
        cursor_agent_id="bc-ev7",
        latest_run_id="run-1",
        session_key="",
        prompt="x",
        repo_url="https://github.com/sevn-bot/sevn",
        starting_ref="main",
        status="FINISHED",
        pr_url="https://github.com/sevn-bot/sevn/pull/99",
        branch="cursor/ev7",
        agent_url="https://cursor.com/agents/bc-ev7",
        result_text="done",
        artifact_count=0,
        error_message=None,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )

    def _fake_create(*_args: object, **_kwargs: object) -> CursorCloudJob:
        return job

    def _fake_refresh(_conn: sqlite3.Connection, existing: CursorCloudJob) -> CursorCloudJob:
        return existing

    with (
        patch(
            "sevn.evolution.router.create_cloud_agent",
            side_effect=_fake_create,
        ),
        patch(
            "sevn.evolution.router.refresh_job_status",
            side_effect=_fake_refresh,
        ),
        patch(
            "sevn.evolution.router.get_job",
            return_value=job,
        ),
    ):
        updated = dispatch_cursor_cloud_implement(
            conn,
            ws,
            layout,
            issue.id,
            poll=True,
            max_polls=1,
            poll_interval_sec=0.0,
        )
    conn.close()
    assert updated.cursor_agent_id == "bc-ev7"
    assert updated.pr_url == "https://github.com/sevn-bot/sevn/pull/99"
    assert updated.agent_url == "https://cursor.com/agents/bc-ev7"
    assert updated.executor == "cursor_cloud"
    reloaded = get_issue(layout, issue.id)
    assert reloaded is not None
    assert reloaded.pr_url == updated.pr_url


def test_dispatch_blocked_when_cursor_disabled(tmp_path: Path) -> None:
    ws, layout = _workspace(tmp_path, cursor_enabled=False)
    issue = create_issue(layout, kind="feature", title="Blocked", body="")
    conn = sqlite3.connect(str(layout.dot_sevn / "sevn.db"))
    with pytest.raises(ExecutorBlockedError, match="enabled"):
        dispatch_cursor_cloud_implement(
            conn,
            ws,
            layout,
            issue.id,
            poll=False,
        )
    conn.close()
