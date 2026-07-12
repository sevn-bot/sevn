"""Wave TMF-1+ behavioral tests — Session QA, command invoke, form wizards."""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.config.model_resolution import ModelSlot, resolve_model_slot
from sevn.config.workspace_config import parse_workspace_config
from sevn.gateway.agent_turn import _apply_routing_footer_once, build_agent_run_turn
from sevn.gateway.channel_router import ChannelRouter, IncomingMessage, OutgoingMessage
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.commands.shortcuts_store import add_shortcut, find_shortcut
from sevn.gateway.media_store import MediaStore
from sevn.gateway.menu import (
    build_config_menu_keyboard,
    build_menu_keyboard,
    config_menu_message_text,
)
from sevn.gateway.rate_limit import TokenBucketLimiter
from sevn.gateway.routing_footer import telegram_show_routing_enabled
from sevn.gateway.session_manager import SessionManager
from sevn.gateway.telegram_quick_actions import GATEWAY_OUTBOUND_PHASE_KEY
from sevn.security.llm_guard_scanner import LLMGuardScanner
from sevn.security.secrets.factory import secrets_chain_from_workspace
from sevn.tools.registry import ToolSet
from sevn.workspace.layout import WorkspaceLayout
from tests.gateway.test_config_menu_actions import (
    _build_router,
    _config_callback,
    _config_section_callbacks,
)
from tests.gateway.test_menu import _conn, _MenuCaptureTelegram, _workspace
from tests.gateway.test_routing_footer import _sample_triage


def _qa_labels(metadata: dict[str, Any]) -> list[str]:
    kb = metadata.get("inline_keyboard")
    rows: list[Any]
    if isinstance(kb, dict):
        raw_rows = kb.get("inline_keyboard")
        rows = raw_rows if isinstance(raw_rows, list) else []
    elif isinstance(kb, list):
        rows = kb
    else:
        return []
    return [
        str(btn.get("text", ""))
        for row in rows
        if isinstance(row, list)
        for btn in row
        if isinstance(btn, dict)
    ]


