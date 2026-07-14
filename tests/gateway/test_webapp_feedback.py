"""Web App share/feedback routes (`plan/control-surface-wave-plan.md` Wave 4)."""

from __future__ import annotations

import hashlib
import hmac
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
    WebChatChannelConfig,
    WorkspaceConfig,
)
from sevn.gateway.auth import mint_webchat_jwt
from sevn.gateway.http_server import create_app
from sevn.gateway.webapp.webapp_qa import mint_webapp_dispatcher_token
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
            telegram=TelegramChannelConfig(bot_token_ref="env"),
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


def test_webapp_feedback_submit_hmac_and_row(client: TestClient) -> None:
    """``POST /webapp/feedback/submit`` verifies initData and persists ``structured_feedback``."""
    conn = client.app.state.sqlite_conn
    token = mint_webapp_dispatcher_token(
        conn,
        kind="webapp_feedback",
        workspace=client.app.state.workspace,
        user_id="42",
        chat_id=1,
        topic_id=None,
        gateway_message_id=5,
        platform_message_id=99,
    )
    sub_key = "idem-key-1"
    resp = client.post(
        "/webapp/feedback/submit",
        json={
            "token": token,
            "init_data": _valid_init_data(),
            "submission_key": sub_key,
            "fields": {"body_text": "too verbose", "severity": "minor"},
        },
    )
    assert resp.status_code == 200, resp.text
    row = conn.execute(
        "SELECT body_text, user_id FROM structured_feedback WHERE submission_key = ?",
        (sub_key,),
    ).fetchone()
    assert row is not None
    assert row[0] == "too verbose"
    assert row[1] == "42"
    retry = client.post(
        "/webapp/feedback/submit",
        json={
            "token": token,
            "init_data": _valid_init_data(),
            "submission_key": sub_key,
            "fields": {"body_text": "ignored"},
        },
    )
    assert retry.status_code == 200
    count = conn.execute(
        "SELECT COUNT(*) FROM structured_feedback WHERE submission_key = ?",
        (sub_key,),
    ).fetchone()
    assert count is not None
    assert int(count[0]) == 1


def test_webapp_feedback_submit_webchat_jwt(client: TestClient) -> None:
    """Webchat path skips ``initData`` and uses Bearer JWT."""
    tok, _ = mint_webchat_jwt(secret=_JWT_SECRET, sub="owner", ttl_seconds=120)
    resp = client.post(
        "/webapp/feedback/submit",
        headers={"Authorization": f"Bearer {tok}"},
        json={
            "target_turn_id": "12",
            "fields": {"body_text": "webchat note"},
        },
    )
    assert resp.status_code == 200
    conn = client.app.state.sqlite_conn
    row = conn.execute(
        "SELECT channel, body_text FROM structured_feedback WHERE target_turn_id = '12'",
    ).fetchone()
    assert row is not None
    assert row[0] == "webchat"
    assert row[1] == "webchat note"


def test_webapp_share_payload_rejects_bad_hmac(client: TestClient) -> None:
    """Share payload endpoint returns 403 on invalid ``initData``."""
    conn = client.app.state.sqlite_conn
    token = mint_webapp_dispatcher_token(
        conn,
        kind="webapp_share",
        workspace=None,
        user_id="42",
        chat_id=1,
        topic_id=None,
        gateway_message_id=3,
        platform_message_id=8,
        share_text="share me",
    )
    resp = client.post(
        "/webapp/share/payload",
        json={"token": token, "init_data": "auth_date=1&hash=bad"},
    )
    assert resp.status_code == 403
