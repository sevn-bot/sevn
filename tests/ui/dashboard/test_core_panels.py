"""Mission Control Core group panels (`specs/24-dashboard.md` Wave MC-4)."""

from __future__ import annotations

import sqlite3
import time
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
from sevn.gateway.http_server import MISSION_CONTROL_SPA_ROOT, create_app
from sevn.storage.migrate import apply_migrations
from sevn.ui.dashboard.services.auth import DASHBOARD_CSRF_COOKIE_NAME, DASHBOARD_CSRF_HEADER
from sevn.ui.dashboard.tab_registry import WIRED_SLUGS
from sevn.ui.openui.store import OpenUIRecord
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


def _login(client: TestClient) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
    assert login.status_code == 200
    token = client.cookies.get(DASHBOARD_CSRF_COOKIE_NAME)
    assert token
    return {DASHBOARD_CSRF_HEADER: token}


def test_core_wired_slugs_include_overview_canvas_sessions() -> None:
    assert {"overview", "chat", "canvas-openui", "sessions"} <= WIRED_SLUGS


def test_dashboard_canvas_empty_when_no_tokens(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        resp = client.get("/api/v1/dashboard/canvas")
        assert resp.status_code == 200
        body = resp.json()
        assert body["configured"] is True
        assert body["empty"] is True
        assert body["iframe_src"] == ""


def test_dashboard_canvas_returns_iframe_src_for_latest_token(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        store = client.app.state.openui_store
        exp_ns = time.time_ns() + 60_000_000_000
        rec = OpenUIRecord(
            record_id="rec-canvas-1",
            workspace_id=".",
            session_id="sess-1",
            message_id="msg-1",
            channel="webchat",
            sanitised_html='<form method="post"></form>',
            expires_at_ns=exp_ns,
            submit_consumed=False,
            fallback_text="fb",
            extra={"title": "Weekly report"},
        )
        store.put(rec)
        store.flush_to_sqlite()
        resp = client.get("/api/v1/dashboard/canvas")
        assert resp.status_code == 200
        body = resp.json()
        assert body["empty"] is False
        assert body["iframe_src"].startswith("/openui/")
        assert body["title"] == "Weekly report"
        assert body["channel"] == "webchat"


def test_overview_aggregate_apis(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        conn: sqlite3.Connection = client.app.state.sqlite_conn
        conn.execute(
            """INSERT INTO gateway_sessions (
                session_id, scope_key, channel, user_id, created_at, updated_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("s-active", "telegram:1", "telegram", "u1", "2026-01-01", "2026-01-02", "{}"),
        )
        conn.execute(
            """INSERT INTO active_run_snapshots (
                run_id, session_id, tier, plan_state, in_flight_tools,
                excerpt, status, created_at_ns, updated_at_ns
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("r1", "s-active", "C", "{}", "[]", "working", "active", 1, 2),
        )
        conn.commit()
        snapshots = client.get("/api/v1/runs/snapshots?limit=5")
        budget = client.get("/api/v1/budget/summary")
        proxy = client.get("/api/v1/proxy/status")
        sessions = client.get("/api/v1/sessions?limit=50")
        assert snapshots.status_code == 200
        assert budget.status_code == 200
        assert proxy.status_code == 200
        assert sessions.status_code == 200
        assert len(sessions.json()["items"]) >= 1
        assert sessions.json()["items"][0]["active_runs"] == 1


def test_mission_sessions_api_calls_deep_link_serves_spa(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        resp = client.get("/mission/sessions/sess-demo/api-calls")
        assert resp.status_code == 200
        assert "sevn.bot Mission Control" in resp.text


def test_app_js_core_panel_wiring() -> None:
    js = (MISSION_CONTROL_SPA_ROOT / "app.js").read_text(encoding="utf-8")
    assert "/api/v1/runs/snapshots" in js
    assert "/api/v1/dashboard/canvas" in js
    assert 'sandbox="allow-forms allow-same-origin"' in js
    assert "resolveActiveTab" in js
    assert "renderCanvas" in js
    assert "Session delete is disabled" in js
    assert "/mission/sessions/" in js
    assert "api-calls" in js