def _build_owner_router(tmp_path: Path) -> tuple[ChannelRouter, _MenuCaptureTelegram, Path]:
    root = tmp_path / "w"
    root.mkdir()
    sevn_json = root / "sevn.json"
    sevn_json.write_text(
        (
            '{"schema_version":1,"workspace_root":".",'
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
        owner_user_ids=frozenset({"owner1"}),
    )
    router.register_adapter(cap)
    build_agent_run_turn(
        router,
        conn,
        ws,
        WorkspaceLayout(sevn_json, root),
        NullTraceSink(),
    )
    return router, cap, root


@pytest.mark.asyncio
async def test_session_qa_toggle_affects_outbound_keyboard(tmp_path: Path) -> None:
    """Disabling Regen via ``/config`` Session toggle omits it on the next outbound QA bar."""
    router, cap, _root = _build_router(tmp_path)
    await router.route_incoming(
        _config_callback("cfg:section:session", callback_query_id="cq-nav"),
    )
    kb = build_config_menu_keyboard(router._workspace, section="session")
    regen_btn = next(
        btn
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data", "").endswith("show_regen:false")
    )
    await router.route_incoming(
        _config_callback(regen_btn["callback_data"], callback_query_id="cq-toggle"),
    )
    conn = router._sessions.connection
    row = conn.execute(
        "SELECT session_id FROM gateway_sessions WHERE scope_key = ?",
        ("telegram:u1",),
    ).fetchone()
    assert row is not None
    session_id = str(row[0])
    meta = {"chat_id": 42}
    await router.route_outgoing(
        OutgoingMessage(
            channel="telegram",
            user_id="u1",
            text="Thinking…",
            session_id=session_id,
            metadata={**meta, GATEWAY_OUTBOUND_PHASE_KEY: "early"},
        ),
    )
    await router.route_outgoing(
        OutgoingMessage(
            channel="telegram",
            user_id="u1",
            text="Assistant reply",
            session_id=session_id,
            metadata={**meta, GATEWAY_OUTBOUND_PHASE_KEY: "final"},
        ),
    )
    assert len(cap.sent) >= 2
    labels = _qa_labels(cap.sent[-1][1])
    assert "♻ Regen" not in labels
    assert any("👍" in label for label in labels)


@pytest.mark.asyncio
async def test_session_thumbs_down_toggle_affects_outbound_keyboard(tmp_path: Path) -> None:
    """Disabling thumbs-down via Session toggle removes 👎 from the outbound QA bar."""
    router, cap, _root = _build_router(tmp_path)
    await router.route_incoming(
        _config_callback("cfg:section:session", callback_query_id="cq-nav"),
    )
    kb = build_config_menu_keyboard(router._workspace, section="session")
    down_btn = next(
        btn
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data", "").endswith("show_thumbs_down:false")
    )
    await router.route_incoming(
        _config_callback(down_btn["callback_data"], callback_query_id="cq-toggle"),
    )
    conn = router._sessions.connection
    row = conn.execute(
        "SELECT session_id FROM gateway_sessions WHERE scope_key = ?",
        ("telegram:u1",),
    ).fetchone()
    assert row is not None
    session_id = str(row[0])
    meta = {"chat_id": 42}
    await router.route_outgoing(
        OutgoingMessage(
            channel="telegram",
            user_id="u1",
            text="Thinking…",
            session_id=session_id,
            metadata={**meta, GATEWAY_OUTBOUND_PHASE_KEY: "early"},
        ),
    )
    await router.route_outgoing(
        OutgoingMessage(
            channel="telegram",
            user_id="u1",
            text="Reply",
            session_id=session_id,
            metadata={**meta, GATEWAY_OUTBOUND_PHASE_KEY: "final"},
        ),
    )
    labels = _qa_labels(cap.sent[-1][1])
    assert "👎" not in labels
    assert any("👍" in label for label in labels)


@pytest.mark.asyncio
async def test_show_routing_toggle_enables_routing_footer(tmp_path: Path) -> None:
    """Enabling Show routing via Channels toggle gates routing footer on outbound text."""
    router, _cap, _root = _build_router(tmp_path)
    assert telegram_show_routing_enabled(router._workspace) is False
    await router.route_incoming(
        _config_callback("cfg:section:channels", callback_query_id="cq-nav"),
    )
    kb = build_config_menu_keyboard(router._workspace, section="channels")
    toggle_btn = next(
        btn
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data", "").startswith("cfg:toggle:channels.telegram.show_routing:true")
    )
    await router.route_incoming(
        _config_callback(toggle_btn["callback_data"], callback_query_id="cq-toggle"),
    )
    assert telegram_show_routing_enabled(router._workspace) is True
    show_routing = telegram_show_routing_enabled(router._workspace)
    text, applied = _apply_routing_footer_once(
        "Assistant body",
        triage=_sample_triage(),
        triager_ms=None,
        enabled=show_routing,
        sent=False,
    )
    assert applied is True
    assert "intent=NEW_REQUEST" in text


@pytest.mark.asyncio
async def test_show_routing_off_omits_routing_footer(tmp_path: Path) -> None:
    """Default ``show_routing=false`` leaves assistant text without routing footer."""
    router, _cap, _root = _build_router(tmp_path)
    show_routing = telegram_show_routing_enabled(router._workspace)
    text, applied = _apply_routing_footer_once(
        "Plain reply",
        triage=_sample_triage(),
        triager_ms=None,
        enabled=show_routing,
        sent=False,
    )
    assert applied is False
    assert text == "Plain reply"
    assert "intent=" not in text


@pytest.mark.asyncio
async def test_config_menu_shortcuts_respects_owner_flag(tmp_path: Path) -> None:
    """Shortcuts section lists owner-only shortcuts only when ``is_owner`` is true."""
    router, cap, root = _build_owner_router(tmp_path)
    add_shortcut(
        root,
        {
            "name": "owneronly",
            "description": "Owner shortcut",
            "type": "prompt",
            "payload": {},
            "auth": "OWNER",
        },
    )
    await router.route_incoming(
        IncomingMessage(
            channel="telegram",
            user_id="guest",
            text="cfg:section:shortcuts",
            metadata={
                "callback_data": "cfg:section:shortcuts",
                "callback_query_id": "cq-guest",
                "chat_id": 42,
                "message_id": 99,
            },
        ),
    )
    assert "owneronly" not in cap.edited[-1]["text"]
    delete_cbs = [
        btn.get("callback_data")
        for row in cap.edited[-1]["reply_markup"]["inline_keyboard"]
        for btn in row
        if str(btn.get("callback_data", "")).startswith("act:shortcut_delete:")
    ]
    assert delete_cbs == []
    await router.route_incoming(
        IncomingMessage(
            channel="telegram",
            user_id="owner1",
            text="cfg:section:shortcuts",
            metadata={
                "callback_data": "cfg:section:shortcuts",
                "callback_query_id": "cq-owner",
                "chat_id": 42,
                "message_id": 99,
            },
        ),
    )
    assert "owneronly" in cap.edited[-1]["text"]
    root = tmp_path / "w"
    callbacks = _config_section_callbacks(
        router._workspace,
        "shortcuts",
        content_root=root,
        user_id="owner1",
        is_owner=True,
    )
    assert "act:shortcut_delete:owneronly" in callbacks


def _menu_callback(
    data: str,
    *,
    chat_id: int = 42,
    message_id: int = 88,
    callback_query_id: str = "cq-menu-1",
) -> IncomingMessage:
    return IncomingMessage(
        channel="telegram",
        user_id="u1",
        text=data,
        metadata={
            "callback_data": data,
            "callback_query_id": callback_query_id,
            "chat_id": chat_id,
            "message_id": message_id,
        },
    )


def test_help_keyboard_includes_status_and_stop() -> None:
    """Help section catalog documents ``/status`` and ``/stop`` slash commands."""
    from sevn.gateway.menu_readiness import config_menu_help_catalog_text

    catalog = config_menu_help_catalog_text()
    assert "/status" in catalog
    assert "/stop" in catalog
    kb = build_config_menu_keyboard(_workspace(), section="help")
    callbacks = [
        btn.get("callback_data")
        for row in kb["inline_keyboard"]
        for btn in row
        if "callback_data" in btn
    ]
    assert all(str(cb).startswith("cfg:nav:") for cb in callbacks)


def test_menu_quick_and_diagnostics_include_status_stop() -> None:
    """Quick section has status/stop; Diagnostics has status (D2.5, D2.6, D4.1)."""
    ws = _workspace()
    tool_set = ToolSet(registry_version=1, native=(), mcp=(), skill_descriptions={})
    quick = build_menu_keyboard(ws, tool_set=tool_set, section="quick")
    quick_cbs = [
        btn.get("callback_data")
        for row in quick["inline_keyboard"]
        for btn in row
        if "callback_data" in btn
    ]
    assert "menu:cmd:status" in quick_cbs
    assert "menu:cmd:stop" in quick_cbs
    diag = build_menu_keyboard(ws, tool_set=tool_set, section="diagnostics")
    diag_cbs = [
        btn.get("callback_data")
        for row in diag["inline_keyboard"]
        for btn in row
        if "callback_data" in btn
    ]
    assert "menu:cmd:status" in diag_cbs
    assert "menu:section:identity" not in diag_cbs


def test_identity_and_workspace_omit_noop_stubs() -> None:
    """D1.1 self-loop and D3.2 workspace noop are omitted from keyboards."""
    ws = _workspace()
    tool_set = ToolSet(registry_version=1, native=(), mcp=(), skill_descriptions={})
    identity = build_menu_keyboard(ws, tool_set=tool_set, section="identity")
    identity_cbs = [
        btn.get("callback_data")
        for row in identity["inline_keyboard"]
        for btn in row
        if "callback_data" in btn
    ]
    assert "menu:section:identity" not in identity_cbs
    workspace_kb = build_menu_keyboard(ws, tool_set=tool_set, section="workspace")
    workspace_cbs = [
        btn.get("callback_data")
        for row in workspace_kb["inline_keyboard"]
        for btn in row
        if "callback_data" in btn
    ]
    assert "menu:section:workspace" not in workspace_cbs


@pytest.mark.asyncio
async def test_config_help_cmd_executes_help_not_toast(tmp_path: Path) -> None:
    """``cfg:help:cmd:help`` sends core ``/help`` text instead of a toast hint."""
    router, cap, _root = _build_router(tmp_path)
    await router.route_incoming(_config_callback("cfg:help:cmd:help", callback_query_id="cq-help"))
    assert cap.answered == [("cq-help", None)]
    assert cap.edited == []
    assert len(cap.sent) == 1
    assert cap.sent[0][0].startswith("Core commands:")


@pytest.mark.asyncio
async def test_menu_cmd_status_sends_new_message(tmp_path: Path) -> None:
    """``menu:cmd:status`` from /menu Quick sends a new status message."""
    router, cap, _root = _build_router(tmp_path)
    await router.route_incoming(_menu_callback("menu:cmd:status", callback_query_id="cq-st"))
    assert cap.answered == [("cq-st", None)]
    assert cap.edited == []
    assert len(cap.sent) == 1
    assert "Session:" in cap.sent[0][0]
    assert "Model:" in cap.sent[0][0]


@pytest.mark.asyncio
async def test_pin_cmd_stop_sends_new_message_without_edit(tmp_path: Path) -> None:
    """Pin keyboard ``menu:cmd:stop`` sends a new chat message (F2)."""
    router, cap, _root = _build_router(tmp_path)
    router._telegram_dashboard_pins = {"telegram:u1:0": 77}
    await router.route_incoming(
        _menu_callback(
            "menu:cmd:stop",
            message_id=77,
            callback_query_id="cq-pin-stop",
        ),
    )
    assert cap.answered == [("cq-pin-stop", None)]
    assert cap.edited == []
    assert len(cap.sent) == 1
    assert cap.sent[0][0] == "Stopped."
    assert "reply_to_message_id" not in cap.sent[0][1]


@pytest.mark.asyncio
async def test_config_help_cmd_menu_opens_menu_message(tmp_path: Path) -> None:
    """``cfg:help:cmd:menu`` opens a new ``/menu`` root message."""
    router, cap, _root = _build_router(tmp_path)
    await router.route_incoming(_config_callback("cfg:help:cmd:menu", callback_query_id="cq-m"))
    assert cap.answered == [("cq-m", None)]
    assert cap.edited == []
    assert len(cap.sent) == 1
    assert cap.sent[0][0] == "sevn — menu"
    kb = cap.sent[0][1].get("inline_keyboard")
    assert isinstance(kb, dict)
    assert kb["inline_keyboard"][0][0]["callback_data"] == "menu:section:identity"


def _text_message(
    text: str,
    *,
    user_id: str = "u1",
    chat_id: int = 42,
) -> IncomingMessage:
    return IncomingMessage(
        channel="telegram",
        user_id=user_id,
        text=text,
        metadata={"chat_id": chat_id},
    )


def _build_secrets_owner_router(
    tmp_path: Path,
    *,
    master_key: bytes,
) -> tuple[ChannelRouter, _MenuCaptureTelegram, Path]:
    root = tmp_path / "w"
    root.mkdir()
    store = root / "store.enc"
    sevn_json = root / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "gateway": {
                    "host": "127.0.0.1",
                    "port": 3001,
                    "queue_mode": "cancel",
                    "token": "${SECRET:keychain:sevn.gateway.token}",
                },
                "secrets_backend": {
                    "chain": [
                        {"type": "encrypted_file", "path": "store.enc", "key_source": "master_key"}
                    ],
                },
            },
        ),
        encoding="utf-8",
    )
    _ = store
    ws = parse_workspace_config(json.loads(sevn_json.read_text(encoding="utf-8")))
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
        owner_user_ids=frozenset({"owner1"}),
    )
    router.register_adapter(cap)
    build_agent_run_turn(
        router,
        conn,
        ws,
        WorkspaceLayout(sevn_json, root),
        NullTraceSink(),
    )
    os.environ["SEVN_SECRETS_MASTER_KEY"] = master_key.hex()
    return router, cap, root


