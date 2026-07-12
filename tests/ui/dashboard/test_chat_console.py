"""Tests for Mission Control in-dashboard chat console API (MC W6)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from starlette.testclient import TestClient

from sevn.config.workspace_config import (
    ChannelsWorkspaceSectionConfig,
    DashboardWorkspaceConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WebChatChannelConfig,
    WorkspaceConfig,
)
from sevn.gateway.auth import mint_webchat_jwt, verify_webchat_jwt
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.ui.dashboard.services.auth import DASHBOARD_CSRF_COOKIE_NAME, DASHBOARD_CSRF_HEADER
from sevn.workspace.layout import WorkspaceLayout

_WEBCHAT_SECRET = "mc-w6-webchat-secret"


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
    channels = ChannelsWorkspaceSectionConfig(
        webchat=WebChatChannelConfig(jwt_secret=_WEBCHAT_SECRET, public=False),
    )
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        channels=channels,
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


def test_chat_token_requires_auth(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    channels = ChannelsWorkspaceSectionConfig(
        webchat=WebChatChannelConfig(jwt_secret=_WEBCHAT_SECRET, public=False),
    )
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        channels=channels,
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
    app = create_app(workspace=cfg, layout=layout)
    with TestClient(
        app,
        client=("203.0.113.1", 40000),
        raise_server_exceptions=True,
    ) as client:
        resp = client.post("/api/v1/chat/token", json={})
        assert resp.status_code == 401


def test_chat_token_rejects_client_sub(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        resp = client.post(
            "/api/v1/chat/token",
            json={"sub": "evil"},
            headers=_csrf_headers(client),
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "client_sub_not_allowed"


def test_chat_token_mints_owner_sub(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        resp = client.post(
            "/api/v1/chat/token",
            json={},
            headers=_csrf_headers(client),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["token"], str)
        assert body["token"]
        assert body["expires_in"] > 0
        assert isinstance(body["expires_at"], int)
        assert isinstance(body["session_id_hint"], str)
        assert body["session_id_hint"]
        claims = verify_webchat_jwt(secret=_WEBCHAT_SECRET, token=body["token"])
        assert claims is not None
        assert claims.sub == "owner"


def test_chat_token_requires_csrf(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        resp = client.post("/api/v1/chat/token", json={})
        assert resp.status_code == 403


def test_chat_ws_owner_round_trip(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        issued = client.post(
            "/api/v1/chat/token",
            json={},
            headers=_csrf_headers(client),
        )
        assert issued.status_code == 200
        token = issued.json()["token"]
        with client.websocket_connect("/ws/webchat") as ws:
            ws.send_text(json.dumps({"type": "auth", "token": token}))
            ready = json.loads(ws.receive_text())
            assert ready["type"] == "ready"
            assert ready["user_id"] == "owner"
            session_id = ready["session_id"]
            ws.send_text(
                json.dumps({"type": "message", "text": "hello mc", "session_id": session_id}),
            )
        conn = client.app.state.sqlite_conn
        rows = conn.execute(
            """
            SELECT content FROM gateway_messages
            WHERE session_id = ? AND role = 'user'
            ORDER BY id DESC LIMIT 1
            """,
            (session_id,),
        ).fetchall()
        assert rows
        assert "hello mc" in str(rows[0][0])


def test_chat_fork_rotates_session(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        first = client.post(
            "/api/v1/chat/token",
            json={},
            headers=_csrf_headers(client),
        )
        assert first.status_code == 200
        prior = first.json()["session_id_hint"]
        fork = client.post("/api/v1/chat/fork", json={}, headers=_csrf_headers(client))
        assert fork.status_code == 200
        new_id = fork.json()["session_id"]
        assert new_id
        assert new_id != prior


def test_ws_cancel_frame_returns_cancelled(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        token, _ = mint_webchat_jwt(secret=_WEBCHAT_SECRET, sub="owner", ttl_seconds=60)
        with client.websocket_connect("/ws/webchat") as ws:
            ws.send_text(json.dumps({"type": "auth", "token": token}))
            ready = json.loads(ws.receive_text())
            session_id = ready["session_id"]
            ws.send_text(json.dumps({"type": "cancel", "session_id": session_id}))
            cancelled = json.loads(ws.receive_text())
            assert cancelled["type"] == "cancelled"
            assert cancelled["session_id"] == session_id
