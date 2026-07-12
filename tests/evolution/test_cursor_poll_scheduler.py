"""Tests for FL-4C: CursorPollScheduler + idempotent launch + done-without-PR path.

Covers:
  FL-4C.1 — dispatch_cursor_cloud_implement is idempotent when cursor_agent_id already set.
  FL-4C.3 — CursorPollScheduler.poll_once polls implementing cursor_cloud issues and fans out.
  FL-4C.4 — poll_cursor_cloud_for_issue marks done on terminal without pr_url when auto_create_pr=false.
  FL-4C.2 — cursor_poll_mode=background starts the loop; manual/inline does not.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

from sevn.config.workspace_config import (
    WorkspaceConfig,
)
from sevn.evolution.cursor_poll_scheduler import CursorPollScheduler
from sevn.evolution.issues import create_issue
from sevn.evolution.router import (
    dispatch_cursor_cloud_implement,
    poll_cursor_cloud_for_issue,
)
from sevn.integrations.cursor_cloud.jobs import CursorCloudJob, insert_job
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _workspace(
    tmp_path: Path,
    *,
    cursor_enabled: bool = True,
    auto_create_pr: bool = True,
    cursor_poll_mode: str = "background",
) -> tuple[WorkspaceConfig, WorkspaceLayout, sqlite3.Connection]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "my_sevn": {
                    "repo_url": "https://github.com/sevn-bot/sevn",
                    "executors": {
                        "bug": "local",
                        "feature": "cursor_cloud",
                        "cursor_poll_mode": cursor_poll_mode,
                    },
                },
                "skills": {
                    "cursor_cloud": {
                        "enabled": cursor_enabled,
                        "default_repo_url": "https://github.com/sevn-bot/sevn",
                        "default_ref": "main",
                        "auto_create_pr": auto_create_pr,
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
    return ws, layout, conn


def _fake_job(
    conn: sqlite3.Connection,
    cursor_agent_id: str = "bc-test1",
    status: str = "ACTIVE",
    pr_url: str | None = None,
) -> CursorCloudJob:
    from sevn.integrations.cursor_cloud.jobs import update_job

    job = insert_job(
        conn,
        cursor_agent_id=cursor_agent_id,
        session_key="",
        prompt="fix",
        repo_url="https://github.com/sevn-bot/sevn",
        starting_ref="main",
        status=status,
        agent_url=f"https://cursor.com/agents/{cursor_agent_id}",
    )
    if pr_url is not None:
        updated = update_job(conn, job.job_id, pr_url=pr_url, status=status)
        return updated if updated is not None else job
    return job


# ---------------------------------------------------------------------------
# FL-4C.1 — Idempotent launch
# ---------------------------------------------------------------------------


def test_dispatch_skips_create_when_non_terminal_job_exists(tmp_path: Path) -> None:
    """If cursor_agent_id set and job non-terminal, launch is skipped; poll-only."""
    ws, layout, conn = _workspace(tmp_path)
    issue = create_issue(layout, kind="feature", title="Idempotent", body="")
    # Pre-insert a non-terminal job
    existing = _fake_job(conn, cursor_agent_id="bc-idem", status="ACTIVE")
    # Patch the issue to look like it's already delegated
    issue.cursor_agent_id = "bc-idem"
    issue.cursor_job_id = existing.job_id
    from sevn.evolution.issues import save_issue

    save_issue(layout, issue)

    create_called = []

    def _track_create(*_args: object, **_kwargs: object) -> CursorCloudJob:
        create_called.append(1)
        return existing

    refreshed = existing.__class__(
        **{**existing.__dict__, "status": "FINISHED", "pr_url": "https://github.com/o/r/pull/1"},
    )

    def _fake_refresh(_conn: sqlite3.Connection, _job: CursorCloudJob) -> CursorCloudJob:
        return refreshed

    with (
        patch("sevn.evolution.router.create_cloud_agent", side_effect=_track_create),
        patch("sevn.evolution.router.refresh_job_status", side_effect=_fake_refresh),
        patch("sevn.evolution.router.get_job", return_value=existing),
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
    # create_cloud_agent must NOT have been called
    assert create_called == [], "launch was called despite existing non-terminal job"
    assert updated.cursor_agent_id == "bc-idem"


def test_dispatch_marks_done_when_terminal_with_pr_url(tmp_path: Path) -> None:
    """Terminal job + pr_url on existing delegation → issue is marked done immediately."""
    ws, layout, conn = _workspace(tmp_path)
    issue = create_issue(layout, kind="feature", title="Already done", body="")
    finished = _fake_job(
        conn,
        cursor_agent_id="bc-done",
        status="FINISHED",
        pr_url="https://github.com/o/r/pull/7",
    )
    issue.cursor_agent_id = "bc-done"
    issue.cursor_job_id = finished.job_id
    from sevn.evolution.issues import save_issue

    save_issue(layout, issue)

    with patch("sevn.evolution.router.get_job", return_value=finished):
        updated = dispatch_cursor_cloud_implement(
            conn,
            ws,
            layout,
            issue.id,
            poll=False,
        )

    conn.close()
    assert updated.state == "done"
    assert updated.pipeline_stage == "done"
    assert updated.pr_url == "https://github.com/o/r/pull/7"


# ---------------------------------------------------------------------------
# FL-4C.3 — Background poll scheduler
# ---------------------------------------------------------------------------


def test_poll_once_polls_implementing_issues(tmp_path: Path) -> None:
    """poll_once calls poll_cursor_cloud_for_issue for each implementing cursor_cloud issue."""
    ws, layout, conn = _workspace(tmp_path)
    issue = create_issue(layout, kind="feature", title="In flight", body="")
    job = _fake_job(conn, cursor_agent_id="bc-sched")
    # Mark issue as implementing / cursor_cloud
    issue.state = "implementing"
    issue.pipeline_stage = "implementing"
    issue.executor = "cursor_cloud"
    issue.cursor_job_id = job.job_id
    issue.cursor_agent_id = "bc-sched"
    from sevn.evolution.issues import save_issue

    save_issue(layout, issue)

    polled_ids: list[str] = []

    def _fake_poll(
        _conn: sqlite3.Connection,
        _layout: WorkspaceLayout,
        _issue: object,
        *,
        ws: WorkspaceConfig | None = None,
    ) -> object:
        polled_ids.append(getattr(_issue, "id", ""))
        # Return the same issue with state unchanged
        return _issue

    sched = CursorPollScheduler(
        sqlite_conn=conn,
        workspace_config=ws,
        layout=layout,
    )

    with patch(
        "sevn.evolution.cursor_poll_scheduler.poll_cursor_cloud_for_issue",
        side_effect=_fake_poll,
    ):
        count = asyncio.run(sched.poll_once())

    conn.close()
    assert count == 1
    assert issue.id in polled_ids


def test_poll_once_skips_non_cursor_issues(tmp_path: Path) -> None:
    """poll_once skips issues with executor!=cursor_cloud or state!=implementing."""
    ws, layout, conn = _workspace(tmp_path)
    # local issue
    local_issue = create_issue(layout, kind="bug", title="Local", body="")
    local_issue.state = "implementing"
    local_issue.executor = "local"
    from sevn.evolution.issues import save_issue

    save_issue(layout, local_issue)

    polled_ids: list[str] = []

    def _fake_poll(*_args: object, **_kwargs: object) -> object:
        polled_ids.append("called")
        return _args[2]

    sched = CursorPollScheduler(
        sqlite_conn=conn,
        workspace_config=ws,
        layout=layout,
    )

    with patch(
        "sevn.evolution.cursor_poll_scheduler.poll_cursor_cloud_for_issue",
        side_effect=_fake_poll,
    ):
        count = asyncio.run(sched.poll_once())

    conn.close()
    assert count == 0
    assert polled_ids == []


def test_poll_once_fans_out_on_transition(tmp_path: Path) -> None:
    """poll_once calls fanout.publish when an issue transitions."""
    ws, layout, conn = _workspace(tmp_path)
    issue = create_issue(layout, kind="feature", title="Fanout", body="")
    job = _fake_job(conn, cursor_agent_id="bc-fan")
    issue.state = "implementing"
    issue.executor = "cursor_cloud"
    issue.cursor_job_id = job.job_id
    issue.cursor_agent_id = "bc-fan"
    from sevn.evolution.issues import save_issue

    save_issue(layout, issue)

    published: list[dict] = []

    class _FakeFanout:
        async def publish(self, payload: dict) -> None:
            published.append(payload)

    def _fake_poll(
        _conn: sqlite3.Connection,
        _layout: WorkspaceLayout,
        _issue: object,
        *,
        ws: WorkspaceConfig | None = None,
    ) -> object:
        return _issue

    sched = CursorPollScheduler(
        sqlite_conn=conn,
        workspace_config=ws,
        layout=layout,
        fanout=_FakeFanout(),  # type: ignore[arg-type]
    )

    with patch(
        "sevn.evolution.cursor_poll_scheduler.poll_cursor_cloud_for_issue",
        side_effect=_fake_poll,
    ):
        asyncio.run(sched.poll_once())

    conn.close()
    assert len(published) == 1
    assert published[0]["issue_id"] == issue.id
    assert published[0]["event"] == "transition"


# ---------------------------------------------------------------------------
# FL-4C.4 — Done without PR when auto_create_pr=false
# ---------------------------------------------------------------------------


def test_poll_marks_done_without_pr_when_auto_create_pr_false(tmp_path: Path) -> None:
    """Terminal job with no pr_url → done when auto_create_pr=false (FL-4C.4)."""
    ws, layout, conn = _workspace(tmp_path, auto_create_pr=False)
    issue = create_issue(layout, kind="feature", title="No PR", body="")
    job = _fake_job(conn, cursor_agent_id="bc-nopr", status="FINISHED")
    issue.cursor_job_id = job.job_id
    issue.cursor_agent_id = "bc-nopr"
    from sevn.evolution.issues import save_issue

    save_issue(layout, issue)

    finished_job = job.__class__(
        **{**job.__dict__, "status": "FINISHED", "pr_url": None},
    )

    def _fake_refresh(_conn: sqlite3.Connection, _job: CursorCloudJob) -> CursorCloudJob:
        return finished_job

    with (
        patch("sevn.evolution.router.refresh_job_status", side_effect=_fake_refresh),
        patch("sevn.evolution.router.get_job", return_value=finished_job),
    ):
        updated = poll_cursor_cloud_for_issue(conn, layout, issue, ws=ws)

    conn.close()
    assert updated.state == "done"
    assert updated.pipeline_stage == "done"
    assert updated.pr_url is None


def test_poll_not_done_without_pr_when_auto_create_pr_true(tmp_path: Path) -> None:
    """Terminal job with no pr_url → NOT done when auto_create_pr=true (requires pr_url)."""
    ws, layout, conn = _workspace(tmp_path, auto_create_pr=True)
    issue = create_issue(layout, kind="feature", title="Needs PR", body="")
    job = _fake_job(conn, cursor_agent_id="bc-needpr", status="FINISHED")
    issue.cursor_job_id = job.job_id
    issue.cursor_agent_id = "bc-needpr"
    from sevn.evolution.issues import save_issue

    save_issue(layout, issue)

    finished_job = job.__class__(
        **{**job.__dict__, "status": "FINISHED", "pr_url": None},
    )

    def _fake_refresh(_conn: sqlite3.Connection, _job: CursorCloudJob) -> CursorCloudJob:
        return finished_job

    with (
        patch("sevn.evolution.router.refresh_job_status", side_effect=_fake_refresh),
        patch("sevn.evolution.router.get_job", return_value=finished_job),
    ):
        updated = poll_cursor_cloud_for_issue(conn, layout, issue, ws=ws)

    conn.close()
    # Should NOT be done — still implementing (waiting for pr_url)
    assert updated.state != "done"


# ---------------------------------------------------------------------------
# FL-4C.2 — cursor_poll_mode controls scheduler start
# ---------------------------------------------------------------------------


def test_scheduler_does_not_start_in_manual_mode(tmp_path: Path) -> None:
    """CursorPollScheduler.start() is a no-op when cursor_poll_mode=manual."""
    ws, layout, conn = _workspace(tmp_path, cursor_poll_mode="manual")
    sched = CursorPollScheduler(
        sqlite_conn=conn,
        workspace_config=ws,
        layout=layout,
    )
    asyncio.run(sched.start())
    conn.close()
    assert sched._task is None


def test_scheduler_starts_in_background_mode(tmp_path: Path) -> None:
    """CursorPollScheduler.start() creates a task in background mode."""
    ws, layout, conn = _workspace(tmp_path, cursor_poll_mode="background")
    sched = CursorPollScheduler(
        sqlite_conn=conn,
        workspace_config=ws,
        layout=layout,
    )

    async def _run() -> None:
        await sched.start()
        assert sched._task is not None
        await sched.stop()
        assert sched._task is None

    asyncio.run(_run())
    conn.close()
