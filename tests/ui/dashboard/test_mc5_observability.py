"""Mission Control MC-5 observability tabs (`specs/24-dashboard.md` §10.13)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient

from sevn.config.workspace_config import (
    ChannelsWorkspaceSectionConfig,
    DashboardWorkspaceConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    TelegramChannelConfig,
    WebChatChannelConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.storage.paths import traces_sqlite_path
from sevn.ui.dashboard.query import ensure_trace_connection
from sevn.ui.dashboard.services.auth import DASHBOARD_CSRF_COOKIE_NAME, DASHBOARD_CSRF_HEADER
from sevn.ui.dashboard.tab_registry import WIRED_SLUGS
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
        channels=ChannelsWorkspaceSectionConfig(
            telegram=TelegramChannelConfig(enabled=True),
            webchat=WebChatChannelConfig(enabled=True),
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
        state = client.app.state.mission_control_state
        state.register_channel("telegram", adapter_type="telegram")
        state.update_channel(
            "telegram",
            connected=True,
            connection_state="connected",
            message=True,
        )
        yield client


def test_mc5_wired_slugs_include_observability_tabs() -> None:
    assert {"channels", "alerts-logs", "audit-analytics"} <= WIRED_SLUGS


def test_channels_status_merges_config_runtime_and_sessions(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200
        conn: sqlite3.Connection = client.app.state.sqlite_conn
        conn.execute(
            """
            INSERT INTO gateway_sessions (
                session_id, scope_key, channel, user_id, created_at, updated_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("s-tg", "telegram:u1", "telegram", "u1", "2026-01-01", "2026-01-02", "{}"),
        )
        conn.commit()
        state = client.app.state.mission_control_state
        state.update_channel(
            "telegram",
            connected=True,
            connection_state="connected",
        )
        resp = client.get("/api/v1/channels/status")
        assert resp.status_code == 200
        body = resp.json()
        names = {row["name"]: row for row in body["channels"]}
        assert names["telegram"]["enabled"] is True
        assert names["telegram"]["connected"] is True
        assert names["telegram"]["session_count"] == 1
        assert names["webchat"]["enabled"] is True


def test_alerts_rollup_includes_trace_errors_and_logs_dir(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200
        path = traces_sqlite_path(client.app.state.layout.dot_sevn)
        traces = ensure_trace_connection(path)
        try:
            traces.execute(
                """
                INSERT INTO trace_events (
                    span_id, parent_span_id, session_id, turn_id, tier, kind,
                    ts_start_ns, ts_end_ns, status, attrs_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("err-span", None, "s1", "t1", "B", "tool.invoke", 9, 10, "error", "{}"),
            )
            traces.commit()
        finally:
            traces.close()
        resp = client.get("/api/v1/alerts/rollup?limit=10")
        assert resp.status_code == 200
        body = resp.json()
        assert body["logs_dir"].endswith("logs")
        assert len(body["trace_errors"]) >= 1
        assert body["trace_errors"][0]["status"] == "error"


def test_traces_replay_endpoint_accepted_with_trace_seed(tmp_path: Path) -> None:
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
        traces = ensure_trace_connection(path)
        try:
            traces.execute(
                """
                INSERT INTO trace_events (
                    span_id, parent_span_id, session_id, turn_id, tier, kind,
                    ts_start_ns, ts_end_ns, status, attrs_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("span-replay", None, "s1", "t1", "B", "b_turn", 1, 2, "ok", "{}"),
            )
            traces.commit()
        finally:
            traces.close()
        # Queue acceptance only — do not dispatch a live agent turn under TestClient.
        worker = getattr(client.app.state, "replay_worker", None)
        if worker is not None:
            with patch.object(worker, "schedule"):
                resp = client.post(
                    "/api/v1/sessions/s1/turns/t1/replay",
                    json={"confirmed": True},
                    headers=headers,
                )
        else:
            resp = client.post(
                "/api/v1/sessions/s1/turns/t1/replay",
                json={"confirmed": True},
                headers=headers,
            )
        assert resp.status_code == 202
        assert resp.json()["replay_job_id"]
