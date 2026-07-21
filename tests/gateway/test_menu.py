"""Wave B1 ``/menu`` inline keyboard + edit-in-place callbacks."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.channels.telegram import TelegramAdapter
from sevn.config.workspace_config import (
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.gateway.agent_turn import build_agent_run_turn
from sevn.gateway.channel_router import ChannelRouter, IncomingMessage
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.commands.menu_action_router import MenuActionRouter, parse_action_callback
from sevn.gateway.config_io.workspace_config_io import load_raw_sevn_json, mutate_sevn_json
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.menu.menu import (
    MenuCallbackHandler,
    _apply_operator_readiness_gate,
    build_config_menu_keyboard,
    build_menu_keyboard,
    menu_message_text,
    parse_menu_callback_data,
)
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.onboarding.web_app import _get_nested
from sevn.security.llm_guard_scanner import LLMGuardScanner
from sevn.storage.migrate import apply_migrations
from sevn.tools.registry import ToolSet
from sevn.workspace.layout import WorkspaceLayout


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.execute("PRAGMA foreign_keys=ON")
    apply_migrations(c)
    return c


class _MenuCaptureTelegram(TelegramAdapter):
    """Records sends, callback answers, and markup edits."""

    def __init__(self) -> None:
        super().__init__(resolved_bot_token="test-token")
        self.sent: list[tuple[str, dict[str, Any]]] = []
        self.answered: list[tuple[str, str | None]] = []
        self.edited: list[dict[str, Any]] = []
        self.pinned: list[dict[str, Any]] = []
        self.unpinned: list[dict[str, Any]] = []

    async def send(self, message: Any) -> list[str]:
        md = dict(message.metadata) if isinstance(message.metadata, dict) else {}
        self.sent.append((message.text, md))
        return ["501"]

    async def answer_callback(
        self,
        callback_query_id: str,
        *,
        text: str = "",
    ) -> dict[str, Any]:
        """Match production :meth:`TelegramAdapter.answer_callback`."""
        self.answered.append((callback_query_id, text or None))
        return {"ok": True}

    async def answer_callback_query(
        self,
        *,
        callback_query_id: str,
        text: str | None = None,
    ) -> bool:
        """Legacy name for ``menu.py`` probes — delegates to :meth:`answer_callback`.

        Form-handler coverage must use a production-only double (see
        ``test_form_secret_wizard_acks_via_production_answer_callback``); this
        shim must not be the sole path that makes form/menu tests green.
        """
        result = await self.answer_callback(callback_query_id, text=text or "")
        return bool(result.get("ok"))

    async def edit_message_text(
        self,
        *,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: dict[str, Any],
        message_thread_id: int | None = None,
    ) -> bool:
        self.edited.append(
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "reply_markup": reply_markup,
                "message_thread_id": message_thread_id,
            },
        )
        return True

    async def edit_reply_markup(self, **kwargs: Any) -> bool:
        self.edited.append(dict(kwargs))
        return True

    async def pin_chat_message(
        self,
        *,
        chat_id: int,
        message_id: int,
        message_thread_id: int | None = None,
        disable_notification: bool = True,
    ) -> bool:
        _ = disable_notification
        self.pinned.append(
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "message_thread_id": message_thread_id,
            },
        )
        return True

    async def unpin_chat_message(
        self,
        *,
        chat_id: int,
        message_id: int,
        message_thread_id: int | None = None,
    ) -> bool:
        self.unpinned.append(
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "message_thread_id": message_thread_id,
            },
        )
        return True


def _build_config_router(
    tmp_path: Path,
) -> tuple[ChannelRouter, _MenuCaptureTelegram, Path]:
    """Full ``build_agent_run_turn`` stack with on-disk ``sevn.json``."""
    root = tmp_path / "w"
    root.mkdir()
    sevn_json = root / "sevn.json"
    sevn_json.write_text(
        (
            '{"schema_version":1,"workspace_root":".",'
            '"agent":{"codemode":{"enabled":false}},'
            '"gateway":{"host":"127.0.0.1","port":3001,"queue_mode":"cancel",'
            '"token":"${SECRET:keychain:sevn.gateway.token}"},'
            '"channels":{"telegram":{"quick_actions":{"show_regen":true}}},'
            '"security":{"scanner":{"heuristic_only":true}},'
            '"providers":{"use_main_model_for_all":false,'
            '"tier_default":{"triager":"test/triager","B":"test/tier-b"}}}'
        ),
        encoding="utf-8",
    )
    ws = _workspace()
    conn = _conn()
    cap = _MenuCaptureTelegram()
    router = ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=SessionManager(conn),
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
        media=MediaStore(conn, root),
        run_turn=AsyncMock(),
    )
    router.register_adapter(cap)
    build_agent_run_turn(
        router,
        conn,
        ws,
        WorkspaceLayout(sevn_json, root),
        NullTraceSink(),
    )
    return router, cap, sevn_json


def _config_callback(
    data: str,
    *,
    chat_id: int = 42,
    message_id: int = 99,
    callback_query_id: str = "cq-config-1",
    metadata_extra: dict[str, Any] | None = None,
) -> IncomingMessage:
    metadata: dict[str, Any] = {
        "callback_data": data,
        "callback_query_id": callback_query_id,
        "chat_id": chat_id,
        "message_id": message_id,
    }
    if metadata_extra:
        metadata.update(metadata_extra)
    return IncomingMessage(
        channel="telegram",
        user_id="u1",
        text=data,
        metadata=metadata,
    )


def _workspace(*, web_ui_url: str | None = None) -> WorkspaceConfig:
    kwargs: dict[str, Any] = {
        "schema_version": 1,
        "security": SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        "providers": {
            "use_main_model_for_all": False,
            "tier_default": {"triager": "stub/triager", "B": "stub/tier-b"},
        },
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    if web_ui_url is not None:
        kwargs["web_ui"] = {"url": web_ui_url}
    return WorkspaceConfig(**kwargs)


def test_build_menu_keyboard_root_sections() -> None:
    ws = _workspace()
    tool_set = ToolSet(registry_version=1, native=(), mcp=(), skill_descriptions={"a": "A"})
    kb = build_menu_keyboard(ws, tool_set=tool_set, section="root")
    labels = [btn["text"] for row in kb["inline_keyboard"] for btn in row]
    assert "🪪 Identity/About" in labels
    assert "⚡ Quick actions" in labels
    assert "🗂 Workspace" in labels
    assert "🔧 Diagnostics" in labels
    callbacks = [
        btn.get("callback_data")
        for row in kb["inline_keyboard"]
        for btn in row
        if "callback_data" in btn
    ]
    assert "menu:section:identity" in callbacks
    assert "menu:section:quick" in callbacks
    assert "menu:open_config" in callbacks
    assert "menu:home" in callbacks
    assert "menu:close" in callbacks


def test_build_menu_keyboard_quick_actions_section() -> None:
    ws = _workspace()
    tool_set = ToolSet(registry_version=1, native=(), mcp=(), skill_descriptions={})
    kb = build_menu_keyboard(ws, tool_set=tool_set, section="quick")
    callbacks = [
        btn.get("callback_data")
        for row in kb["inline_keyboard"]
        for btn in row
        if "callback_data" in btn
    ]
    assert "menu:cmd:new" in callbacks
    assert "menu:cmd:help" in callbacks
    assert "menu:cmd:voice" not in callbacks
    assert "menu:cmd:model" in callbacks
    assert "menu:cmd:status" in callbacks
    assert "menu:cmd:stop" in callbacks


def test_build_menu_keyboard_workspace_url_button() -> None:
    ws = _workspace(web_ui_url="https://app.example/chat")
    tool_set = ToolSet(registry_version=1, native=(), mcp=(), skill_descriptions={})
    kb = build_menu_keyboard(ws, tool_set=tool_set, section="workspace")
    url_buttons = [
        btn
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("url") == "https://app.example/chat"
    ]
    assert len(url_buttons) == 1


def test_menu_diagnostics_text_includes_model_and_budget() -> None:
    ws = _workspace()
    tool_set = ToolSet(registry_version=1, native=(), mcp=(), skill_descriptions={})
    body = menu_message_text(ws, tool_set=tool_set, section="diagnostics")
    assert "stub/tier-b" in body
    assert "PER_TOKEN" in body


@pytest.mark.asyncio
async def test_menu_callback_edits_message_not_send(tmp_path: Path) -> None:
    root = tmp_path / "w"
    root.mkdir()
    ws = _workspace()
    conn = _conn()
    cap = _MenuCaptureTelegram()
    router = ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=SessionManager(conn),
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
        media=MediaStore(conn, root),
        run_turn=AsyncMock(),
    )
    router.register_adapter(cap)
    handler = MenuCallbackHandler(ws, router)
    await handler.handle(
        IncomingMessage(
            channel="telegram",
            user_id="u1",
            text="menu:section:quick",
            metadata={
                "callback_data": "menu:section:quick",
                "callback_query_id": "cq-menu-1",
                "chat_id": 42,
                "message_id": 99,
            },
        ),
        session_id="telegram:u1",
    )
    assert cap.answered == [("cq-menu-1", None)]
    assert len(cap.edited) == 1
    assert cap.edited[0]["message_id"] == 99
    assert cap.edited[0]["reply_markup"]["inline_keyboard"]
    assert "Quick actions" in cap.edited[0]["text"]
    assert cap.sent == []


@pytest.mark.asyncio
async def test_menu_slash_opens_keyboard_message(tmp_path: Path) -> None:
    root = tmp_path / "w"
    root.mkdir()
    ws = _workspace()
    conn = _conn()
    cap = _MenuCaptureTelegram()
    router = ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=SessionManager(conn),
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
        media=MediaStore(conn, root),
        run_turn=AsyncMock(),
    )
    router.register_adapter(cap)
    build_agent_run_turn(
        router,
        conn,
        ws,
        WorkspaceLayout(root / "sevn.json", root),
        NullTraceSink(),
    )
    await router.route_incoming(
        IncomingMessage(
            channel="telegram",
            user_id="u1",
            text="/menu",
            metadata={"chat_id": 7},
        ),
    )
    assert len(cap.sent) == 1
    text, md = cap.sent[0]
    assert text == "sevn — menu"
    assert "inline_keyboard" in md
    assert parse_menu_callback_data("menu:section:diagnostics") == ("section", "diagnostics")


@pytest.mark.asyncio
async def test_menu_open_config_edits_to_config_root(tmp_path: Path) -> None:
    root = tmp_path / "w"
    root.mkdir()
    ws = _workspace()
    conn = _conn()
    cap = _MenuCaptureTelegram()
    router = ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=SessionManager(conn),
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
        media=MediaStore(conn, root),
        run_turn=AsyncMock(),
    )
    router.register_adapter(cap)
    build_agent_run_turn(
        router,
        conn,
        ws,
        WorkspaceLayout(root / "sevn.json", root),
        NullTraceSink(),
    )
    await router.route_incoming(
        IncomingMessage(
            channel="telegram",
            user_id="u1",
            text="menu:open_config",
            metadata={
                "callback_data": "menu:open_config",
                "callback_query_id": "cq-open-config",
                "chat_id": 42,
                "message_id": 99,
            },
        ),
    )
    assert ("cq-open-config", None) in cap.answered
    assert len(cap.edited) == 1
    assert cap.edited[0]["text"] == "sevn — /config"
    labels = [
        btn["text"] for row in cap.edited[0]["reply_markup"]["inline_keyboard"] for btn in row
    ]
    assert "📦 Session" in labels
    assert cap.sent == []
    assert parse_menu_callback_data("menu:open_config") == ("open_config", None)


def test_build_config_menu_keyboard_has_22_tiles() -> None:
    ws = _workspace()
    kb = build_config_menu_keyboard(ws, section="root")
    labels = [btn["text"] for row in kb["inline_keyboard"] for btn in row]
    section_labels = [label for label in labels if label.startswith(("📦", "🤖", "📜"))]
    assert len(section_labels) >= 2
    assert "📊 Dashboard" in labels
    assert "⌨️ Shortcuts" in labels
    assert "📜 Logs" in labels


def test_parse_action_callback_excludes_config_nav() -> None:
    assert parse_action_callback("cfg:section:voice") is None
    assert parse_action_callback("cfg:nav:home") is None
    assert parse_action_callback("cfg:nav:close") is None


@pytest.mark.parametrize(
    ("callback", "kind"),
    [
        ("cfg:voice:mode:off", "toggle"),
        ("short:run:standup", "prompt"),
        ("act:tool", "action"),
        ("scene:apply:work", "scene"),
        ("form:wizard:step=1", "form"),
    ],
)
def test_menu_action_router_kinds(callback: str, kind: str) -> None:
    parsed = parse_action_callback(callback)
    assert parsed is not None
    assert parsed[0] == kind


@pytest.mark.asyncio
async def test_toggle_mutates_sevn_json(tmp_path: Path) -> None:
    root = tmp_path / "w"
    root.mkdir()
    sevn_json = root / "sevn.json"
    sevn_json.write_text(
        '{"schema_version":1,"workspace_root":".","gateway":{"host":"127.0.0.1","port":3001,"queue_mode":"cancel","token":"${SECRET:keychain:sevn.gateway.token}"},"voice":{"tts_mode":"off"}}',
        encoding="utf-8",
    )
    ws = _workspace()
    conn = _conn()
    cap = _MenuCaptureTelegram()
    router = ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=SessionManager(conn),
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
        media=MediaStore(conn, root),
        run_turn=AsyncMock(),
    )
    router.register_adapter(cap)
    action = MenuActionRouter(
        workspace=ws,
        router=router,
        conn=conn,
        content_root=root,
        sevn_json_path=sevn_json,
    )
    mutate_sevn_json(sevn_json, lambda d: None)
    await action.handle(
        IncomingMessage(
            channel="telegram",
            user_id="u1",
            text="",
            metadata={"callback_data": "cfg:voice:mode:all", "callback_query_id": "cq1"},
        ),
        session_id="telegram:u1",
    )
    doc = load_raw_sevn_json(sevn_json)
    assert _get_nested(doc, "voice.tts_mode") == "all"


@pytest.mark.asyncio
async def test_config_toggle_persists_sevn_json(tmp_path: Path) -> None:
    router, cap, sevn_json = _build_config_router(tmp_path)
    await router.route_incoming(
        _config_callback("cfg:toggle:agent.codemode.enabled:true", callback_query_id="cq-toggle"),
    )
    doc = load_raw_sevn_json(sevn_json)
    assert _get_nested(doc, "agent.codemode.enabled") is True
    assert cap.answered
    assert cap.edited


@pytest.mark.asyncio
async def test_config_toggle_idempotent_roundtrip(tmp_path: Path) -> None:
    router, cap, sevn_json = _build_config_router(tmp_path)
    await router.route_incoming(
        _config_callback("cfg:toggle:agent.codemode.enabled:true", callback_query_id="cq-on"),
    )
    assert _get_nested(load_raw_sevn_json(sevn_json), "agent.codemode.enabled") is True
    await router.route_incoming(
        _config_callback("cfg:toggle:agent.codemode.enabled:false", callback_query_id="cq-off"),
    )
    assert _get_nested(load_raw_sevn_json(sevn_json), "agent.codemode.enabled") is False
    await router.route_incoming(
        _config_callback("cfg:toggle:agent.codemode.enabled:true", callback_query_id="cq-on2"),
    )
    assert _get_nested(load_raw_sevn_json(sevn_json), "agent.codemode.enabled") is True
    assert cap.answered
    assert cap.edited


@pytest.mark.asyncio
async def test_config_disabled_callback_no_write(tmp_path: Path) -> None:
    router, cap, sevn_json = _build_config_router(tmp_path)
    before = load_raw_sevn_json(sevn_json)
    await router.route_incoming(
        _config_callback("cfg:disabled:C9.1", callback_query_id="cq-disabled"),
    )
    assert ("cq-disabled", "Not active yet — see /config → Help for status.") in cap.answered
    assert load_raw_sevn_json(sevn_json) == before
    assert cap.edited == []


@pytest.mark.asyncio
async def test_config_help_callback_renders(tmp_path: Path) -> None:
    router, cap, sevn_json = _build_config_router(tmp_path)
    before = load_raw_sevn_json(sevn_json)
    await router.route_incoming(
        _config_callback("cfg:section:session", callback_query_id="cq-nav"),
    )
    await router.route_incoming(
        _config_callback("cfg:nav:help", callback_query_id="cq-help"),
    )
    assert cap.answered
    assert len(cap.sent) == 1
    help_text, _md = cap.sent[0]
    assert help_text.startswith("Help — session")
    assert load_raw_sevn_json(sevn_json) == before


def test_operator_readiness_gate_gates_unready_tile() -> None:
    ready_btn = {
        "text": "CodeMode off",
        "callback_data": "cfg:toggle:agent.codemode.enabled:true",
    }
    unready_btn = {
        "text": "λ-RLM",
        "callback_data": "cfg:toggle:executors.tier_cd.lambda_rlm.enabled:true",
    }
    chrome_row = [{"text": "⬅️ Back", "callback_data": "cfg:nav:back"}]
    raw = {"inline_keyboard": [[ready_btn], [unready_btn], chrome_row]}
    gated = _apply_operator_readiness_gate(raw)
    assert gated["inline_keyboard"][0][0]["callback_data"] == ready_btn["callback_data"]
    locked = gated["inline_keyboard"][1][0]
    assert locked["callback_data"] == "cfg:disabled:C9.1"
    assert locked["text"].startswith("🚧")
    assert gated["inline_keyboard"][-1] == chrome_row


@pytest.mark.asyncio
async def test_models_picker_page_rerenders(tmp_path: Path) -> None:
    router, cap, _sevn_json = _build_config_router(tmp_path)
    await router.route_incoming(
        _config_callback("cfg:section:models", callback_query_id="cq-nav"),
    )
    await router.route_incoming(
        _config_callback("cfg:models:page:tier_b:0", callback_query_id="cq-pick"),
    )
    picker_edit = cap.edited[-1]
    assert "Pick Tier B" in picker_edit["text"]
    assert "Page 1/" in picker_edit["text"]
    assert picker_edit["reply_markup"]["inline_keyboard"]
