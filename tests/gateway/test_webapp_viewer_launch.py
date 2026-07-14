"""Mini App viewer launch buttons (`telegram-rich-inline-miniapps-wave-plan.md` Wave M2)."""

from __future__ import annotations

import hashlib
import hmac
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import pytest
from starlette.testclient import TestClient

from sevn.agent.tracing.sink import NullTraceSink
from sevn.config.workspace_config import (
    ChannelsWorkspaceSectionConfig,
    TelegramChannelConfig,
    TelegramWebappConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.gateway.menu.menu import build_chat_menu_webapp_request
from sevn.gateway.telegram.telegram_quick_actions import build_quick_action_inline_keyboard
from sevn.gateway.webapp.webapp_viewer import (
    attach_inline_viewer_launch_buttons,
    build_viewer_web_app_button,
    infer_viewer_payload_from_markdown,
    mint_webapp_viewer_token,
    webapp_share_to_story_enabled,
    webapp_viewer_launch_allowed,
)
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout

_JWT_SECRET = "test-secret"
_BOT_TOKEN = "999:test-bot-token"


def _https_workspace(*, share_to_story: bool = True) -> WorkspaceConfig:
    return WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        gateway={"token": "test-gateway-token"},
        channels=ChannelsWorkspaceSectionConfig(
            telegram=TelegramChannelConfig(
                webhook_url="https://bot.example.com/hook",
                webapp=TelegramWebappConfig(
                    viewer_enabled=True,
                    share_to_story=share_to_story,
                ),
            ),
        ),
    )


def _make_client(
    tmp_path: Path, *, monkeypatch: pytest.MonkeyPatch, ws: WorkspaceConfig
) -> TestClient:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    layout = WorkspaceLayout.from_config(sevn_json, ws)

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

    app = create_app(workspace=ws, layout=layout, sqlite_connection_factory=factory)
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
def https_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    with _make_client(tmp_path, monkeypatch=monkeypatch, ws=_https_workspace()) as c:
        yield c


def test_viewer_button_not_built_without_https_base() -> None:
    """Quick-action viewer row is omitted when public base is HTTP-only."""
    ws = WorkspaceConfig.minimal(workspace_root=".")
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    kb = build_quick_action_inline_keyboard(
        42,
        workspace=ws,
        conn=conn,
        user_id="1",
        gateway_message_id=5,
        platform_chat_id=1,
        viewer_source_text="| A | B |\n| - | - |\n| 1 | 2 |",
    )
    rows = kb.get("inline_keyboard") or []
    assert len(rows) == 1
    assert all(
        "web_app" not in btn or "viewer" not in btn["web_app"]["url"] for row in rows for btn in row
    )
    conn.close()


def test_viewer_button_built_on_https_with_table_markdown() -> None:
    """Viewer web_app row appears when HTTPS base + viewer_enabled + table markdown."""
    ws = _https_workspace()
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    kb = build_quick_action_inline_keyboard(
        42,
        workspace=ws,
        conn=conn,
        user_id="1",
        gateway_message_id=5,
        platform_chat_id=1,
        viewer_source_text="| Name | Score |\n| - | - |\n| Ada | 99 |",
    )
    rows = kb.get("inline_keyboard") or []
    assert len(rows) == 2
    viewer_urls = [
        btn["web_app"]["url"] for row in rows for btn in row if isinstance(btn.get("web_app"), dict)
    ]
    assert any("/webapp/viewer?token=" in url for url in viewer_urls)
    conn.close()


def test_build_viewer_web_app_button_requires_launch_allowed() -> None:
    """Standalone viewer button helper returns None without HTTPS public base."""
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    btn = build_viewer_web_app_button(
        conn,
        workspace=WorkspaceConfig.minimal(workspace_root="."),
        user_id="1",
        gateway_message_id=1,
        view="gallery",
        view_data={"images": ["https://example.com/a.png"]},
    )
    assert btn is None
    conn.close()


def _viewer_token_from_url(url: str) -> str:
    parsed = urlparse(url)
    token = parse_qs(parsed.query).get("token")
    assert token, f"missing token query param in {url!r}"
    return token[0]


def test_chat_menu_webapp_request_https() -> None:
    """Menu button uses MenuButtonWebApp when viewer launch is allowed."""
    body = build_chat_menu_webapp_request(_https_workspace())
    assert body["menu_button"]["type"] == "web_app"
    assert "/webapp/viewer?token=" in body["menu_button"]["web_app"]["url"]


def test_chat_menu_webapp_request_mints_registered_payload_id() -> None:
    """W3: menu launch must mint dispatcher state, not bare ``menu`` token (finding-9)."""
    body = build_chat_menu_webapp_request(_https_workspace())
    url = body["menu_button"]["web_app"]["url"]
    token = _viewer_token_from_url(url)
    assert token != "menu"
    assert "token=menu" not in url


