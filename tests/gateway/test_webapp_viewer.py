"""Mini App rich viewer routes (`telegram-rich-inline-miniapps-wave-plan.md` Wave M1)."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlencode

import pytest
from starlette.testclient import TestClient

from sevn.agent.tracing.sink import NullTraceSink
from sevn.config.workspace_config import (
    ChannelsWorkspaceSectionConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    TelegramChannelConfig,
    TelegramWebappConfig,
    WebChatChannelConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.gateway.webapp.webapp_qa import resolve_webapp_public_base
from sevn.gateway.webapp.webapp_viewer import (
    append_viewer_stream_chunk,
    mark_viewer_stream_done,
    mint_webapp_viewer_token,
    webapp_viewer_launch_allowed,
)
from sevn.infrastructure.tunnel_manager import TunnelStatus
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout

_JWT_SECRET = "test-secret"
_BOT_TOKEN = "999:test-bot-token"


def _make_client(tmp_path: Path, *, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        channels=ChannelsWorkspaceSectionConfig(
            webchat=WebChatChannelConfig(jwt_secret=_JWT_SECRET, public=False),
            telegram=TelegramChannelConfig(
                bot_token_ref="env",
                webapp=TelegramWebappConfig(viewer_enabled=True),
            ),
        ),
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, cfg)

    async def _stub_resolve(workspace: object, *, content_root: object) -> str | None:
        _ = workspace, content_root
        return _BOT_TOKEN

    monkeypatch.setattr(
        "sevn.gateway.http_server._resolve_webapp_telegram_bot_token",
        _stub_resolve,
    )

    def factory() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.execute("PRAGMA foreign_keys=ON")
        apply_migrations(conn)
        return conn

    app = create_app(workspace=cfg, layout=layout, sqlite_connection_factory=factory)
    app.state.gateway_trace = NullTraceSink()
    return TestClient(app, raise_server_exceptions=True)


def _valid_init_data() -> str:
    fields = {
        "auth_date": "1700000000",
        "user": '{"id":42,"first_name":"Alex"}',
        "query_id": "abcd",
    }
    dcs = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret_key = hmac.new(b"WebAppData", _BOT_TOKEN.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret_key, dcs.encode("utf-8"), hashlib.sha256).hexdigest()
    payload = dict(fields)
    payload["hash"] = digest
    return urlencode(payload)


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    with _make_client(tmp_path, monkeypatch=monkeypatch) as c:
        yield c


def test_webapp_viewer_static_served(client: TestClient) -> None:
    """GET /webapp/viewer serves the viewer shell."""
    resp = client.get("/webapp/viewer?token=abc")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "viewer.js" in resp.text


def test_webapp_viewer_static_assets(client: TestClient) -> None:
    """Viewer CSS/JS are served under /webapp/viewer/."""
    css = client.get("/webapp/viewer/viewer.css")
    js = client.get("/webapp/viewer/viewer.js")
    assert css.status_code == 200
    assert js.status_code == 200
    assert "viewer-stream" in css.text


def test_webapp_viewer_payload_requires_initdata(client: TestClient) -> None:
    """Payload route returns 403 without verified initData."""
    conn = client.app.state.sqlite_conn
    token = mint_webapp_viewer_token(
        conn,
        workspace=client.app.state.workspace,
        user_id="42",
        chat_id=1,
        topic_id=None,
        gateway_message_id=5,
        platform_message_id=9,
        view="table",
        view_data={"headers": ["A"], "rows": [["1"]]},
    )
    resp = client.post(
        "/webapp/viewer/payload",
        json={"token": token, "init_data": "auth_date=1&hash=bad"},
    )
    assert resp.status_code == 403


def test_webapp_viewer_table_payload(client: TestClient) -> None:
    """Verified initData returns table view_data and burns token."""
    conn = client.app.state.sqlite_conn
    token = mint_webapp_viewer_token(
        conn,
        workspace=client.app.state.workspace,
        user_id="42",
        chat_id=1,
        topic_id=None,
        gateway_message_id=5,
        platform_message_id=9,
        view="table",
        view_data={
            "headers": ["Name", "Score"],
            "rows": [["Ada", "99"]],
            "caption": "Results",
        },
    )
    resp = client.post(
        "/webapp/viewer/payload",
        json={"token": token, "init_data": _valid_init_data()},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["view"] == "table"
    assert body["view_data"]["headers"] == ["Name", "Score"]
    row = conn.execute(
        "SELECT consumed FROM dispatcher_state WHERE token = ?",
        (token,),
    ).fetchone()
    assert row is not None
    assert int(row[0]) == 1


def test_webapp_viewer_stream_poll(client: TestClient) -> None:
    """Stream poll endpoint returns incremental chunks after initData verify."""
    conn = client.app.state.sqlite_conn
    stream_id = "stream-test-1"
    token = mint_webapp_viewer_token(
        conn,
        workspace=client.app.state.workspace,
        user_id="42",
        chat_id=1,
        topic_id=None,
        gateway_message_id=7,
        platform_message_id=11,
        view="stream",
        view_data={"chunks": ["hello"], "done": False},
        stream_id=stream_id,
    )
    append_viewer_stream_chunk(stream_id, " world")
    mark_viewer_stream_done(stream_id)
    init = _valid_init_data()
    poll1 = client.get(
        f"/webapp/viewer/stream/{stream_id}/poll",
        params={"token": token, "offset": 0, "init_data": init},
    )
    assert poll1.status_code == 200, poll1.text
    snap1 = poll1.json()
    assert snap1["chunks"] == ["hello", " world"]
    assert snap1["done"] is True
    poll2 = client.get(
        f"/webapp/viewer/stream/{stream_id}/poll",
        params={"token": token, "offset": snap1["next_offset"], "init_data": init},
    )
    assert poll2.json()["chunks"] == []


def test_webapp_viewer_stream_token_not_consumed_on_payload(client: TestClient) -> None:
    """Stream view keeps dispatcher token until stream endpoints finish."""
    conn = client.app.state.sqlite_conn
    stream_id = "stream-persist"
    token = mint_webapp_viewer_token(
        conn,
        workspace=client.app.state.workspace,
        user_id="42",
        chat_id=1,
        topic_id=None,
        gateway_message_id=8,
        platform_message_id=12,
        view="stream",
        view_data={"chunks": [], "done": True},
        stream_id=stream_id,
    )
    resp = client.post(
        "/webapp/viewer/payload",
        json={"token": token, "init_data": _valid_init_data()},
    )
    assert resp.status_code == 200
    row = conn.execute(
        "SELECT consumed FROM dispatcher_state WHERE token = ?",
        (token,),
    ).fetchone()
    assert row is not None
    assert int(row[0]) == 0


def test_resolve_webapp_public_base_uses_tunnel_when_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tunnel manager HTTPS URL is used when webhook is unset."""
    ws = WorkspaceConfig.minimal(
        workspace_root=".",
        infrastructure={"tunnel": {"mode": "cloudflare", "hostname": "bot.example.com"}},
    )

    def _healthy(_cfg: dict[str, object]) -> TunnelStatus:
        return TunnelStatus(
            mode="cloudflare",
            pid=123,
            healthy=True,
            public_url="https://bot.example.com",
            error=None,
        )

    monkeypatch.setattr(
        "sevn.infrastructure.tunnel_manager.default_manager.status",
        _healthy,
    )
    assert resolve_webapp_public_base(ws) == "https://bot.example.com"


