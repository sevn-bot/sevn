"""Integration tests for the Web UI WebSocket gateway (`specs/19-channel-webui.md`)."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from sevn.config.workspace_config import (
    ChannelsWorkspaceSectionConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WebChatChannelConfig,
    WorkspaceConfig,
)
from sevn.gateway.auth import mint_webchat_jwt, verify_webchat_jwt
from sevn.gateway.http_server import WEBAPP_TELEGRAM_INITDATA_MAX_AGE_SECONDS, create_app
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout
from tests.channels.test_webchat import _build_init_data

_JWT_SECRET = "test-secret"
# Matches the autouse ``SEVN_GATEWAY_TOKEN`` bearer from ``tests/conftest.py`` that the
# app resolves at boot; gateway.token is mandatory, so operator-scoped routes now require it.
_BEARER = "a" * 64


def _make_client(
    tmp_path: Path,
    *,
    channels: ChannelsWorkspaceSectionConfig | None = None,
) -> TestClient:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    ch = channels or ChannelsWorkspaceSectionConfig(
        webchat=WebChatChannelConfig(jwt_secret=_JWT_SECRET, public=False),
    )
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        channels=ch,
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
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with _make_client(tmp_path) as client_local:
        yield client_local


def test_api_webchat_token_issues_jwt(client: TestClient) -> None:
    resp = client.post(
        "/api/webchat/token",
        json={"sub": "owner"},
        headers={"Authorization": f"Bearer {_BEARER}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "Bearer"
    assert isinstance(body["access_token"], str)
    assert body["access_token"]
    assert isinstance(body["expires_in"], int)
    assert body["expires_in"] > 0


def test_api_webchat_token_operator_no_sub_defaults_owner(client: TestClient) -> None:
    resp = client.post(
        "/api/webchat/token",
        json={},
        headers={"Authorization": f"Bearer {_BEARER}"},
    )
    assert resp.status_code == 200
    claims = verify_webchat_jwt(secret=_JWT_SECRET, token=resp.json()["access_token"])
    assert claims is not None
    assert claims.sub == "owner"


def test_api_webchat_token_503_when_no_secret(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
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
    with TestClient(app) as client_local:
        resp = client_local.post(
            "/api/webchat/token",
            json={"sub": "owner"},
            headers={"Authorization": f"Bearer {_BEARER}"},
        )
        assert resp.status_code == 503


def test_login_get_and_post_with_gateway_token(client: TestClient) -> None:
    # gateway.token is mandatory now, so /login validates the submitted bearer against the
    # configured one (resolved from the autouse SEVN_GATEWAY_TOKEN at boot).
    page = client.get("/login")
    assert page.status_code == 200
    assert "sevn.bot login" in page.text
    ok = client.post("/login", json={"token": _BEARER})
    assert ok.status_code == 200
    assert ok.json()["ok"] is True


def test_auth_refresh_round_trip(client: TestClient) -> None:
    issued = client.post(
        "/api/webchat/token",
        json={"sub": "owner"},
        headers={"Authorization": f"Bearer {_BEARER}"},
    )
    assert issued.status_code == 200
    token = issued.json()["access_token"]
    refreshed = client.post("/auth/refresh", headers={"Authorization": f"Bearer {token}"})
    assert refreshed.status_code == 200
    body = refreshed.json()
    assert isinstance(body["access_token"], str)
    assert body["access_token"]
    assert body["expires_in"] > 0


def test_webapp_index_served(client: TestClient) -> None:
    resp = client.get("/webapp/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "sevn.bot" in resp.text


def test_webapp_path_traversal_404(client: TestClient) -> None:
    resp = client.get("/webapp/../pyproject.toml")
    assert resp.status_code == 404


def test_ws_rejects_bad_auth_frame_with_4401(client: TestClient) -> None:
    from starlette.websockets import WebSocketDisconnect

    with client.websocket_connect("/ws/webchat") as ws:
        ws.send_text("not json")
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 4401


def test_ws_happy_path_auth_ready_and_session_persisted(client: TestClient) -> None:
    token, _ = mint_webchat_jwt(secret=_JWT_SECRET, sub="owner", ttl_seconds=60)
    with client.websocket_connect("/ws/webchat") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token}))
        ready = json.loads(ws.receive_text())
        assert ready["type"] == "ready"
        assert ready["user_id"] == "owner"
        session_id = ready["session_id"]
        assert session_id

    conn = client.app.state.sqlite_conn
    rows = conn.execute(
        "SELECT channel, user_id FROM gateway_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchall()
    assert rows == [("webchat", "owner")]


def test_ws_ping_pong_round_trip(client: TestClient) -> None:
    token, _ = mint_webchat_jwt(secret=_JWT_SECRET, sub="owner", ttl_seconds=60)
    with client.websocket_connect("/ws/webchat") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token}))
        json.loads(ws.receive_text())
        ws.send_text(json.dumps({"type": "ping", "nonce": 42}))
        pong = json.loads(ws.receive_text())
        assert pong == {"type": "pong", "nonce": 42}


def test_ws_unknown_frame_returns_error(client: TestClient) -> None:
    token, _ = mint_webchat_jwt(secret=_JWT_SECRET, sub="owner", ttl_seconds=60)
    with client.websocket_connect("/ws/webchat") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token}))
        ready = json.loads(ws.receive_text())
        ws.send_text(json.dumps({"type": "nonsense", "session_id": ready["session_id"]}))
        err = json.loads(ws.receive_text())
        assert err["type"] == "error"
        assert err["code"] == "unknown_frame"


def test_ws_session_forbidden_when_id_mismatches(client: TestClient) -> None:
    token, _ = mint_webchat_jwt(secret=_JWT_SECRET, sub="owner", ttl_seconds=60)
    with client.websocket_connect("/ws/webchat") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token}))
        json.loads(ws.receive_text())
        ws.send_text(
            json.dumps(
                {"type": "message", "text": "hello", "session_id": "forged"},
            ),
        )
        err = json.loads(ws.receive_text())
        assert err["type"] == "error"
        assert err["code"] == "session_forbidden"


def test_ws_client_meta_persists_browser_timezone(client: TestClient) -> None:
    """SPA's first ``client_meta`` frame writes the IANA tz into the profile.

    Reference: ``PROBLEMS.md`` §4 / Step §4. The SPA sends its
    ``Intl.DateTimeFormat().resolvedOptions().timeZone`` on connect; the
    server persists it when the row is still on the UTC default.
    """
    from sevn.gateway.user_profile import get_user_profile

    token, _ = mint_webchat_jwt(secret=_JWT_SECRET, sub="owner", ttl_seconds=60)
    with client.websocket_connect("/ws/webchat") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token}))
        json.loads(ws.receive_text())  # discard the ``ready`` frame
        ws.send_text(
            json.dumps(
                {"type": "client_meta", "timezone": "Europe/Paris"},
            ),
        )
        # Round-trip a ping → pong so we know the server's receive loop has
        # processed the prior frame (TestClient closes the WS on ``with``
        # exit which can race the server's read of the last frame).
        ws.send_text(json.dumps({"type": "ping", "nonce": "tz"}))
        assert json.loads(ws.receive_text())["type"] == "pong"
    conn = client.app.state.sqlite_conn
    profile = get_user_profile(conn, channel="webchat", user_id="owner")
    assert profile.timezone == "Europe/Paris"


def test_ws_client_meta_rejects_bad_timezone_silently(client: TestClient) -> None:
    """Unknown IANA name from the SPA never crashes the WS handler."""
    from sevn.gateway.user_profile import get_user_profile

    token, _ = mint_webchat_jwt(secret=_JWT_SECRET, sub="owner", ttl_seconds=60)
    with client.websocket_connect("/ws/webchat") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token}))
        json.loads(ws.receive_text())
        ws.send_text(
            json.dumps(
                {"type": "client_meta", "timezone": "Mars/Olympus"},
            ),
        )
        ws.send_text(json.dumps({"type": "ping", "nonce": "tz-bad"}))
        assert json.loads(ws.receive_text())["type"] == "pong"
    conn = client.app.state.sqlite_conn
    profile = get_user_profile(conn, channel="webchat", user_id="owner")
    # Bad tz was rejected; profile stayed on UTC default (no row written).
    assert profile.timezone == "UTC"


def test_ws_message_persists_through_router(client: TestClient) -> None:
    token, _ = mint_webchat_jwt(secret=_JWT_SECRET, sub="owner", ttl_seconds=60)
    with client.websocket_connect("/ws/webchat") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token}))
        ready = json.loads(ws.receive_text())
        session_id = ready["session_id"]
        ws.send_text(
            json.dumps(
                {"type": "message", "text": "hello world", "session_id": session_id},
            ),
        )

    conn = client.app.state.sqlite_conn
    rows = conn.execute(
        """
        SELECT role, kind, content FROM gateway_messages
        WHERE session_id = ?
        ORDER BY id ASC
        """,
        (session_id,),
    ).fetchall()
    contents = [r[2] for r in rows]
    assert "hello world" in contents


def test_webapp_telegram_rejects_bad_signature(tmp_path: Path) -> None:
    channels = ChannelsWorkspaceSectionConfig(
        webchat=WebChatChannelConfig(jwt_secret=_JWT_SECRET, public=False),
    )
    with _make_client(tmp_path, channels=channels) as client_local:
        resp = client_local.post(
            "/webapp/telegram",
            data={"init_data": "auth_date=1&hash=00"},
        )
        assert resp.status_code == 403


def _stub_webapp_bot_token(
    monkeypatch: pytest.MonkeyPatch, bot_token: str = "999:test-bot-token"
) -> str:
    async def _stub_resolve(workspace: object, *, content_root: object) -> str | None:
        _ = workspace, content_root
        return bot_token

    monkeypatch.setattr(
        "sevn.gateway.http_server._resolve_webapp_telegram_bot_token",
        _stub_resolve,
    )
    return bot_token


def test_webapp_telegram_valid_initdata_returns_jwt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot_token = _stub_webapp_bot_token(monkeypatch)
    now = int(time.time())
    fields = {
        "auth_date": str(now),
        "user": '{"id":42,"first_name":"Alex"}',
        "query_id": "abcd",
    }
    init_data = _build_init_data(bot_token=bot_token, fields=fields)

    with _make_client(tmp_path) as client_local:
        resp = client_local.post(
            "/webapp/telegram",
            data={"init_data": init_data},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["token_type"] == "Bearer"
        assert isinstance(body["access_token"], str)
        assert body["access_token"]


def test_webapp_telegram_stale_initdata_returns_403(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot_token = _stub_webapp_bot_token(monkeypatch)
    now = int(time.time())
    stale_auth_date = str(now - WEBAPP_TELEGRAM_INITDATA_MAX_AGE_SECONDS - 60)
    fields = {
        "auth_date": stale_auth_date,
        "user": '{"id":42,"first_name":"Alex"}',
        "query_id": "abcd",
    }
    init_data = _build_init_data(bot_token=bot_token, fields=fields)

    with _make_client(tmp_path) as client_local:
        resp = client_local.post(
            "/webapp/telegram",
            data={"init_data": init_data},
        )
        assert resp.status_code == 403


def test_webapp_telegram_fresh_initdata_mints_jwt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot_token = _stub_webapp_bot_token(monkeypatch)
    now = int(time.time())
    fields = {
        "auth_date": str(now),
        "user": '{"id":99,"first_name":"Fresh"}',
        "query_id": "fresh",
    }
    init_data = _build_init_data(bot_token=bot_token, fields=fields)

    with _make_client(tmp_path) as client_local:
        resp = client_local.post(
            "/webapp/telegram",
            data={"init_data": init_data},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["token_type"] == "Bearer"
        assert isinstance(body["access_token"], str)
        assert body["access_token"]
        claims = verify_webchat_jwt(secret=_JWT_SECRET, token=body["access_token"])
        assert claims is not None
        assert claims.sub == "tg:99"