@pytest.mark.asyncio
async def test_shortcut_add_form_wizard_persists_and_republishes(tmp_path: Path) -> None:
    """``form:shortcut_add`` collects name + prompt and writes ``shortcuts.json``."""
    router, cap, _ws = _build_router(tmp_path)
    content_root = router._content_root
    cap._flush_set_my_commands = AsyncMock()
    await router.route_incoming(
        _config_callback("form:shortcut_add", callback_query_id="cq-add"),
    )
    assert cap.answered == [("cq-add", None)]
    assert "shortcut name" in cap.sent[-1][0].lower()
    await router.route_incoming(_text_message("standup"))
    assert "prompt text" in cap.sent[-1][0].lower()
    await router.route_incoming(_text_message("What did you ship today?"))
    row = find_shortcut(content_root, "standup")
    assert row is not None
    assert row.get("type") == "prompt"
    cap._flush_set_my_commands.assert_awaited()
    assert "saved" in cap.sent[-1][0].lower()


@pytest.mark.asyncio
async def test_secret_wizard_rejects_non_owner(tmp_path: Path) -> None:
    """``form:secret_wizard`` is owner-only (C6.1)."""
    router, cap, _root = _build_owner_router(tmp_path)
    await router.route_incoming(
        IncomingMessage(
            channel="telegram",
            user_id="guest",
            text="form:secret_wizard",
            metadata={
                "callback_data": "form:secret_wizard",
                "callback_query_id": "cq-sec",
                "chat_id": 42,
                "message_id": 99,
            },
        ),
    )
    assert cap.answered == [("cq-sec", "Owner only.")]
    assert cap.sent == []


@pytest.mark.asyncio
async def test_secret_wizard_stores_secret_for_owner(tmp_path: Path) -> None:
    """Owner completes secret wizard and value is persisted via secrets chain."""
    mk = secrets.token_bytes(32)
    router, cap, root = _build_secrets_owner_router(tmp_path, master_key=mk)
    try:
        await router.route_incoming(
            IncomingMessage(
                channel="telegram",
                user_id="owner1",
                text="form:secret_wizard",
                metadata={
                    "callback_data": "form:secret_wizard",
                    "callback_query_id": "cq-wiz",
                    "chat_id": 42,
                    "message_id": 99,
                },
            ),
        )
        assert cap.answered == [("cq-wiz", None)]
        await router.route_incoming(_text_message("demo.api_key", user_id="owner1"))
        await router.route_incoming(_text_message("super-secret-value", user_id="owner1"))
        chain = secrets_chain_from_workspace(root, router._workspace.secrets_backend)
        stored = await chain.get("demo.api_key")
        assert stored == "super-secret-value"
        assert "stored" in cap.sent[-1][0].lower()
    finally:
        os.environ.pop("SEVN_SECRETS_MASTER_KEY", None)


def test_secrets_caption_lists_ref_key_names(tmp_path: Path) -> None:
    """Secrets section caption lists ``${SECRET:…}`` logical key names (C6.2)."""
    root = tmp_path / "w"
    root.mkdir()
    sevn_json = root / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "channels": {
                    "telegram": {"bot_token_ref": "${SECRET:keychain:telegram.bot_token}"}
                },
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            },
        ),
        encoding="utf-8",
    )
    ws = _workspace()
    text = config_menu_message_text(ws, section="secrets", content_root=root)
    assert "Referenced keys:" in text
    assert "telegram.bot_token" in text


@pytest.mark.asyncio
async def test_form_shortcut_add_not_toast_only(tmp_path: Path) -> None:
    """``form:shortcut_add`` no longer returns the stub ``Queued form handler`` toast."""
    router, cap, _root = _build_router(tmp_path)
    await router.route_incoming(
        _config_callback("form:shortcut_add", callback_query_id="cq-form"),
    )
    assert cap.answered == [("cq-form", None)]
    assert not any("Queued form handler" in str(item) for item in cap.answered)
    assert cap.sent


@pytest.mark.asyncio
async def test_dashboard_create_pin_sends_registers_and_pins(tmp_path: Path) -> None:
    """C15.3 create pin sends dashboard body, registers id, and calls pinChatMessage."""
    from sevn.gateway.dashboard_pin import lookup_dashboard_pin_message_id

    router, cap, _root = _build_router(tmp_path)
    await router.route_incoming(
        _config_callback("cfg:dashboard:create_pin", callback_query_id="cq-create"),
    )
    assert len(cap.sent) == 1
    assert "sevn dashboard" in cap.sent[0][0]
    assert (
        cap.sent[0][1]["inline_keyboard"]["inline_keyboard"][0][0]["callback_data"]
        == "menu:cmd:new"
    )
    pin_id = lookup_dashboard_pin_message_id(router, chat_id=42, topic_id=None)
    assert pin_id == 501
    assert cap.pinned == [{"chat_id": 42, "message_id": 501, "message_thread_id": None}]
    assert ("cq-create", "Pin created.") in cap.answered


@pytest.mark.asyncio
async def test_dashboard_create_pin_updates_existing_registry_entry(tmp_path: Path) -> None:
    """C15.3 update path re-renders an existing registered pin and re-pins it."""
    router, cap, _root = _build_router(tmp_path)
    router._telegram_dashboard_pins = {"42:0": 1001}
    await router.route_incoming(
        _config_callback("cfg:dashboard:create_pin", callback_query_id="cq-update"),
    )
    assert cap.sent == []
    assert len(cap.edited) == 2
    pin_edit = cap.edited[0]
    assert pin_edit["message_id"] == 1001
    assert "sevn dashboard" in pin_edit["text"]
    assert cap.pinned == [{"chat_id": 42, "message_id": 1001, "message_thread_id": None}]
    assert ("cq-update", "Pin updated.") in cap.answered


@pytest.mark.asyncio
async def test_dashboard_refresh_pin_requires_registry_entry(tmp_path: Path) -> None:
    """C15.1 refresh schedules edit only when pin is registered for the topic."""
    from unittest.mock import AsyncMock

    router, cap, _root = _build_router(tmp_path)
    publisher = AsyncMock()
    publisher.schedule_render = AsyncMock()
    router._dashboard_pin_publisher = publisher
    await router.route_incoming(
        _config_callback("cfg:dashboard:refresh_pin", callback_query_id="cq-miss"),
    )
    publisher.schedule_render.assert_not_awaited()
    assert len(cap.sent) == 1
    assert cap.sent[0][0] == "No pinned dashboard in this topic."
    assert cap.sent[0][1]["chat_id"] == 42

    router._telegram_dashboard_pins = {"42:0": 1001}
    await router.route_incoming(
        _config_callback("cfg:dashboard:refresh_pin", callback_query_id="cq-refresh"),
    )
    publisher.schedule_render.assert_awaited_once()
    assert ("cq-refresh", "Pin refresh scheduled.") in cap.answered


