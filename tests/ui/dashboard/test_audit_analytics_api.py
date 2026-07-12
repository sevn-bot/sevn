"""Tests for dashboard audit trail and analytics APIs (MC-W4)."""

from __future__ import annotations

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
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.storage.paths import traces_sqlite_path
from sevn.ui.dashboard.query import ensure_trace_connection
from sevn.ui.dashboard.services.auth import DASHBOARD_CSRF_COOKIE_NAME, DASHBOARD_CSRF_HEADER
from sevn.workspace.layout import WorkspaceLayout


def _csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get(DASHBOARD_CSRF_COOKIE_NAME)
    assert token
    return {DASHBOARD_CSRF_HEADER: token}


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


def _insert_trace(
    conn: sqlite3.Connection,
    *,
    span_id: str,
    kind: str,
    ts_start_ns: int,
    attrs_json: str = "{}",
    session_id: str = "sess-1",
) -> None:
    conn.execute(
        """
        INSERT INTO trace_events (
            span_id, parent_span_id, session_id, turn_id, tier, kind,
            ts_start_ns, ts_end_ns, status, attrs_json
        ) VALUES (?, NULL, ?, 'turn-1', 'B', ?, ?, ?, 'ok', ?)
        """,
        (span_id, session_id, kind, ts_start_ns, ts_start_ns + 1000, attrs_json),
    )
    conn.commit()


def test_audit_timeline_requires_auth(tmp_path: Path) -> None:
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
    app = create_app(workspace=cfg, layout=layout)
    with TestClient(app, client=("203.0.113.1", 40000), raise_server_exceptions=True) as client:
        assert client.get("/api/v1/audit/timeline").status_code == 401


def test_audit_timeline_returns_tool_events(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        layout: WorkspaceLayout = client.app.state.layout
        conn = ensure_trace_connection(traces_sqlite_path(layout.dot_sevn))
        try:
            _insert_trace(
                conn,
                span_id="s-tool",
                kind="tool.invoke",
                ts_start_ns=9_000_000_000,
                attrs_json='{"name": "read_file"}',
            )
            _insert_trace(
                conn,
                span_id="s-mission",
                kind="mission.file.write",
                ts_start_ns=8_000_000_000,
                attrs_json='{"path": "SOUL.md"}',
            )
        finally:
            conn.close()

        resp = client.get("/api/v1/audit/timeline?limit=10")
        assert resp.status_code == 200
        body = resp.json()
        kinds = {item["kind"] for item in body["items"]}
        assert "tool.invoke" in kinds
        assert "mission.file.write" in kinds


def test_analytics_tool_frequency(tmp_path: Path) -> None:
    import time

    with _client(tmp_path) as client:
        _login(client)
        layout: WorkspaceLayout = client.app.state.layout
        conn = ensure_trace_connection(traces_sqlite_path(layout.dot_sevn))
        try:
            now = time.time_ns()
            for idx in range(3):
                _insert_trace(
                    conn,
                    span_id=f"s-{idx}",
                    kind="tool.complete",
                    ts_start_ns=now - idx * 1_000_000,
                    attrs_json='{"name": "grep"}',
                )
            _insert_trace(
                conn,
                span_id="s-other",
                kind="tool.invoke",
                ts_start_ns=now - 4_000_000,
                attrs_json='{"name": "read"}',
            )
        finally:
            conn.close()

        resp = client.get("/api/v1/analytics/tool-frequency?days=30")
        assert resp.status_code == 200
        tools = {row["name"]: row["count"] for row in resp.json()["tools"]}
        assert tools.get("grep") == 3
        assert tools.get("read") == 1


def test_analytics_daily_volume_empty(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        resp = client.get("/api/v1/analytics/daily-volume?days=7")
        assert resp.status_code == 200
        assert resp.json()["days"] == []


def test_budget_summary_includes_projections_and_alerts(tmp_path: Path) -> None:
    import asyncio

    from tests._helpers.provider_trace_emit import emit_provider_call_rows

    with _client(tmp_path) as client:
        _login(client)
        layout: WorkspaceLayout = client.app.state.layout
        path = traces_sqlite_path(layout.dot_sevn)
        asyncio.run(
            emit_provider_call_rows(
                path,
                session_id="sess-budget",
                turn_id="t-budget",
                model_id="anthropic/claude",
                regime="SUBSCRIPTION",
                tokens_in=100,
                tokens_out=50,
                subscription_window_remaining=0.08,
                subscription_window_id=None,
            ),
        )

        resp = client.get("/api/v1/budget/summary")
        assert resp.status_code == 200
        body = resp.json()
        assert "projections" in body
        assert "burn_rate" in body["projections"]
        assert body["alerts"]
        assert body["alerts"][0]["model_id"] == "anthropic/claude"


def test_analytics_approvals_filter(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        layout: WorkspaceLayout = client.app.state.layout
        conn = ensure_trace_connection(traces_sqlite_path(layout.dot_sevn))
        try:
            _insert_trace(
                conn,
                span_id="ap-1",
                kind="mission.approval.pending",
                ts_start_ns=5_000_000_000,
                attrs_json='{"tool_name": "shell"}',
            )
        finally:
            conn.close()

        resp = client.get("/api/v1/analytics/approvals?limit=5")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["kind"] == "mission.approval.pending"
