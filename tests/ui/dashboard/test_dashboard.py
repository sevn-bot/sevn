"""Tests for Mission Control dashboard scaffold (`specs/24-dashboard.md` §9)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from starlette.testclient import TestClient

from sevn.config import ProcessSettings
from sevn.config.workspace_config import (
    DashboardWorkspaceConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.storage.paths import traces_sqlite_path
from sevn.ui.dashboard.query import clamp_limit, ensure_trace_connection
from sevn.ui.dashboard.services.auth import (
    DASHBOARD_CSRF_COOKIE_NAME,
    DASHBOARD_CSRF_HEADER,
    DashboardAuthService,
)
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


def test_clamp_limit_bounds() -> None:
    assert clamp_limit(None, default=25, maximum=200) == 25
    assert clamp_limit("1000", maximum=200) == 200
    assert clamp_limit("0", default=25, maximum=200) == 25


def test_dashboard_auth_service_verifies_dashboard_audience() -> None:
    cfg = WorkspaceConfig(
        schema_version=1,
        dashboard=DashboardWorkspaceConfig(login_password="pw", jwt_secret="s"),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    svc = DashboardAuthService(workspace=cfg, process_settings=ProcessSettings())
    token, _ = svc.mint_dashboard_jwt(workspace=cfg, now=100)
    claims = svc.verify_dashboard_jwt(token, now=101)
    assert claims is not None
    assert claims.aud == "dashboard"
    assert claims.sub == "owner"


def _csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get(DASHBOARD_CSRF_COOKIE_NAME)
    assert token
    return {DASHBOARD_CSRF_HEADER: token}


def test_login_cookie_then_protected_traces_query(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200
        assert login.cookies.get("sevn_dashboard_session")
        assert login.cookies.get(DASHBOARD_CSRF_COOKIE_NAME)
        protected = client.get("/api/v1/traces/query")
        assert protected.status_code == 200, protected.text
        assert protected.json() == {"items": [], "next_cursor": None, "has_more": False}


def test_dashboard_replay_returns_409_when_run_active(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200
        conn: sqlite3.Connection = client.app.state.sqlite_conn
        conn.execute(
            """INSERT INTO active_run_snapshots (
                run_id, session_id, tier, plan_state, in_flight_tools,
                excerpt, status, created_at_ns, updated_at_ns
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("r1", "s1", "C", "{}", "[]", "active", "active", 1, 2),
        )
        conn.commit()
        resp = client.post(
            "/api/v1/sessions/s1/turns/t1/replay",
            json={"confirmed": True},
            headers=_csrf_headers(client),
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "active_run_conflict"


def test_dashboard_replay_idempotency_returns_same_job(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200
        headers = _csrf_headers(client)
        db: sqlite3.Connection = client.app.state.sqlite_conn
        db.execute(
            """
            INSERT INTO gateway_sessions (
                session_id, scope_key, channel, user_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("s1", "webchat:s1", "webchat", "owner", "2026-01-01", "2026-01-01"),
        )
        db.execute(
            """
            INSERT INTO gateway_messages (
                session_id, role, kind, content, visible_to_llm, status,
                extras_json, created_at, turn_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("s1", "user", "message", "hello replay", 1, "sent", "{}", "2026-01-01", "t1"),
        )
        db.commit()
        path = traces_sqlite_path(client.app.state.layout.dot_sevn)
        conn = ensure_trace_connection(path)
        try:
            with conn:
                conn.execute(
                    """INSERT INTO trace_events (
                        span_id, parent_span_id, session_id, turn_id, tier, kind,
                        ts_start_ns, ts_end_ns, status, attrs_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    ("span-idem", None, "s1", "t1", "B", "b_turn", 1, 2, "ok", "{}"),
                )
        finally:
            conn.close()
        first = client.post(
            "/api/v1/sessions/s1/turns/t1/replay",
            json={"confirmed": True},
            headers=headers,
        )
        second = client.post(
            "/api/v1/sessions/s1/turns/t1/replay",
            json={"confirmed": True},
            headers=headers,
        )
        assert first.status_code == 202
        assert second.status_code == 202
        assert first.json()["replay_job_id"] == second.json()["replay_job_id"]


def test_dashboard_api_calls_csv_headers(tmp_path: Path) -> None:
    import asyncio

    from tests._helpers.provider_trace_emit import emit_provider_call_rows

    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200
        path = traces_sqlite_path(client.app.state.layout.dot_sevn)
        asyncio.run(
            emit_provider_call_rows(
                path,
                session_id="s1",
                turn_id="t1",
                model_id="anthropic/claude-sonnet-4-6",
                regime="PER_TOKEN",
                tokens_in=1,
                tokens_out=1,
                subscription_window_remaining=None,
                subscription_window_id=None,
            ),
        )
        resp = client.get("/api/v1/sessions/s1/api-calls/export.csv")
        assert resp.status_code == 200
        assert resp.text.splitlines()[0] == (
            "ts_start_ns,span_id,parent_span_id,session_id,turn_id,tier,kind,status"
        )


def test_dashboard_trace_redacts_llmignore_paths(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200
        path = traces_sqlite_path(client.app.state.layout.dot_sevn)
        conn = ensure_trace_connection(path)
        try:
            conn.execute(
                """INSERT INTO trace_events (
                    span_id, parent_span_id, session_id, turn_id, tier, kind,
                    ts_start_ns, ts_end_ns, status, attrs_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "span2",
                    None,
                    "s1",
                    "t1",
                    "B",
                    "tool.call",
                    3,
                    4,
                    "ok",
                    json.dumps({"path": "/workspace/.llmignore/blocked/secret.txt"}),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        resp = client.get("/api/v1/traces/query?session_id=s1")
        assert resp.status_code == 200
        body = json.dumps(resp.json())
        assert ".llmignore" not in body
        assert "[REDACTED_PATH]" in body


def test_protected_route_rejects_missing_auth(tmp_path: Path) -> None:
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
        resp = client.get("/api/v1/traces/query")
        assert resp.status_code == 401


def test_dashboard_ws_subscribe_receives_published_event(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw"})
        token = login.json()["access_token"]
        with client.websocket_connect("/ws/dashboard") as ws:
            ws.send_text(json.dumps({"type": "auth", "token": token}))
            ready = json.loads(ws.receive_text())
            assert ready["type"] == "ready"
            ws.send_text(json.dumps({"type": "subscribe", "topics": ["proxy.health"]}))
            subscribed = json.loads(ws.receive_text())
            assert subscribed["type"] == "subscribed"
            client.portal.call(
                client.app.state.dashboard_hub.publish,
                "proxy.health",
                {"ok": True},
            )
            event = json.loads(ws.receive_text())
            assert event["topic"] == "proxy.health"
            assert event["payload"] == {"ok": True}