@pytest.mark.asyncio
async def test_dashboard_unpin_removes_registry_and_unpins_chat(tmp_path: Path) -> None:
    """C15.4 unpin drops registry entry and calls unpinChatMessage."""
    from sevn.gateway.dashboard_pin import lookup_dashboard_pin_message_id

    router, cap, _root = _build_router(tmp_path)
    router._telegram_dashboard_pins = {"42:0": 1001}
    await router.route_incoming(
        _config_callback("cfg:dashboard:unpin", callback_query_id="cq-unpin"),
    )
    assert lookup_dashboard_pin_message_id(router, chat_id=42, topic_id=None) is None
    assert cap.unpinned == [{"chat_id": 42, "message_id": 1001, "message_thread_id": None}]
    assert ("cq-unpin", "Unpinned.") in cap.answered


@pytest.mark.asyncio
async def test_pin_shortcuts_opens_config_section_message(tmp_path: Path) -> None:
    """F6 ``cfg:section:shortcuts`` from pin opens a new /config Shortcuts message."""
    router, cap, _root = _build_router(tmp_path)
    router._telegram_dashboard_pins = {"42:0": 77}
    await router.route_incoming(
        _config_callback(
            "cfg:section:shortcuts",
            message_id=77,
            callback_query_id="cq-pin-shortcuts",
        ),
    )
    assert cap.answered == [("cq-pin-shortcuts", None)]
    assert cap.edited == []
    assert len(cap.sent) == 1
    assert "Shortcuts" in cap.sent[0][0]
    shortcuts_cbs = _config_section_callbacks(
        router._workspace,
        "shortcuts",
        content_root=tmp_path / "w",
        user_id="u1",
    )
    assert "form:shortcut_add" in shortcuts_cbs


def _build_models_router(
    tmp_path: Path,
) -> tuple[ChannelRouter, _MenuCaptureTelegram, Path]:
    """Router with a multi-model catalog for model picker tests."""
    from sevn.config.loader import load_workspace

    root = tmp_path / "w"
    root.mkdir()
    sevn_json = root / "sevn.json"
    sevn_json.write_text(
        (
            '{"schema_version":1,"workspace_root":".",'
            '"gateway":{"host":"127.0.0.1","port":3001,"queue_mode":"cancel",'
            '"token":"${SECRET:keychain:sevn.gateway.token}"},'
            '"web_ui":{"url":"https://app.example/"},'
            '"providers":{"use_main_model_for_all":false,'
            '"last_used_model":"test/other",'
            '"models":{"test/a":{},"test/b":{},"test/c":{},"test/d":{},"test/e":{},'
            '"test/triager":{},"test/tier-b":{},"test/tier-c":{},'
            '"test/other":{},"test/extra":{}},'
            '"tier_default":{"triager":"test/triager","B":"test/tier-b",'
            '"C":"test/tier-c","D":"test/tier-c"}}}'
        ),
        encoding="utf-8",
    )
    ws, _ = load_workspace(sevn_json=sevn_json)
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
    return router, cap, root


@pytest.mark.asyncio
async def test_models_picker_page_navigation(tmp_path: Path) -> None:
    """C4.2-C4.4 paginated picker shows Next and persists page caption."""
    router, cap, _root = _build_models_router(tmp_path)
    await router.route_incoming(
        _config_callback("cfg:section:models", callback_query_id="cq-nav"),
    )
    await router.route_incoming(
        _config_callback("cfg:models:page:tier_b:0", callback_query_id="cq-pick"),
    )
    picker_edit = cap.edited[-1]
    assert "Pick Tier B" in picker_edit["text"]
    assert "Page 1/" in picker_edit["text"]
    callbacks = _config_section_callbacks(
        router._workspace,
        "models",
        models_picker_slot="tier_b",
        models_picker_page=0,
    )
    assert any(cb == "cfg:models:pick:tier_b:0" for cb in callbacks)
    assert "cfg:models:page:tier_b:1" in callbacks
    await router.route_incoming(
        _config_callback("cfg:models:page:tier_b:1", callback_query_id="cq-page"),
    )
    assert "Page 2/" in cap.edited[-1]["text"]


@pytest.mark.asyncio
async def test_models_pick_persists_to_sevn_json(tmp_path: Path) -> None:
    """Selecting a catalog row writes the slot in ``sevn.json`` and refreshes caption."""
    from sevn.gateway.workspace_config_io import load_raw_sevn_json
    from sevn.onboarding.web_app import _get_nested

    router, cap, root = _build_models_router(tmp_path)
    sevn_json = root / "sevn.json"
    await router.route_incoming(
        _config_callback("cfg:models:pick:tier_b:0", callback_query_id="cq-select"),
    )
    doc = load_raw_sevn_json(sevn_json)
    assert _get_nested(doc, "providers.tier_default.B") == "test/a"
    assert "Tier B: test/a" in cap.edited[-1]["text"]


@pytest.mark.asyncio
async def test_models_swap_last_model(tmp_path: Path) -> None:
    """C4.5 swap mirrors ``/model toggle`` using ``providers.last_used_model``."""
    from sevn.gateway.workspace_config_io import load_raw_sevn_json
    from sevn.onboarding.web_app import _get_nested

    router, cap, root = _build_models_router(tmp_path)
    sevn_json = root / "sevn.json"
    await router.route_incoming(
        _config_callback("cfg:models:swap", callback_query_id="cq-swap"),
    )
    doc = load_raw_sevn_json(sevn_json)
    assert _get_nested(doc, "providers.tier_default.B") == "test/other"
    assert _get_nested(doc, "providers.last_used_model") == "test/tier-b"
    assert "Tier B: test/other" in cap.edited[-1]["text"]


@pytest.mark.asyncio
async def test_unified_model_toggle_affects_slot_resolution(tmp_path: Path) -> None:
    """C4.1 unified toggle makes tier B caption match triager when enabled."""
    router, cap, _root = _build_models_router(tmp_path)
    await router.route_incoming(
        _config_callback("cfg:section:models", callback_query_id="cq-nav"),
    )
    kb = build_config_menu_keyboard(router._workspace, section="models")
    toggle_btn = next(
        btn
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data", "").startswith(
            "cfg:toggle:providers.use_main_model_for_all:true"
        )
    )
    await router.route_incoming(
        _config_callback(toggle_btn["callback_data"], callback_query_id="cq-unified"),
    )
    triager = resolve_model_slot(router._workspace, ModelSlot.triager)
    tier_b = resolve_model_slot(router._workspace, ModelSlot.tier_b)
    assert triager == tier_b
    assert "Unified model: on" in cap.edited[-1]["text"]
    assert f"Tier B: {triager}" in cap.edited[-1]["text"]


@pytest.mark.asyncio
async def test_models_open_tab_url_when_web_ui_configured(tmp_path: Path) -> None:
    """C4.6 renders Open Models tab URL when ``web_ui.url`` is set."""
    router, cap, _root = _build_models_router(tmp_path)
    await router.route_incoming(_config_callback("cfg:section:models"))
    urls = [
        btn.get("url")
        for row in cap.edited[-1]["reply_markup"]["inline_keyboard"]
        for btn in row
        if btn.get("url")
    ]
    assert any(str(u).endswith("/mission/providers-llms") for u in urls)


def _my_sevn_bot_callbacks(*, is_owner: bool) -> list[str]:
    from sevn.config.workspace_config import WorkspaceConfig

    kb = build_config_menu_keyboard(
        WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        ),
        section="my_sevn_bot",
        is_owner=is_owner,
    )
    return [
        str(btn.get("callback_data"))
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data")
    ]


def test_my_sevn_bot_restart_buttons_ready() -> None:
    """C18.4/C18.5 are pressable (not gated) on owner keyboards."""
    from sevn.gateway.menu_readiness import readiness_for_callback

    assert readiness_for_callback("act:gateway:restart") == "Ready"
    assert readiness_for_callback("act:proxy:restart") == "Ready"


