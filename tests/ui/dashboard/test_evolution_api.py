"""Dashboard evolution API tests (`plan/bot-evolution-wave-plan.md` Wave EV-8)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from starlette.testclient import TestClient

from sevn.config.workspace_config import (
    DashboardWorkspaceConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.evolution.approvals import create_approval
from sevn.evolution.events import evolution_issue_ws_topic
from sevn.evolution.issues import create_issue, save_issue
from sevn.evolution.stats import record_last_sync
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.ui.dashboard.services.auth import DASHBOARD_CSRF_COOKIE_NAME, DASHBOARD_CSRF_HEADER
from sevn.workspace.layout import WorkspaceLayout


@contextmanager
def _client(tmp_path: Path) -> Iterator[TestClient]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        dashboard=DashboardWorkspaceConfig(
            enabled=True,
            login_password="pw",
            jwt_secret="dashboard-secret",
        ),
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, cfg)

    def factory() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        apply_migrations(conn)
        return conn

    app = create_app(workspace=cfg, layout=layout, sqlite_connection_factory=factory)
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client


def _login(client: TestClient) -> None:
    resp = client.post("/api/v1/auth/login", json={"password": "pw"})
    assert resp.status_code == 200


def _csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get(DASHBOARD_CSRF_COOKIE_NAME)
    assert token
    return {DASHBOARD_CSRF_HEADER: token}


@contextmanager
def _client_csrf_enforced(tmp_path: Path) -> Iterator[TestClient]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        dashboard=DashboardWorkspaceConfig(
            enabled=True,
            login_password="pw",
            jwt_secret="dashboard-secret",
            local_open=False,
        ),
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, cfg)

    def factory() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        apply_migrations(conn)
        return conn

    app = create_app(workspace=cfg, layout=layout, sqlite_connection_factory=factory)
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client


def test_evolution_pipelines_lists_active_runs(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    lay = WorkspaceLayout.from_config(
        sevn_json,
        WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        ),
    )
    active = create_issue(lay, kind="feature", title="Active", state="spec_kit")
    done = create_issue(lay, kind="bug", title="Done", state="done")
    _ = active, done

    with _client(tmp_path) as client:
        _login(client)
        resp = client.get("/api/v1/evolution/pipelines")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["issue_id"] == active.id
        assert items[0]["stages"]


def test_evolution_pipeline_kill_cancels_issue(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    lay = WorkspaceLayout.from_config(
        sevn_json,
        WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        ),
    )
    issue = create_issue(lay, kind="bug", title="Kill me", state="implementing")

    with _client(tmp_path) as client:
        _login(client)
        resp = client.post(
            f"/api/v1/evolution/pipelines/{issue.id}/kill",
            headers=_csrf_headers(client),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["state"] == "cancelled"


def test_evolution_approvals_approve_unblocks_pipeline(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    lay = WorkspaceLayout.from_config(
        sevn_json,
        WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        ),
    )
    issue = create_issue(lay, kind="feature", title="Needs approval", state="awaiting_approval")
    approval = create_approval(
        lay,
        kind="feature_plan",
        title="Plan review",
        body="Plan body",
        issue_id=issue.id,
    )
    issue.approval_id = approval.id
    save_issue(lay, issue)

    with _client(tmp_path) as client:
        _login(client)
        listed = client.get("/api/v1/evolution/approvals")
        assert listed.status_code == 200
        assert any(row["id"] == approval.id for row in listed.json()["items"])
        resp = client.post(
            f"/api/v1/evolution/approvals/{approval.id}/approve",
            headers=_csrf_headers(client),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"
        detail = client.get(f"/api/v1/evolution/issues/{issue.id}")
        assert detail.json()["state"] == "implementing"


def test_evolution_stats_counters(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    lay = WorkspaceLayout.from_config(
        sevn_json,
        WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        ),
    )
    _ = create_issue(lay, kind="bug", title="Open", state="open")
    closed = create_issue(lay, kind="bug", title="Closed", state="done")
    closed.pr_url = "https://github.com/org/repo/pull/1"
    save_issue(lay, closed)
    record_last_sync(lay, status="ok")

    with _client(tmp_path) as client:
        _login(client)
        resp = client.get("/api/v1/evolution/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["issues_open"] >= 1
        assert body["issues_closed"] >= 1
        assert body["prs"] >= 1
        assert body["last_sync"]["status"] == "ok"


def test_evolution_traces_returns_filtered_page(tmp_path: Path) -> None:
    from sevn.agent.tracing.traces_migrate import apply_traces_migrations
    from sevn.storage.paths import traces_sqlite_path

    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    lay = WorkspaceLayout.from_config(
        sevn_json,
        WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        ),
    )
    db_path = traces_sqlite_path(lay.content_root)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    apply_traces_migrations(conn)
    conn.execute(
        """INSERT INTO trace_events (
            span_id, parent_span_id, session_id, turn_id, tier, kind,
            ts_start_ns, ts_end_ns, status, attrs_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "s1",
            None,
            "sess",
            "t1",
            "B",
            "evolution.pipeline_start",
            100,
            200,
            "ok",
            json.dumps({"issue_id": "iss-1"}),
        ),
    )
    conn.execute(
        """INSERT INTO trace_events (
            span_id, parent_span_id, session_id, turn_id, tier, kind,
            ts_start_ns, ts_end_ns, status, attrs_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "s2",
            None,
            "sess",
            "t2",
            "B",
            "b_turn",
            50,
            60,
            "ok",
            "{}",
        ),
    )
    conn.commit()
    conn.close()

    with _client(tmp_path) as client:
        _login(client)
        resp = client.get("/api/v1/evolution/traces?limit=10")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["kind"] == "evolution.pipeline_start"
        assert items[0].get("issue_link")


def test_evolution_issue_ws_topic_naming() -> None:
    assert evolution_issue_ws_topic("abc") == "evolution.issue.abc"


# ---------------------------------------------------------------------------
# POST /pipelines/{issue_id}/run  (FL-2.5)
# ---------------------------------------------------------------------------


def test_evolution_pipeline_run_dispatches_open_issue(tmp_path: Path) -> None:
    import dataclasses
    from unittest.mock import AsyncMock, patch

    from sevn.evolution.issues import create_issue

    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    lay = WorkspaceLayout.from_config(
        sevn_json,
        WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        ),
    )
    issue = create_issue(lay, kind="bug", title="Open", state="open")

    mock_result = dataclasses.replace(issue, state="implementing", pipeline_stage="implementing")

    with (
        _client(tmp_path) as client,
        patch(
            "sevn.evolution.pipeline_runner.run_pipeline",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_run,
    ):
        _login(client)
        resp = client.post(
            f"/api/v1/evolution/pipelines/{issue.id}/run",
            json={"stage": "auto"},
            headers=_csrf_headers(client),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["state"] == "implementing"
        mock_run.assert_called_once()


def test_evolution_pipeline_run_404_missing_issue(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        resp = client.post(
            "/api/v1/evolution/pipelines/no-such-issue/run",
            json={"stage": "auto"},
            headers=_csrf_headers(client),
        )
        assert resp.status_code == 404


def test_evolution_pipeline_run_409_awaiting_approval(tmp_path: Path) -> None:
    from unittest.mock import AsyncMock, patch

    from sevn.evolution.issues import create_issue
    from sevn.evolution.pipeline_common import PipelineBlockedError

    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    lay = WorkspaceLayout.from_config(
        sevn_json,
        WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        ),
    )
    issue = create_issue(lay, kind="bug", title="Blocked", state="awaiting_approval")

    with (
        _client(tmp_path) as client,
        patch(
            "sevn.evolution.pipeline_runner.run_pipeline",
            new_callable=AsyncMock,
            side_effect=PipelineBlockedError("awaiting_approval"),
        ),
    ):
        _login(client)
        resp = client.post(
            f"/api/v1/evolution/pipelines/{issue.id}/run",
            json={"stage": "auto"},
            headers=_csrf_headers(client),
        )
        assert resp.status_code == 409


def test_evolution_pipeline_run_live_passes_false_dry_runs(tmp_path: Path) -> None:
    import dataclasses
    from unittest.mock import AsyncMock, patch

    from sevn.evolution.issues import create_issue

    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    lay = WorkspaceLayout.from_config(
        sevn_json,
        WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        ),
    )
    issue = create_issue(lay, kind="bug", title="Live", state="open")

    mock_result = dataclasses.replace(issue, state="done", pipeline_stage="done")

    with (
        _client(tmp_path) as client,
        patch(
            "sevn.evolution.pipeline_runner.run_pipeline",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_run,
    ):
        _login(client)
        resp = client.post(
            f"/api/v1/evolution/pipelines/{issue.id}/run",
            json={"stage": "auto", "live": True},
            headers=_csrf_headers(client),
        )
        assert resp.status_code == 200
        _, kwargs = mock_run.call_args
        assert kwargs["ci_dry_run"] is False
        assert kwargs["promotion_dry_run"] is False
        assert kwargs["spec_kit_dry_run"] is False


# ---------------------------------------------------------------------------
# FL-5 — executor picker forwarded through POST /run (FL-5.1 / FL-5.2)
# ---------------------------------------------------------------------------


def test_evolution_pipeline_run_with_executor_forwarded(tmp_path: Path) -> None:
    """MC executor picker value must be forwarded to run_pipeline (FL-5.1/5.2)."""
    import dataclasses
    from unittest.mock import AsyncMock, patch

    from sevn.evolution.issues import create_issue

    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    lay = WorkspaceLayout.from_config(
        sevn_json,
        WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        ),
    )
    issue = create_issue(lay, kind="bug", title="Exec", state="open")

    mock_result = dataclasses.replace(issue, state="implementing", pipeline_stage="implementing")

    with (
        _client(tmp_path) as client,
        patch(
            "sevn.evolution.pipeline_runner.run_pipeline",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_run,
    ):
        _login(client)
        resp = client.post(
            f"/api/v1/evolution/pipelines/{issue.id}/run",
            json={"stage": "auto", "executor": "chat"},
            headers=_csrf_headers(client),
        )
        assert resp.status_code == 200
        _, kwargs = mock_run.call_args
        assert kwargs["executor"] == "chat"


def test_evolution_pipeline_run_executor_none_when_omitted(tmp_path: Path) -> None:
    """When executor is omitted from the request body, it must be ``None``."""
    import dataclasses
    from unittest.mock import AsyncMock, patch

    from sevn.evolution.issues import create_issue

    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    lay = WorkspaceLayout.from_config(
        sevn_json,
        WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        ),
    )
    issue = create_issue(lay, kind="bug", title="NoExec", state="open")

    mock_result = dataclasses.replace(issue, state="implementing", pipeline_stage="implementing")

    with (
        _client(tmp_path) as client,
        patch(
            "sevn.evolution.pipeline_runner.run_pipeline",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_run,
    ):
        _login(client)
        resp = client.post(
            f"/api/v1/evolution/pipelines/{issue.id}/run",
            json={"stage": "auto"},
            headers=_csrf_headers(client),
        )
        assert resp.status_code == 200
        _, kwargs = mock_run.call_args
        assert kwargs["executor"] is None


# ---------------------------------------------------------------------------
# FL-5.3 — pr_url notify: fanout receives pr_url on transition (via pipeline_common)
# ---------------------------------------------------------------------------


def test_publish_transition_includes_pr_url() -> None:
    """publish_transition must include ``pr_url`` in the event payload when set on issue."""
    import asyncio

    from sevn.evolution.issues import EvolutionIssue
    from sevn.evolution.pipeline_common import publish_transition

    received: list[dict] = []

    class _FakeFanout:
        async def publish(self, payload: dict) -> None:  # type: ignore[override]
            received.append(dict(payload))

    issue = EvolutionIssue(
        id="i1",
        kind="bug",
        title="T",
        body="",
        state="done",
        created_at="t",
        updated_at="t",
        source="test",
        pipeline_stage="promote/done",
        pr_url="https://github.com/org/repo/pull/99",
    )

    asyncio.run(publish_transition(_FakeFanout(), issue=issue))  # type: ignore[arg-type]

    transition_events = [e for e in received if e.get("event") == "transition"]
    assert transition_events, "no transition event emitted"
    assert transition_events[0]["pr_url"] == "https://github.com/org/repo/pull/99"


def test_format_evolution_telegram_pr_url_message() -> None:
    """``_format_evolution_telegram`` must return a PR-ready message when pr_url is set."""
    from sevn.gateway.evolution.evolution_issue_events import _format_evolution_telegram

    text, _ = _format_evolution_telegram(
        {
            "issue_id": "i1",
            "event": "transition",
            "state": "done",
            "pr_url": "https://github.com/org/repo/pull/99",
        }
    )
    assert "PR ready" in text
    assert "https://github.com/org/repo/pull/99" in text


def test_format_evolution_telegram_no_pr_url_unchanged() -> None:
    """Without ``pr_url``, the standard state/stage message is returned."""
    from sevn.gateway.evolution.evolution_issue_events import _format_evolution_telegram

    text, _ = _format_evolution_telegram(
        {
            "issue_id": "i2",
            "event": "transition",
            "state": "implementing",
            "pipeline_stage": "implementing",
        }
    )
    assert "PR ready" not in text
    assert "i2" in text
    assert "implementing" in text


# ---------------------------------------------------------------------------
# SEC-01 — CSRF enforcement on evolution mutation routes (improve3 W2)
# ---------------------------------------------------------------------------


def test_evolution_create_issue_requires_csrf(tmp_path: Path) -> None:
    from unittest.mock import AsyncMock, patch

    with (
        _client_csrf_enforced(tmp_path) as client,
        patch(
            "sevn.ui.dashboard.api.evolution.maybe_mirror_issue_to_github",
            new_callable=AsyncMock,
            side_effect=lambda _layout, issue, _ws: issue,
        ),
    ):
        _login(client)
        denied = client.post(
            "/api/v1/evolution/issues",
            json={"kind": "bug", "title": "CSRF test", "body": ""},
        )
        assert denied.status_code == 403
        assert denied.json()["detail"] == "csrf_failed"

        allowed = client.post(
            "/api/v1/evolution/issues",
            json={"kind": "bug", "title": "CSRF test", "body": ""},
            headers=_csrf_headers(client),
        )
        assert allowed.status_code == 200
        assert allowed.json()["title"] == "CSRF test"


def test_evolution_pipeline_run_requires_csrf(tmp_path: Path) -> None:
    with _client_csrf_enforced(tmp_path) as client:
        _login(client)
        denied = client.post(
            "/api/v1/evolution/pipelines/no-such-issue/run",
            json={"stage": "auto"},
        )
        assert denied.status_code == 403
        assert denied.json()["detail"] == "csrf_failed"

        allowed = client.post(
            "/api/v1/evolution/pipelines/no-such-issue/run",
            json={"stage": "auto"},
            headers=_csrf_headers(client),
        )
        assert allowed.status_code == 404


def test_evolution_approval_approve_requires_csrf(tmp_path: Path) -> None:
    with _client_csrf_enforced(tmp_path) as client:
        _login(client)
        denied = client.post("/api/v1/evolution/approvals/missing-approval/approve")
        assert denied.status_code == 403
        assert denied.json()["detail"] == "csrf_failed"

        allowed = client.post(
            "/api/v1/evolution/approvals/missing-approval/approve",
            headers=_csrf_headers(client),
        )
        assert allowed.status_code == 404


def test_evolution_get_issues_unaffected_by_csrf(tmp_path: Path) -> None:
    with _client_csrf_enforced(tmp_path) as client:
        _login(client)
        resp = client.get("/api/v1/evolution/issues")
        assert resp.status_code == 200
        assert "items" in resp.json()


def test_maybe_mirror_issue_to_github_survives_connect_error(tmp_path: Path) -> None:
    import asyncio

    import httpx

    from sevn.evolution.issues import create_issue, maybe_mirror_issue_to_github
    from sevn.integrations.github_skill.hooks import GithubSkillHooks

    async def _fail(_method: str, _args: dict[str, object]) -> dict[str, object]:
        raise httpx.ConnectError("proxy unreachable")

    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text('{"schema_version": 1, "workspace_root": "."}', encoding="utf-8")
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        dashboard=DashboardWorkspaceConfig(
            enabled=True,
            login_password="pw",
            jwt_secret="dashboard-secret",
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, cfg)
    issue = create_issue(layout, kind="bug", title="mirror fail")
    hooks = GithubSkillHooks(integration_call=_fail)

    result = asyncio.run(maybe_mirror_issue_to_github(layout, issue, cfg, hooks=hooks))

    assert result.id == issue.id
    assert result.github is None