def test_resolve_webapp_public_base_reads_tunnel_from_disk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On-disk tunnel setup is visible before in-memory workspace reload."""
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gateway": {"token": "x"},
                "infrastructure": {
                    "tunnel": {"mode": "cloudflare", "hostname": "live.example.com"},
                },
            },
        ),
        encoding="utf-8",
    )
    ws = WorkspaceConfig.minimal(
        workspace_root=str(tmp_path),
        infrastructure={"tunnel": {"mode": "none"}},
    )
    monkeypatch.setattr(
        "sevn.config.loader.resolve_sevn_json_path",
        lambda **_: sevn_json,
    )

    def _healthy(cfg: dict[str, object]) -> TunnelStatus:
        hostname = str(cfg.get("hostname") or "")
        return TunnelStatus(
            mode=str(cfg.get("mode") or "none"),
            pid=123,
            healthy=True,
            public_url=f"https://{hostname}" if hostname else None,
            error=None,
        )

    monkeypatch.setattr(
        "sevn.infrastructure.tunnel_manager.default_manager.status",
        _healthy,
    )
    assert resolve_webapp_public_base(ws) == "https://live.example.com"


def test_webapp_viewer_launch_disallowed_on_http_base() -> None:
    """Missing HTTPS public base disables viewer launch."""
    ws = WorkspaceConfig.minimal(workspace_root=".")
    assert webapp_viewer_launch_allowed(ws) is False


def test_webapp_viewer_launch_allowed_on_https() -> None:
    """HTTPS webhook + viewer_enabled allows launch."""
    ws = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        gateway={"token": "test-gateway-token"},
        channels=ChannelsWorkspaceSectionConfig(
            telegram=TelegramChannelConfig(
                webhook_url="https://bot.example.com/hook",
                webapp=TelegramWebappConfig(viewer_enabled=True),
            ),
        ),
    )
    assert webapp_viewer_launch_allowed(ws) is True