def test_my_sevn_bot_restart_buttons_owner_only() -> None:
    """C18.4/C18.5 restart rows render only for workspace owners under My sevn bot."""
    owner_cbs = _my_sevn_bot_callbacks(is_owner=True)
    assert "act:gateway:restart" in owner_cbs
    assert "act:proxy:restart" in owner_cbs
    assert "cfg:logs:deployment_id" in owner_cbs
    non_owner_cbs = _my_sevn_bot_callbacks(is_owner=False)
    assert "act:gateway:restart" not in non_owner_cbs
    assert "act:proxy:restart" not in non_owner_cbs
    assert "cfg:logs:deployment_id" in non_owner_cbs


@pytest.mark.asyncio
async def test_gateway_restart_non_owner_rejected(tmp_path: Path) -> None:
    """Non-owner tapping restart gets an owner-only toast."""
    router, cap, _root = _build_router(tmp_path)
    await router.route_incoming(
        _config_callback("act:gateway:restart", callback_query_id="cq-restart"),
    )
    assert ("cq-restart", "Owner only.") in cap.answered


@pytest.mark.asyncio
async def test_gateway_restart_confirm_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Owner two-step gateway restart shows confirm keyboard then invokes restart."""
    router, cap, _root = _build_owner_router(tmp_path)
    calls: list[str] = []

    def _fake_gateway_restart() -> str:
        calls.append("gateway")
        return "gateway restart: ok"

    monkeypatch.setattr(
        "sevn.gateway.commands.menu_action_router._run_gateway_restart",
        _fake_gateway_restart,
    )

    owner_cb = lambda data, cq: IncomingMessage(  # noqa: E731
        channel="telegram",
        user_id="owner1",
        text=data,
        metadata={
            "callback_data": data,
            "callback_query_id": cq,
            "chat_id": 42,
            "message_id": 99,
        },
    )

    await router.route_incoming(owner_cb("act:gateway:restart", "cq-step1"))
    confirm_edit = cap.edited[-1]
    confirm_cbs = [
        btn.get("callback_data")
        for row in confirm_edit["reply_markup"]["inline_keyboard"]
        for btn in row
        if btn.get("callback_data")
    ]
    assert "act:gateway:restart:confirm" in confirm_cbs
    assert "act:gateway:restart:cancel" in confirm_cbs
    assert ("cq-step1", "Confirm restart?") in cap.answered

    await router.route_incoming(owner_cb("act:gateway:restart:confirm", "cq-step2"))
    assert calls == ["gateway"]
    assert ("cq-step2", "gateway restart: ok") in cap.answered


@pytest.mark.asyncio
async def test_proxy_restart_confirm_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Owner two-step proxy restart invokes proxy-only restart helper."""
    router, cap, _root = _build_owner_router(tmp_path)
    calls: list[str] = []

    def _fake_proxy_restart() -> str:
        calls.append("proxy")
        return "proxy restart: ok"

    monkeypatch.setattr(
        "sevn.gateway.commands.menu_action_router._run_proxy_restart",
        _fake_proxy_restart,
    )

    owner_cb = lambda data, cq: IncomingMessage(  # noqa: E731
        channel="telegram",
        user_id="owner1",
        text=data,
        metadata={
            "callback_data": data,
            "callback_query_id": cq,
            "chat_id": 42,
            "message_id": 99,
        },
    )

    await router.route_incoming(owner_cb("act:proxy:restart", "cq-proxy1"))
    await router.route_incoming(owner_cb("act:proxy:restart:confirm", "cq-proxy2"))
    assert calls == ["proxy"]
    assert ("cq-proxy2", "proxy restart: ok") in cap.answered


@pytest.mark.asyncio
async def test_gateway_restart_cancel_returns_to_my_sevn_bot(tmp_path: Path) -> None:
    """Cancel on restart confirm restores the My sevn bot section keyboard."""
    router, cap, _root = _build_owner_router(tmp_path)
    owner_cb = lambda data, cq: IncomingMessage(  # noqa: E731
        channel="telegram",
        user_id="owner1",
        text=data,
        metadata={
            "callback_data": data,
            "callback_query_id": cq,
            "chat_id": 42,
            "message_id": 99,
        },
    )
    await router.route_incoming(owner_cb("cfg:section:my_sevn_bot", "cq-my"))
    await router.route_incoming(owner_cb("act:gateway:restart", "cq-prompt"))
    await router.route_incoming(owner_cb("act:gateway:restart:cancel", "cq-cancel"))
    callbacks = _my_sevn_bot_callbacks(is_owner=True)
    assert "act:gateway:restart" in callbacks
    assert ("cq-cancel", "Cancelled.") in cap.answered


def test_voice_section_includes_when_asked_button() -> None:
    """C3.3 renders TTS when_asked alongside off and all."""
    kb = build_config_menu_keyboard(_workspace(), section="voice")
    callbacks = [
        btn.get("callback_data")
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data")
    ]
    assert "cfg:voice:mode:when_asked" in callbacks
    assert "cfg:voice:mode:off" in callbacks
    assert "cfg:voice:mode:all" in callbacks


@pytest.mark.asyncio
async def test_voice_tts_mode_toggle_updates_runtime(tmp_path: Path) -> None:
    """C3.1/C3.2 toggling TTS mode refreshes ``router._voice_rt`` for outbound gating."""
    router, cap, _root = _build_router(tmp_path)
    assert router._voice_rt.tts_mode == "off"
    assert (
        router._tts.should_synthesize(
            session_tts_mode=router._voice_rt.tts_mode, user_text_last_turn=""
        )
        is False
    )
    await router.route_incoming(
        _config_callback("cfg:section:voice", callback_query_id="cq-nav"),
    )
    await router.route_incoming(
        _config_callback("cfg:voice:mode:all", callback_query_id="cq-toggle"),
    )
    assert router._voice_rt.tts_mode == "all"
    assert (
        router._tts.should_synthesize(
            session_tts_mode=router._voice_rt.tts_mode, user_text_last_turn=""
        )
        is True
    )
    assert "TTS mode: all" in cap.edited[-1]["text"]
    assert ("cq-toggle", "✅ Updated.") in cap.answered


@pytest.mark.asyncio
async def test_dm_policy_cycle_mutates_and_refreshes(tmp_path: Path) -> None:
    """C5.3 cycles DM policy open → pairing in ``sevn.json`` and caption."""
    root = tmp_path / "w"
    sevn_json = root / "sevn.json"
    router, cap, ws = _build_router(tmp_path)
    await router.route_incoming(
        _config_callback("cfg:section:channels", callback_query_id="cq-nav"),
    )
    kb = build_config_menu_keyboard(ws, section="channels")
    cycle_btn = next(
        btn
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data", "").startswith("cfg:toggle:channels.telegram.dm_policy:")
    )
    await router.route_incoming(
        _config_callback(cycle_btn["callback_data"], callback_query_id="cq-dm"),
    )
    from sevn.gateway.workspace_config_io import load_raw_sevn_json
    from sevn.onboarding.web_app import _get_nested

    doc = load_raw_sevn_json(sevn_json)
    assert _get_nested(doc, "channels.telegram.dm_policy") == "pairing"
    assert "DM policy: pairing" in cap.edited[-1]["text"]
    adapter = router._adapters["telegram"]
    from sevn.channels.telegram import DMPolicy

    assert adapter._cfg.dm_policy == DMPolicy.PAIRING
    assert ("cq-dm", "✅ Updated.") in cap.answered


