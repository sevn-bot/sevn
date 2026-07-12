"""Unit tests for Cursor cloud client helpers."""

from __future__ import annotations

import sqlite3

from sevn.integrations.cursor_cloud.client import (
    _extract_agent_from_create,
    _pr_and_branch_from_run,
    parse_mcp_servers_json,
)
from sevn.integrations.cursor_cloud.jobs import insert_job, list_workspace_jobs
from sevn.storage.migrate import apply_migrations


def test_extract_agent_from_create() -> None:
    agent = _extract_agent_from_create({"agent": {"id": "bc-9", "status": "ACTIVE"}})
    assert agent["id"] == "bc-9"


def test_pr_and_branch_from_run() -> None:
    pr, branch, text = _pr_and_branch_from_run(
        {
            "result": "done",
            "git": {"branches": [{"prUrl": "https://github.com/o/r/pull/1", "branch": "cursor/x"}]},
        },
    )
    assert pr == "https://github.com/o/r/pull/1"
    assert branch == "cursor/x"
    assert text == "done"


def test_parse_mcp_servers_json() -> None:
    servers = parse_mcp_servers_json('[{"name": "a", "url": "https://example.com"}]')
    assert servers is not None
    assert servers[0]["name"] == "a"


def test_jobs_round_trip() -> None:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    job = insert_job(
        conn,
        cursor_agent_id="bc-local",
        session_key="web:1",
        prompt="fix tests",
        repo_url="https://github.com/o/r",
        starting_ref="main",
        status="ACTIVE",
        agent_url="https://cursor.com/agents/bc-local",
    )
    listed = list_workspace_jobs(conn, session_key="web:1", limit=5)
    assert len(listed) == 1
    assert listed[0].job_id == job.job_id