def test_chat_menu_webapp_payload_resolves(https_client: TestClient) -> None:
    """W3: ``/webapp/viewer/payload`` resolves for chat-menu minted token (finding-9)."""
    body = build_chat_menu_webapp_request(https_client.app.state.workspace)
    token = _viewer_token_from_url(body["menu_button"]["web_app"]["url"])
    resp = https_client.post(
        "/webapp/viewer/payload",
        json={"token": token, "init_data": _valid_init_data()},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert "view" in payload
    assert "init_data" not in payload


def test_chat_menu_webapp_request_default_on_http() -> None:
    """Menu button resets to default when HTTPS public base is unavailable."""
    body = build_chat_menu_webapp_request(WorkspaceConfig.minimal(workspace_root="."))
    assert body["menu_button"]["type"] == "default"


def test_viewer_payload_requires_initdata(https_client: TestClient) -> None:
    """Payload route rejects requests without verified initData (M2.2)."""
    conn = https_client.app.state.sqlite_conn
    token = mint_webapp_viewer_token(
        conn,
        workspace=https_client.app.state.workspace,
        user_id="42",
        chat_id=1,
        topic_id=None,
        gateway_message_id=5,
        platform_message_id=9,
        view="gallery",
        view_data={"images": ["https://example.com/x.png"]},
    )
    resp = https_client.post(
        "/webapp/viewer/payload",
        json={"token": token, "init_data": "auth_date=1&hash=bad"},
    )
    assert resp.status_code == 403
    assert "init_data" not in resp.text


def test_viewer_payload_never_echoes_initdata(https_client: TestClient) -> None:
    """Successful payload responses omit initData (M2.2)."""
    conn = https_client.app.state.sqlite_conn
    init = _valid_init_data()
    token = mint_webapp_viewer_token(
        conn,
        workspace=https_client.app.state.workspace,
        user_id="42",
        chat_id=1,
        topic_id=None,
        gateway_message_id=5,
        platform_message_id=9,
        view="slideshow",
        view_data={"slides": [{"url": "https://example.com/a.png", "caption": "A"}]},
    )
    resp = https_client.post(
        "/webapp/viewer/payload",
        json={"token": token, "init_data": init},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "init_data" not in body
    assert init not in resp.text


def test_share_to_story_flag_in_payload(https_client: TestClient) -> None:
    """Payload exposes share_to_story config for the viewer SPA hook (M2.3)."""
    conn = https_client.app.state.sqlite_conn
    token = mint_webapp_viewer_token(
        conn,
        workspace=https_client.app.state.workspace,
        user_id="42",
        chat_id=1,
        topic_id=None,
        gateway_message_id=5,
        platform_message_id=9,
        view="gallery",
        view_data={"images": ["https://example.com/a.png"]},
    )
    resp = https_client.post(
        "/webapp/viewer/payload",
        json={"token": token, "init_data": _valid_init_data()},
    )
    assert resp.json()["share_to_story"] is True


def test_share_to_story_disabled_in_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """share_to_story=false omits the client hook flag."""
    ws = _https_workspace(share_to_story=False)
    with _make_client(tmp_path, monkeypatch=monkeypatch, ws=ws) as client:
        conn = client.app.state.sqlite_conn
        token = mint_webapp_viewer_token(
            conn,
            workspace=client.app.state.workspace,
            user_id="42",
            chat_id=1,
            topic_id=None,
            gateway_message_id=5,
            platform_message_id=9,
            view="gallery",
            view_data={"images": ["https://example.com/a.png"]},
        )
        resp = client.post(
            "/webapp/viewer/payload",
            json={"token": token, "init_data": _valid_init_data()},
        )
        assert resp.json()["share_to_story"] is False


def test_viewer_shell_includes_share_story_hook(https_client: TestClient) -> None:
    """Viewer static shell wires shareToStory UI hook (M2.3)."""
    js = https_client.get("/webapp/viewer/viewer.js")
    assert js.status_code == 200
    assert "shareToStory" in js.text
    assert "share_to_story" in js.text
    html = https_client.get("/webapp/viewer?token=abc")
    assert "viewer-share-story" in html.text


def test_attach_inline_viewer_launch_buttons() -> None:
    """Artifact inline rows gain Open viewer web_app when launch is allowed."""
    ws = _https_workspace()
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    rows = attach_inline_viewer_launch_buttons(
        [
            {
                "type": "article",
                "id": "artifacts:0",
                "title": "run: table.md",
                "_viewer_spec": {
                    "view": "table",
                    "view_data": {"headers": ["A"], "rows": [["1"]]},
                },
            },
        ],
        workspace=ws,
        conn=conn,
        user_id="42",
    )
    assert "reply_markup" in rows[0]
    btn = rows[0]["reply_markup"]["inline_keyboard"][0][0]
    assert btn["text"] == "Open viewer"
    assert "/webapp/viewer?token=" in btn["web_app"]["url"]
    assert "_viewer_spec" not in rows[0]
    conn.close()


def test_infer_viewer_payload_from_markdown_table() -> None:
    """Markdown table maps to table viewer payload."""
    inferred = infer_viewer_payload_from_markdown("| H |\n| - |\n| 1 |")
    assert inferred is not None
    view, data = inferred
    assert view == "table"
    assert data["headers"] == ["H"]
    assert webapp_viewer_launch_allowed(_https_workspace()) is True
    assert webapp_share_to_story_enabled(_https_workspace(share_to_story=False)) is False