def test_channels_caption_shows_telegram_mode_read_only() -> None:
    """C5.4 Telegram mode appears read-only in the Channels caption."""
    from sevn.config.workspace_config import (
        ChannelsWorkspaceSectionConfig,
        TelegramChannelConfig,
        WorkspaceConfig,
    )

    ws = WorkspaceConfig(
        schema_version=1,
        channels=ChannelsWorkspaceSectionConfig(
            telegram=TelegramChannelConfig(mode="webhook"),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    text = config_menu_message_text(ws, section="channels")
    assert "Telegram mode: webhook (read-only)" in text
    assert "Webchat TTS inline:" in text


def test_webchat_tts_inline_button_omitted_without_schema_path() -> None:
    """C5.5 omits Webchat TTS toggle when schema path is absent; caption still shows status."""
    kb = build_config_menu_keyboard(_workspace(), section="channels")
    callbacks = [
        btn.get("callback_data")
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data")
    ]
    assert not any(cb.startswith("cfg:toggle:channels.webchat.tts_inline:") for cb in callbacks)
    text = config_menu_message_text(_workspace(), section="channels")
    assert "caption-only (no schema toggle path)" in text


@pytest.mark.asyncio
async def test_notify_policy_cycle_runtime_path(tmp_path: Path) -> None:
    """C17.1 notify policy cycle persists and reloads on ``router._workspace``."""
    root = tmp_path / "w"
    sevn_json = root / "sevn.json"
    router, cap, ws = _build_router(tmp_path)
    from sevn.gateway.menu import _telegram_notify_policy
    from sevn.gateway.workspace_config_io import load_raw_sevn_json
    from sevn.onboarding.web_app import _get_nested

    assert _telegram_notify_policy(router._workspace) == "all"
    await router.route_incoming(
        _config_callback("cfg:section:notifications", callback_query_id="cq-nav"),
    )
    kb = build_config_menu_keyboard(ws, section="notifications")
    cycle_btn = next(
        btn
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data", "").startswith(
            "cfg:toggle:channels.telegram.telegram_notify_policy:",
        )
    )
    await router.route_incoming(
        _config_callback(cycle_btn["callback_data"], callback_query_id="cq-notify"),
    )
    doc = load_raw_sevn_json(sevn_json)
    assert _get_nested(doc, "channels.telegram.telegram_notify_policy") == "errors"
    assert _telegram_notify_policy(router._workspace) == "errors"
    assert "Telegram notify policy: errors" in cap.edited[-1]["text"]
    assert ("cq-notify", "✅ Updated.") in cap.answered


@pytest.mark.asyncio
async def test_reply_keyboard_toggle_updates_adapter_config(tmp_path: Path) -> None:
    """C5.1 disabling reply keyboard propagates to the Telegram adapter after reload."""
    router, cap, ws = _build_router(tmp_path)
    adapter = router._adapters["telegram"]
    assert adapter._cfg.reply_keyboard_enabled is True
    await router.route_incoming(
        _config_callback("cfg:section:channels", callback_query_id="cq-nav"),
    )
    kb = build_config_menu_keyboard(ws, section="channels")
    toggle_btn = next(
        btn
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data", "").startswith(
            "cfg:toggle:channels.telegram.reply_keyboard.enabled:false",
        )
    )
    await router.route_incoming(
        _config_callback(toggle_btn["callback_data"], callback_query_id="cq-rk"),
    )
    assert adapter._cfg.reply_keyboard_enabled is False
    assert "Reply keyboard: off" in cap.edited[-1]["text"]
    assert ("cq-rk", "✅ Updated.") in cap.answered


def test_skills_section_omits_url_without_web_ui() -> None:
    """X7/C7.1: no Skills URL button when ``web_ui.url`` is unset; caption is honest."""
    ws = _workspace()
    kb = build_config_menu_keyboard(ws, section="skills")
    buttons = [btn for row in kb["inline_keyboard"] for btn in row]
    assert not any("url" in btn for btn in buttons)
    text = config_menu_message_text(ws, section="skills")
    assert "skills.*.enabled" in text


