"""Telegram channel E2E gate (`plan/v1-tasks-ordered.md` Wave 7 Agent 7A).

Recorded Bot API ``Update`` fixtures exercise webhook ingress and long-poll
dispatch without a live test bot or network.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest
from starlette.testclient import TestClient

from sevn.agent.tracing.sink import NullTraceSink
from sevn.channels.telegram import TelegramAdapter, TelegramConfig
from sevn.config.workspace_config import (
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.gateway.channel_router import ChannelRouter
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.http_server import create_app
from sevn.gateway.media_store import MediaStore
from sevn.gateway.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.security.llm_guard_scanner import LLMGuardScanner, ScanResult, ScanVerdict
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "channels" / "telegram"


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((_FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


def _router_bundle(content_root: Path, conn: sqlite3.Connection) -> ChannelRouter:
    ws = WorkspaceConfig(
        schema_version=1,
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    return ChannelRouter(
        workspace=ws,
        content_root=content_root,
        sessions=SessionManager(conn),
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(content_root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
        media=MediaStore(conn, content_root),
    )


def _allow_scanner(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _stub(
        _self: LLMGuardScanner,
        *,
        text: str,
        channel: str,
        user_id: str,
        actor_is_owner: bool,
        source: str,
    ) -> ScanResult:
        _ = text, channel, user_id, actor_is_owner, source
        return ScanResult(
            verdict=ScanVerdict.allow,
            reasons=(),
            scores={},
            provider_used=None,
            details={"test": True},
        )

    monkeypatch.setattr(LLMGuardScanner, "scan_inbound", _stub)


def _app_client(tmp_path: Path, *, cfg: WorkspaceConfig | None = None) -> TestClient:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    workspace_cfg = cfg or WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, workspace_cfg)

    def factory() -> sqlite3.Connection:
        conn_local = sqlite3.connect(":memory:", check_same_thread=False)
        conn_local.execute("PRAGMA journal_mode=WAL")
        conn_local.execute("PRAGMA foreign_keys=ON")
        apply_migrations(conn_local)
        return conn_local

    app = create_app(
        workspace=workspace_cfg,
        layout=layout,
        sqlite_connection_factory=factory,
    )
    return TestClient(app, raise_server_exceptions=True)


@pytest.mark.asyncio
async def test_webhook_handle_webhook_persists_fixture_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Webhook path: ``handle_webhook`` → router persists user row."""

    _allow_scanner(monkeypatch)
    root = tmp_path / "w"
    root.mkdir()
    conn = _memory_conn()
    router: ChannelRouter | None = None
    try:
        router = _router_bundle(root, conn)
        router.register_adapter(TelegramAdapter(config=TelegramConfig(bot_token="")))
        payload = _load_fixture("update_dm_message.json")
        await router.handle_webhook("telegram", payload)
        row = conn.execute(
            "SELECT content FROM gateway_messages WHERE kind = 'message' AND role = 'user'",
        ).fetchone()
        assert row is not None
        assert row[0] == "hello from fixture"
    finally:
        if router is not None:
            await router.session_manager.drain()
        conn.close()


@pytest.mark.asyncio
async def test_edited_message_enqueues_new_llm_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Edited messages are not filtered; each update_id enqueues a user turn."""

    _allow_scanner(monkeypatch)
    root = tmp_path / "w"
    root.mkdir()
    conn = _memory_conn()
    router: ChannelRouter | None = None
    try:
        router = _router_bundle(root, conn)
        adapter = TelegramAdapter(config=TelegramConfig(bot_token=""))
        router.register_adapter(adapter)
        original = _load_fixture("update_dm_message.json")
        edited = _load_fixture("update_edited_message.json")
        edited_parsed = TelegramAdapter(config=TelegramConfig(bot_token="")).parse_webhook(edited)
        assert edited_parsed is not None
        assert edited_parsed.metadata.get("is_edited_message") is True
        await router.handle_webhook("telegram", original)
        await router.handle_webhook("telegram", edited)
        rows = conn.execute(
            "SELECT content FROM gateway_messages WHERE kind = 'message' AND role = 'user' "
            "ORDER BY rowid",
        ).fetchall()
        assert len(rows) == 2
        assert rows[0][0] == "hello from fixture"
        assert rows[1][0] == "revised text"
    finally:
        if router is not None:
            await router.session_manager.drain()
        conn.close()


def test_webhook_http_endpoint_accepts_recorded_fixture(tmp_path: Path) -> None:
    """Gateway ``POST /webhook/telegram`` accepts fixture JSON with secret header."""

    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        channels={"telegram": {"webhook_secret": "e2e-secret"}},
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    payload = _load_fixture("update_dm_message.json")
    with _app_client(tmp_path, cfg=cfg) as client:
        client.get("/health")
        denied = client.post("/webhook/telegram", json=payload)
        assert denied.status_code == 401
        ok = client.post(
            "/webhook/telegram",
            json=payload,
            headers={"X-Telegram-Bot-Api-Secret-Token": "e2e-secret"},
        )
        assert ok.status_code == 200
        assert ok.json().get("ok") is True
        conn = client.app.state.sqlite_conn
        count = conn.execute(
            "SELECT COUNT(*) FROM gateway_messages WHERE kind = 'message'",
        ).fetchone()[0]
        assert int(count) >= 1


@pytest.mark.asyncio
async def test_poll_loop_dispatches_recorded_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Polling path: mocked ``getUpdates`` delivers fixture to the router."""

    _allow_scanner(monkeypatch)
    root = tmp_path / "w"
    root.mkdir()
    conn = _memory_conn()
    router: ChannelRouter | None = None
    poll_payload = _load_fixture("update_dm_message.json")
    poll_round = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_round
        method = request.url.path.rsplit("/", 1)[-1]
        body: dict[str, Any] = {}
        if request.content:
            body = json.loads(request.content.decode())
        if method == "getUpdates":
            timeout = int(body.get("timeout") or 0)
            if timeout == 0:
                return httpx.Response(200, json={"ok": True, "result": []})
            poll_round += 1
            if poll_round == 1:
                return httpx.Response(200, json={"ok": True, "result": [poll_payload]})
            return httpx.Response(200, json={"ok": True, "result": []})
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        router = _router_bundle(root, conn)
        cfg = TelegramConfig(bot_token="poll-test-token", mode="poll")
        adapter = TelegramAdapter(config=cfg, http_client=client, sqlite_conn=conn)
        router.register_adapter(adapter)
        adapter._router = router
        await adapter._drain_pending()
        res = await adapter._api(
            "getUpdates",
            {
                "offset": adapter._last_update_id + 1,
                "timeout": 30,
                "allowed_updates": ["message", "edited_message", "callback_query"],
            },
        )
        assert res.get("ok") is True
        for upd in res.get("result") or []:
            if isinstance(upd, dict):
                uid = upd.get("update_id")
                if isinstance(uid, int):
                    adapter._last_update_id = max(adapter._last_update_id, uid)
                await router.handle_webhook("telegram", upd)
        row = conn.execute(
            "SELECT content FROM gateway_messages WHERE kind = 'message' AND role = 'user'",
        ).fetchone()
        assert row is not None
        assert row[0] == "hello from fixture"
        assert poll_round == 1
        await router.session_manager.drain()
        conn.close()