def test_tools_section_includes_mcp_link_when_web_ui_configured() -> None:
    """C8.3 MCP dashboard link renders with Tools tab URL."""
    from sevn.config.workspace_config import WorkspaceConfig

    ws = WorkspaceConfig(
        schema_version=1,
        web_ui={"url": "https://app.example/"},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    kb = build_config_menu_keyboard(ws, section="tools")
    labels = [btn.get("text", "") for row in kb["inline_keyboard"] for btn in row]
    urls = [btn.get("url") for row in kb["inline_keyboard"] for btn in row if btn.get("url")]
    assert "🔌 MCP servers" in labels
    assert any(u and "/mission/tools-permissions" in u for u in urls)


def test_agents_section_no_advanced_fallback() -> None:
    """C19.1 removes Advanced nav loop when Mission Control URL is absent."""
    kb = build_config_menu_keyboard(_workspace(), section="agents")
    callbacks = [
        btn.get("callback_data")
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data")
    ]
    assert "cfg:section:advanced" not in callbacks
    assert "form:agent:display_name" in callbacks


@pytest.mark.asyncio
async def test_skill_toggle_mutates_sevn_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C7.2 skill enabled toggle writes ``skills.lcm.enabled`` when schema allows."""
    from sevn.config.loader import load_workspace
    from sevn.gateway.workspace_config_io import load_raw_sevn_json, mutate_sevn_json
    from sevn.onboarding.web_app import _get_nested, _set_nested

    stub_surface = ToolSet(
        registry_version=1,
        native=(),
        mcp=(),
        skill_descriptions={"lcm": "lcm — memory summaries"},
    )
    monkeypatch.setattr(
        "sevn.gateway.menu._config_menu_tool_surface",
        lambda _ws, _cr: stub_surface,
    )

    router, cap, _ws = _build_router(tmp_path)
    root = tmp_path / "w"
    sevn_json = root / "sevn.json"

    def _seed(doc: dict[str, object]) -> None:
        _set_nested(doc, "skills.lcm.enabled", True)

    mutate_sevn_json(sevn_json, _seed)
    ws, _ = load_workspace(sevn_json=sevn_json)
    router._workspace = ws
    router._config_menu_handler._workspace = ws
    router._menu_action_router._workspace = ws
    kb = build_config_menu_keyboard(ws, section="skills", content_root=root)
    toggle_btn = next(
        btn
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data", "").startswith("cfg:toggle:skills.lcm.enabled:")
    )
    await router.route_incoming(
        _config_callback(toggle_btn["callback_data"], callback_query_id="cq-skill"),
    )
    doc = load_raw_sevn_json(sevn_json)
    assert _get_nested(doc, "skills.lcm.enabled") is False
    assert ("cq-skill", "✅ Updated.") in cap.answered


@pytest.mark.asyncio
async def test_openwiki_skill_toggle_mutates_sevn_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenWiki skill toggle writes ``skills.openwiki.enabled`` when schema allows."""
    from sevn.config.loader import load_workspace
    from sevn.gateway.workspace_config_io import load_raw_sevn_json, mutate_sevn_json
    from sevn.onboarding.web_app import _get_nested, _set_nested
    from sevn.tools.registry import ToolSet

    stub_surface = ToolSet(
        registry_version=1,
        native=(),
        mcp=(),
        skill_descriptions={"openwiki": "LLM-generated agent wiki"},
    )
    monkeypatch.setattr(
        "sevn.gateway.menu._config_menu_tool_surface",
        lambda _ws, _cr: stub_surface,
    )

    router, cap, _ws = _build_router(tmp_path)
    root = tmp_path / "w"
    sevn_json = root / "sevn.json"

    def _seed(doc: dict[str, object]) -> None:
        _set_nested(doc, "skills.openwiki.enabled", False)

    mutate_sevn_json(sevn_json, _seed)
    ws, _ = load_workspace(sevn_json=sevn_json)
    router._workspace = ws
    router._config_menu_handler._workspace = ws
    router._menu_action_router._workspace = ws
    kb = build_config_menu_keyboard(ws, section="skills", content_root=root)
    toggle_btn = next(
        btn
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data", "").startswith("cfg:toggle:skills.openwiki.enabled:")
    )
    await router.route_incoming(
        _config_callback(toggle_btn["callback_data"], callback_query_id="cq-openwiki"),
    )
    doc = load_raw_sevn_json(sevn_json)
    assert _get_nested(doc, "skills.openwiki.enabled") is True
    assert ("cq-openwiki", "✅ Updated.") in cap.answered


@pytest.mark.asyncio
async def test_agent_display_name_form_updates_config(tmp_path: Path) -> None:
    """C19.2 display name wizard persists ``agent.display_name`` and refreshes caption."""
    from sevn.gateway.channel_router import IncomingMessage
    from sevn.gateway.workspace_config_io import load_raw_sevn_json
    from sevn.onboarding.web_app import _get_nested

    router, cap, root = _build_owner_router(tmp_path)
    sevn_json = root / "sevn.json"
    await router.route_incoming(
        IncomingMessage(
            channel="telegram",
            user_id="owner1",
            text="",
            metadata={
                "callback_data": "form:agent:display_name",
                "callback_query_id": "cq-form",
                "chat_id": 42,
                "message_id": 99,
            },
        ),
    )
    await router.route_incoming(
        IncomingMessage(
            channel="telegram",
            user_id="owner1",
            text="Nova",
            metadata={"chat_id": 42, "message_id": 99},
        ),
    )
    doc = load_raw_sevn_json(sevn_json)
    assert _get_nested(doc, "agent.display_name") == "Nova"
    assert any("Nova" in text for text, _md in cap.sent)


@pytest.mark.asyncio
async def test_rlm_backend_cycle_runtime(tmp_path: Path) -> None:
    """C9.2 C/D backend cycle persists and reloads on ``router._workspace``."""
    from sevn.agent.executors.cd_harness import _cd_backend
    from sevn.config.loader import load_workspace
    from sevn.gateway.menu import _rlm_c_d_backend
    from sevn.gateway.workspace_config_io import load_raw_sevn_json, mutate_sevn_json
    from sevn.onboarding.web_app import _get_nested, _set_nested

    router, cap, _ws = _build_router(tmp_path)
    sevn_json = tmp_path / "w" / "sevn.json"

    def _seed(doc: dict[str, object]) -> None:
        _set_nested(doc, "executors.tier_cd.lambda_rlm.enabled", True)
        _set_nested(doc, "rlm.c_d_backend", "lambda_rlm")
        _set_nested(doc, "rlm.lambda_tool_allowlist", ["read"])

    mutate_sevn_json(sevn_json, _seed)
    ws, _ = load_workspace(sevn_json=sevn_json)
    router._workspace = ws
    router._config_menu_handler._workspace = ws
    router._menu_action_router._workspace = ws
    assert _rlm_c_d_backend(router._workspace) == "lambda_rlm"
    await router.route_incoming(
        _config_callback("cfg:section:rlm", callback_query_id="cq-nav"),
    )
    kb = build_config_menu_keyboard(ws, section="rlm")
    cycle_btn = next(
        btn
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data", "").startswith("cfg:toggle:rlm.c_d_backend:")
    )
    await router.route_incoming(
        _config_callback(cycle_btn["callback_data"], callback_query_id="cq-backend"),
    )
    doc = load_raw_sevn_json(sevn_json)
    assert _get_nested(doc, "rlm.c_d_backend") == "dspy"
    assert _get_nested(doc, "executors.tier_cd.lambda_rlm.enabled") is False
    assert _rlm_c_d_backend(router._workspace) == "dspy"
    assert _cd_backend(router._workspace) == "dspy"
    assert "C/D backend: dspy" in cap.edited[-1]["text"]
    assert ("cq-backend", "✅ Updated.") in cap.answered


@pytest.mark.asyncio
async def test_lambda_rlm_toggle_updates_executor_gate(tmp_path: Path) -> None:
    """C9.1 λ-RLM opt-in toggle reloads harness gate on ``router._workspace``."""
    from sevn.agent.executors.cd_harness import _lambda_rlm_enabled
    from sevn.gateway.workspace_config_io import load_raw_sevn_json
    from sevn.onboarding.web_app import _get_nested

    router, cap, ws = _build_router(tmp_path)
    sevn_json = tmp_path / "w" / "sevn.json"
    assert _lambda_rlm_enabled(router._workspace) is False
    await router.route_incoming(
        _config_callback("cfg:section:rlm", callback_query_id="cq-nav"),
    )
    kb = build_config_menu_keyboard(ws, section="rlm")
    toggle_btn = next(
        btn
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data", "").startswith(
            "cfg:toggle:executors.tier_cd.lambda_rlm.enabled:true",
        )
    )
    await router.route_incoming(
        _config_callback(toggle_btn["callback_data"], callback_query_id="cq-lambda"),
    )
    doc = load_raw_sevn_json(sevn_json)
    assert _get_nested(doc, "executors.tier_cd.lambda_rlm.enabled") is True
    assert _lambda_rlm_enabled(router._workspace) is True
    assert "λ-RLM opt-in: on" in cap.edited[-1]["text"]


@pytest.mark.asyncio
async def test_security_heuristic_toggle_reloads_scanner(tmp_path: Path) -> None:
    """C11.1 heuristic-only toggle reloads ``router._scanner`` config."""
    from sevn.config.workspace_config import SecurityWorkspaceConfig
    from sevn.gateway.workspace_config_io import load_raw_sevn_json
    from sevn.onboarding.web_app import _get_nested

    router, cap, ws = _build_router(tmp_path)
    sevn_json = tmp_path / "w" / "sevn.json"
    assert router._scanner._cfg.security is not None
    assert router._scanner._cfg.security.scanner.heuristic_only is True
    await router.route_incoming(
        _config_callback("cfg:section:security", callback_query_id="cq-nav"),
    )
    kb = build_config_menu_keyboard(ws, section="security")
    toggle_btn = next(
        btn
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data", "").endswith("heuristic_only:false")
    )
    await router.route_incoming(
        _config_callback(toggle_btn["callback_data"], callback_query_id="cq-sec"),
    )
    doc = load_raw_sevn_json(sevn_json)
    assert _get_nested(doc, "security.scanner.heuristic_only") is False
    reloaded = router._scanner._cfg
    assert isinstance(reloaded.security, SecurityWorkspaceConfig)
    assert reloaded.security.scanner is not None
    assert reloaded.security.scanner.heuristic_only is False
    assert "Heuristic-only scanner: off" in cap.edited[-1]["text"]


@pytest.mark.asyncio
async def test_mycode_toggle_updates_runtime_flag(tmp_path: Path) -> None:
    """C10.1 MYCODE toggle reloads ``code_understanding.mycode.enabled``."""
    from sevn.gateway.menu import _mycode_enabled
    from sevn.gateway.workspace_config_io import load_raw_sevn_json
    from sevn.onboarding.web_app import _get_nested

    router, cap, ws = _build_router(tmp_path)
    sevn_json = tmp_path / "w" / "sevn.json"
    assert _mycode_enabled(router._workspace) is True
    await router.route_incoming(
        _config_callback("cfg:section:code", callback_query_id="cq-nav"),
    )
    kb = build_config_menu_keyboard(ws, section="code")
    toggle_btn = next(
        btn
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data", "").startswith("cfg:toggle:code_understanding.mycode.enabled:")
        and btn["callback_data"].endswith(":false")
    )
    await router.route_incoming(
        _config_callback(toggle_btn["callback_data"], callback_query_id="cq-mycode"),
    )
    doc = load_raw_sevn_json(sevn_json)
    assert _get_nested(doc, "code_understanding.mycode.enabled") is False
    assert _mycode_enabled(router._workspace) is False
    assert "MYCODE scan: off" in cap.edited[-1]["text"]


@pytest.mark.asyncio
async def test_code_review_graph_toggle_updates_mcp_gate(tmp_path: Path) -> None:
    """C10.2 review graph toggle reloads ``code_review_graph_mcp_enabled``."""
    from sevn.code_understanding.code_review_graph_mcp import code_review_graph_mcp_enabled
    from sevn.gateway.workspace_config_io import load_raw_sevn_json
    from sevn.onboarding.web_app import _get_nested

    router, cap, ws = _build_router(tmp_path)
    sevn_json = tmp_path / "w" / "sevn.json"
    assert code_review_graph_mcp_enabled(router._workspace) is False
    await router.route_incoming(
        _config_callback("cfg:section:code", callback_query_id="cq-nav"),
    )
    kb = build_config_menu_keyboard(ws, section="code")
    toggle_btn = next(
        btn
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data", "").startswith(
            "cfg:toggle:code_understanding.code_review_graph.enabled:true",
        )
    )
    await router.route_incoming(
        _config_callback(toggle_btn["callback_data"], callback_query_id="cq-crg"),
    )
    doc = load_raw_sevn_json(sevn_json)
    assert _get_nested(doc, "code_understanding.code_review_graph.enabled") is True
    assert code_review_graph_mcp_enabled(router._workspace) is False
    assert "Code review graph: on" in cap.edited[-1]["text"]


@pytest.mark.asyncio
async def test_self_improve_toggle_updates_effective_enabled(tmp_path: Path) -> None:
    """C12.1 self-improve toggle reloads ``effective_self_improve_enabled``."""
    from sevn.config.loader import load_workspace
    from sevn.gateway.workspace_config_io import load_raw_sevn_json, mutate_sevn_json
    from sevn.onboarding.web_app import _get_nested, _set_nested
    from sevn.self_improve.effective import effective_self_improve_enabled

    router, cap, _ws = _build_router(tmp_path)
    sevn_json = tmp_path / "w" / "sevn.json"
    mutate_sevn_json(sevn_json, lambda d: _set_nested(d, "self_improve.enabled", False))
    ws, _ = load_workspace(sevn_json=sevn_json)
    router._workspace = ws
    router._config_menu_handler._workspace = ws
    router._menu_action_router._workspace = ws
    assert effective_self_improve_enabled(router._workspace) is False
    await router.route_incoming(
        _config_callback("cfg:section:self_improve", callback_query_id="cq-nav"),
    )
    kb = build_config_menu_keyboard(ws, section="self_improve")
    toggle_btn = next(
        btn
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data", "").startswith("cfg:toggle:self_improve.enabled:true")
    )
    await router.route_incoming(
        _config_callback(toggle_btn["callback_data"], callback_query_id="cq-si"),
    )
    doc = load_raw_sevn_json(sevn_json)
    assert _get_nested(doc, "self_improve.enabled") is True
    assert effective_self_improve_enabled(router._workspace) is True
    assert "Enabled: on" in cap.edited[-1]["text"]


def test_wave9_section_urls_when_web_ui_configured() -> None:
    """C9.4/C10.3/C11.2/C12.2/C13.3 Mission Control deep links when ``web_ui.url`` set."""
    from sevn.config.workspace_config import WorkspaceConfig

    ws = WorkspaceConfig(
        schema_version=1,
        web_ui={"url": "https://app.example/"},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    for section, path_suffix, label in (
        ("rlm", "/mission/rlm-training", "Open RLM tab"),
        ("code", "/mission/code-understanding", "Open Code tab"),
        ("security", "/mission/security", "Open Security tab"),
        ("self_improve", "/mission/traces", "View jobs / Traces"),
        ("second_brain", "/mission/second-brain", "Open Second Brain tab"),
    ):
        kb = build_config_menu_keyboard(ws, section=section)  # type: ignore[arg-type]
        labels = [btn.get("text", "") for row in kb["inline_keyboard"] for btn in row]
        urls = [btn.get("url") for row in kb["inline_keyboard"] for btn in row if btn.get("url")]
        assert any(label in text for text in labels)
        assert any(u and path_suffix in u for u in urls), section


def test_wave9_sections_omit_urls_without_web_ui() -> None:
    """X7: Wave 9 URL buttons omitted when ``web_ui.url`` unset; captions stay honest."""
    ws = _workspace()
    for section in ("rlm", "code", "security", "self_improve", "second_brain"):
        kb = build_config_menu_keyboard(ws, section=section)  # type: ignore[arg-type]
        assert not any("url" in btn for row in kb["inline_keyboard"] for btn in row)
        text = config_menu_message_text(ws, section=section)  # type: ignore[arg-type]
        assert "web_ui.url" in text


@pytest.mark.asyncio
async def test_queue_mode_reload_after_toggle(tmp_path: Path) -> None:
    """TE-2: toggling ``gateway.queue_mode`` updates ``router._queue_mode`` without restart."""
    from sevn.gateway.menu import _gateway_queue_mode

    router, cap, _ws = _build_router(tmp_path)
    assert router._queue_mode == "cancel"
    assert _gateway_queue_mode(router._workspace) == "cancel"
    await router.route_incoming(
        _config_callback("cfg:section:session", callback_query_id="cq-nav"),
    )
    kb = build_config_menu_keyboard(router._workspace, section="session")
    toggle_btn = next(
        btn
        for row in kb["inline_keyboard"]
        for btn in row
        if str(btn.get("callback_data", "")).startswith(
            "cfg:toggle:gateway.queue_mode:",
        )
    )
    assert toggle_btn["callback_data"].endswith(":steer")
    await router.route_incoming(
        _config_callback(toggle_btn["callback_data"], callback_query_id="cq-queue"),
    )
    assert _gateway_queue_mode(router._workspace) == "steer"
    assert router._queue_mode == "steer"
    assert ("cq-queue", "✅ Updated.") in cap.answered


@pytest.mark.asyncio
async def test_regen_toggle_hides_qa_button_on_next_reply(tmp_path: Path) -> None:
    """TE-2: disabling ``show_regen`` removes Regen from the next outbound QA bar."""
    router, cap, _root = _build_owner_router(tmp_path)
    owner_cb = lambda data, cq: IncomingMessage(  # noqa: E731
        channel="telegram",
        user_id="owner1",
        text=data,
        metadata={
            "callback_data": data,
            "callback_query_id": cq,
            "chat_id": 42,
            "message_id": 99,
        },
    )
    await router.route_incoming(owner_cb("cfg:section:session", "cq-nav"))
    kb = build_config_menu_keyboard(router._workspace, section="session")
    regen_btn = next(
        btn
        for row in kb["inline_keyboard"]
        for btn in row
        if str(btn.get("callback_data", "")).endswith("show_regen:false")
    )
    await router.route_incoming(owner_cb(regen_btn["callback_data"], "cq-toggle"))
    conn = router._sessions.connection
    row = conn.execute(
        "SELECT session_id FROM gateway_sessions WHERE scope_key = ?",
        ("telegram:owner1",),
    ).fetchone()
    assert row is not None
    session_id = str(row[0])
    meta = {"chat_id": 42}
    await router.route_outgoing(
        OutgoingMessage(
            channel="telegram",
            user_id="owner1",
            text="Thinking…",
            session_id=session_id,
            metadata={**meta, GATEWAY_OUTBOUND_PHASE_KEY: "early"},
        ),
    )
    await router.route_outgoing(
        OutgoingMessage(
            channel="telegram",
            user_id="owner1",
            text="Assistant reply",
            session_id=session_id,
            metadata={**meta, GATEWAY_OUTBOUND_PHASE_KEY: "final"},
        ),
    )
    labels = _qa_labels(cap.sent[-1][1])
    assert "♻ Regen" not in labels
    assert any("👍" in label for label in labels)
