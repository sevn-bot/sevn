"""Wave TMC-1 ``/config`` navigation via ``ConfigMenuHandler`` (not action router)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.gateway.agent_turn import build_agent_run_turn
from sevn.gateway.channel_router import ChannelRouter, IncomingMessage
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.commands.menu_action_router import parse_action_callback
from sevn.gateway.config_io.workspace_config_io import load_raw_sevn_json
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.menu.menu import build_config_menu_keyboard
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.onboarding.web_app import _get_nested
from sevn.security.llm_guard_scanner import LLMGuardScanner
from sevn.workspace.layout import WorkspaceLayout
from tests.gateway.test_menu import _conn, _MenuCaptureTelegram, _workspace

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig


def _config_section_callbacks(
    ws: WorkspaceConfig,
    section: str,
    **kwargs: Any,
) -> list[str]:
    """Return ``callback_data`` values from ungated ``build_config_menu_keyboard``."""
    kb = build_config_menu_keyboard(ws, section=section, **kwargs)  # type: ignore[arg-type]
    return [
        str(btn["callback_data"])
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data")
    ]


def _build_router(tmp_path: Path) -> tuple[ChannelRouter, _MenuCaptureTelegram, WorkspaceConfig]:
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
    )
    router.register_adapter(cap)
    build_agent_run_turn(
        router,
        conn,
        ws,
        WorkspaceLayout(sevn_json, root),
        NullTraceSink(),
    )
    return router, cap, ws


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


@pytest.mark.asyncio
async def test_section_navigation_edits_message(tmp_path: Path) -> None:
    router, cap, _ws = _build_router(tmp_path)
    await router.route_incoming(_config_callback("cfg:section:voice"))
    assert cap.answered == [("cq-config-1", None)]
    assert len(cap.edited) == 1
    assert cap.edited[0]["message_id"] == 99
    assert "Voice" in cap.edited[0]["text"]
    assert cap.edited[0]["reply_markup"]["inline_keyboard"]
    assert cap.sent == []


@pytest.mark.asyncio
async def test_nav_back_returns_previous_section(tmp_path: Path) -> None:
    router, cap, _ws = _build_router(tmp_path)
    await router.route_incoming(_config_callback("cfg:section:voice", callback_query_id="cq1"))
    await router.route_incoming(
        _config_callback("cfg:nav:back", callback_query_id="cq2"),
    )
    assert len(cap.edited) == 2
    assert "Voice" in cap.edited[0]["text"]
    assert cap.edited[1]["text"] == "sevn — /config"
    assert cap.sent == []


@pytest.mark.asyncio
async def test_nav_home_returns_root(tmp_path: Path) -> None:
    router, cap, _ws = _build_router(tmp_path)
    await router.route_incoming(_config_callback("cfg:section:voice", callback_query_id="cq1"))
    await router.route_incoming(
        _config_callback("cfg:nav:home", callback_query_id="cq2"),
    )
    assert len(cap.edited) == 2
    assert "Voice" in cap.edited[0]["text"]
    assert cap.edited[1]["text"] == "sevn — /config"
    assert cap.sent == []


@pytest.mark.asyncio
async def test_nav_close_clears_markup(tmp_path: Path) -> None:
    router, cap, _ws = _build_router(tmp_path)
    await router.route_incoming(_config_callback("cfg:nav:close"))
    assert cap.answered == [("cq-config-1", None)]
    assert len(cap.edited) == 1
    assert cap.edited[0]["reply_markup"] == {"inline_keyboard": []}
    assert cap.sent == []


@pytest.mark.asyncio
async def test_voice_toggle_updates_caption_in_place(tmp_path: Path) -> None:
    router, cap, _ws = _build_router(tmp_path)
    await router.route_incoming(
        _config_callback("cfg:section:voice", callback_query_id="cq-nav"),
    )
    await router.route_incoming(
        _config_callback("cfg:voice:mode:all", callback_query_id="cq-toggle"),
    )
    assert len(cap.edited) >= 2
    toggle_edit = cap.edited[-1]
    assert toggle_edit["message_id"] == 99
    assert "TTS mode: all" in toggle_edit["text"]
    kb = build_config_menu_keyboard(router._workspace, section="voice")
    tts_labels = [
        btn["text"]
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("text", "").startswith("TTS:")
    ]
    assert any("all ✅" in label for label in tts_labels)
    assert toggle_edit["reply_markup"]["inline_keyboard"]
    assert ("cq-toggle", "✅ Updated.") in cap.answered
    assert cap.sent == []


@pytest.mark.asyncio
async def test_models_section_navigation(tmp_path: Path) -> None:
    router, cap, _ws = _build_router(tmp_path)
    await router.route_incoming(_config_callback("cfg:section:models"))
    assert len(cap.edited) == 1
    assert "Models" in cap.edited[0]["text"]
    assert "Triager:" in cap.edited[0]["text"]
    assert "Tier B:" in cap.edited[0]["text"]
    callbacks = _config_section_callbacks(router._workspace, "models")
    assert any(cb.startswith("cfg:toggle:providers.use_main_model_for_all:") for cb in callbacks)


@pytest.mark.asyncio
async def test_models_toggle_updates_caption_in_place(tmp_path: Path) -> None:
    root = tmp_path / "w"
    sevn_json = root / "sevn.json"
    router, cap, ws = _build_router(tmp_path)
    await router.route_incoming(
        _config_callback("cfg:section:models", callback_query_id="cq-nav"),
    )
    kb = build_config_menu_keyboard(ws, section="models")
    toggle_btn = next(
        btn
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data", "").startswith(
            "cfg:toggle:providers.use_main_model_for_all:true"
        )
    )
    await router.route_incoming(
        _config_callback(toggle_btn["callback_data"], callback_query_id="cq-toggle"),
    )
    doc = load_raw_sevn_json(sevn_json)
    assert _get_nested(doc, "providers.use_main_model_for_all") is True
    toggle_edit = cap.edited[-1]
    assert "Unified model: on" in toggle_edit["text"]
    unified_labels = [
        btn["text"]
        for row in toggle_edit["reply_markup"]["inline_keyboard"]
        for btn in row
        if "Unified model" in btn.get("text", "")
    ]
    assert any("✅" in label for label in unified_labels)
    assert ("cq-toggle", "✅ Updated.") in cap.answered


@pytest.mark.asyncio
async def test_security_section_navigation(tmp_path: Path) -> None:
    router, cap, _ws = _build_router(tmp_path)
    await router.route_incoming(_config_callback("cfg:section:security"))
    assert len(cap.edited) == 1
    assert "Security" in cap.edited[0]["text"]
    assert "Heuristic-only scanner:" in cap.edited[0]["text"]
    callbacks = _config_section_callbacks(router._workspace, "security")
    assert any(cb.startswith("cfg:toggle:security.scanner.heuristic_only:") for cb in callbacks)


@pytest.mark.asyncio
async def test_security_toggle_updates_caption_in_place(tmp_path: Path) -> None:
    root = tmp_path / "w"
    sevn_json = root / "sevn.json"
    router, cap, ws = _build_router(tmp_path)
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
        _config_callback(toggle_btn["callback_data"], callback_query_id="cq-toggle"),
    )
    doc = load_raw_sevn_json(sevn_json)
    assert _get_nested(doc, "security.scanner.heuristic_only") is False
    toggle_edit = cap.edited[-1]
    assert "Heuristic-only scanner: off" in toggle_edit["text"]
    heuristic_labels = [
        btn["text"]
        for row in toggle_edit["reply_markup"]["inline_keyboard"]
        for btn in row
        if "Heuristic-only" in btn.get("text", "")
    ]
    assert any("off" in label for label in heuristic_labels)
    assert ("cq-toggle", "✅ Updated.") in cap.answered


@pytest.mark.asyncio
async def test_help_section_navigation(tmp_path: Path) -> None:
    from sevn.gateway.menu.menu_readiness import config_menu_help_catalog_text

    router, cap, _ws = _build_router(tmp_path)
    await router.route_incoming(_config_callback("cfg:section:help"))
    assert len(cap.edited) == 1
    assert "Help" in cap.edited[0]["text"]
    assert "/config" in cap.edited[0]["text"]
    catalog = config_menu_help_catalog_text()
    assert "/status" in catalog
    assert "/stop" in catalog
    callbacks = [
        btn.get("callback_data")
        for row in cap.edited[0]["reply_markup"]["inline_keyboard"]
        for btn in row
        if "callback_data" in btn
    ]
    assert all(str(cb).startswith("cfg:nav:") for cb in callbacks)


@pytest.mark.asyncio
async def test_session_toggle_mutates_sevn_json(tmp_path: Path) -> None:
    root = tmp_path / "w"
    sevn_json = root / "sevn.json"
    router, cap, ws = _build_router(tmp_path)
    await router.route_incoming(
        _config_callback("cfg:section:session", callback_query_id="cq-nav"),
    )
    kb = build_config_menu_keyboard(ws, section="session")
    regen_btn = next(
        btn
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data", "").endswith("show_regen:false")
    )
    await router.route_incoming(
        _config_callback(regen_btn["callback_data"], callback_query_id="cq-toggle"),
    )
    doc = load_raw_sevn_json(sevn_json)
    assert _get_nested(doc, "channels.telegram.quick_actions.show_regen") is False
    toggle_edit = cap.edited[-1]
    assert "Regen: off" in toggle_edit["text"]
    regen_labels = [
        btn["text"]
        for row in toggle_edit["reply_markup"]["inline_keyboard"]
        for btn in row
        if "Regen" in btn.get("text", "")
    ]
    assert any("off" in label for label in regen_labels)
    assert ("cq-toggle", "✅ Updated.") in cap.answered


@pytest.mark.asyncio
async def test_session_toggle_refresh_uses_forum_general_thread_id(tmp_path: Path) -> None:
    """Toggle refresh must pass ``message_thread_id=1`` when ``topic_id`` is normalized away."""
    root = tmp_path / "w"
    sevn_json = root / "sevn.json"
    router, cap, ws = _build_router(tmp_path)
    await router.route_incoming(
        _config_callback(
            "cfg:section:session",
            callback_query_id="cq-nav",
            metadata_extra={"telegram_thread_id": 1, "topic_id": None},
        ),
    )
    kb = build_config_menu_keyboard(ws, section="session")
    regen_btn = next(
        btn
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data", "").endswith("show_regen:false")
    )
    await router.route_incoming(
        _config_callback(
            regen_btn["callback_data"],
            callback_query_id="cq-toggle",
            metadata_extra={"telegram_thread_id": 1, "topic_id": None},
        ),
    )
    doc = load_raw_sevn_json(sevn_json)
    assert _get_nested(doc, "channels.telegram.quick_actions.show_regen") is False
    toggle_edit = cap.edited[-1]
    assert toggle_edit["message_thread_id"] == 1
    assert "Regen: off" in toggle_edit["text"]
    assert ("cq-toggle", "✅ Updated.") in cap.answered


@pytest.mark.asyncio
async def test_dashboard_refresh_pin_schedules_edit(tmp_path: Path) -> None:
    router, cap, _ws = _build_router(tmp_path)
    publisher = AsyncMock()
    publisher.schedule_render = AsyncMock()
    router._dashboard_pin_publisher = publisher
    router._telegram_dashboard_pins = {"42:0": 1001}
    assert parse_action_callback("cfg:dashboard:refresh_pin") == (
        "action",
        "dashboard:refresh_pin",
        None,
    )
    await router.route_incoming(
        _config_callback("cfg:dashboard:refresh_pin", callback_query_id="cq-pin"),
    )
    publisher.schedule_render.assert_awaited_once()
    call_kw = publisher.schedule_render.await_args.kwargs
    assert call_kw["chat_id"] == 42
    assert call_kw["message_id"] == 1001
    assert ("cq-pin", "Pin refresh scheduled.") in cap.answered


@pytest.mark.asyncio
async def test_shortcut_delete_round_trip(tmp_path: Path) -> None:
    from sevn.gateway.commands.shortcuts_store import add_shortcut, load_shortcuts

    root = tmp_path / "w"
    router, cap, _ws = _build_router(tmp_path)
    add_shortcut(
        root,
        {"name": "standup", "description": "Daily", "type": "prompt", "payload": {}},
    )
    adapter = router._adapters["telegram"]
    adapter._flush_set_my_commands = AsyncMock()
    await router.route_incoming(
        _config_callback("cfg:section:shortcuts", callback_query_id="cq-nav"),
    )
    assert "standup" in cap.edited[-1]["text"]
    root = tmp_path / "w"
    delete_cb = next(
        cb
        for cb in _config_section_callbacks(
            router._workspace,
            "shortcuts",
            content_root=root,
            user_id="u1",
        )
        if cb.startswith("act:shortcut_delete:")
    )
    await router.route_incoming(
        _config_callback(delete_cb, callback_query_id="cq-del"),
    )
    assert load_shortcuts(root) == []
    adapter._flush_set_my_commands.assert_awaited_once()
    assert "standup" not in cap.edited[-1]["text"]
    assert ("cq-del", "Deleted.") in cap.answered


@pytest.mark.asyncio
async def test_dashboard_section_navigation(tmp_path: Path) -> None:
    from sevn.config.loader import load_workspace
    from sevn.gateway.config_io.workspace_config_io import mutate_sevn_json
    from sevn.onboarding.web_app import _set_nested

    router, cap, _ws = _build_router(tmp_path)
    root = tmp_path / "w"
    sevn_json = root / "sevn.json"
    mutate_sevn_json(sevn_json, lambda d: _set_nested(d, "web_ui.url", "https://app.example/"))
    ws, _ = load_workspace(sevn_json=sevn_json)
    router._workspace = ws
    router._config_menu_handler._workspace = ws
    await router.route_incoming(_config_callback("cfg:section:dashboard"))
    assert len(cap.edited) == 1
    assert "Dashboard" in cap.edited[0]["text"]
    callbacks = _config_section_callbacks(ws, "dashboard")
    assert "cfg:dashboard:create_pin" in callbacks
    assert "cfg:dashboard:refresh_pin" in callbacks
    assert "cfg:dashboard:unpin" in callbacks
    buttons = [btn for row in cap.edited[0]["reply_markup"]["inline_keyboard"] for btn in row]
    assert any(btn.get("url") == "https://app.example/" for btn in buttons)


@pytest.mark.asyncio
async def test_shortcuts_section_navigation(tmp_path: Path) -> None:
    from sevn.gateway.commands.shortcuts_store import add_shortcut

    root = tmp_path / "w"
    router, cap, _ws = _build_router(tmp_path)
    add_shortcut(
        root,
        {"name": "daily", "description": "Daily note", "type": "prompt", "payload": {}},
    )
    await router.route_incoming(_config_callback("cfg:section:shortcuts"))
    assert len(cap.edited) == 1
    assert "daily" in cap.edited[0]["text"]
    callbacks = _config_section_callbacks(
        router._workspace,
        "shortcuts",
        content_root=root,
        user_id="u1",
    )
    assert "form:shortcut_add" in callbacks
    assert "act:shortcut_delete:daily" in callbacks
    assert parse_action_callback("cfg:section:shortcuts") is None


_WAVE7_SECTIONS = frozenset({"agents", "skills", "tools", "rlm", "code"})
_WAVE8_SECTIONS = frozenset({"secrets", "self_improve", "second_brain", "integrations"})

_ALL_CONFIG_SECTIONS: tuple[str, ...] = (
    "session",
    "agents",
    "models",
    "voice",
    "channels",
    "secrets",
    "skills",
    "tools",
    "code",
    "security",
    "integrations",
    "dashboard",
    "shortcuts",
    "notifications",
    "advanced",
    "help",
)


def _keyboard_buttons(edit: dict[str, Any]) -> list[dict[str, Any]]:
    return [btn for row in edit["reply_markup"]["inline_keyboard"] for btn in row]


@pytest.mark.asyncio
async def test_all_root_sections_navigate(tmp_path: Path) -> None:
    router, cap, _ws = _build_router(tmp_path)
    for idx, section in enumerate(_ALL_CONFIG_SECTIONS):
        await router.route_incoming(
            _config_callback(f"cfg:section:{section}", callback_query_id=f"cq-{idx}"),
        )
        edit = cap.edited[-1]
        title = section.replace("_", " ").title()
        assert title in edit["text"] or section == "help"
        buttons = _keyboard_buttons(edit)
        assert buttons
        if section in _WAVE7_SECTIONS or section in _WAVE8_SECTIONS:
            assert not any(btn.get("text") == "Coming soon" for btn in buttons)
        assert parse_action_callback(f"cfg:section:{section}") is None


@pytest.mark.asyncio
async def test_rlm_toggle_updates_caption_in_place(tmp_path: Path) -> None:
    root = tmp_path / "w"
    sevn_json = root / "sevn.json"
    router, cap, ws = _build_router(tmp_path)
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
        _config_callback(toggle_btn["callback_data"], callback_query_id="cq-toggle"),
    )
    doc = load_raw_sevn_json(sevn_json)
    assert _get_nested(doc, "executors.tier_cd.lambda_rlm.enabled") is True
    toggle_edit = cap.edited[-1]
    assert "λ-RLM opt-in: on" in toggle_edit["text"]
    assert ("cq-toggle", "✅ Updated.") in cap.answered


@pytest.mark.asyncio
async def test_code_review_graph_toggle_updates_caption_in_place(tmp_path: Path) -> None:
    root = tmp_path / "w"
    sevn_json = root / "sevn.json"
    router, cap, ws = _build_router(tmp_path)
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
        _config_callback(toggle_btn["callback_data"], callback_query_id="cq-toggle"),
    )
    doc = load_raw_sevn_json(sevn_json)
    assert _get_nested(doc, "code_understanding.code_review_graph.enabled") is True
    toggle_edit = cap.edited[-1]
    assert "Code review graph: on" in toggle_edit["text"]
    assert ("cq-toggle", "✅ Updated.") in cap.answered


@pytest.mark.asyncio
async def test_channels_section_navigation(tmp_path: Path) -> None:
    router, cap, _ws = _build_router(tmp_path)
    await router.route_incoming(_config_callback("cfg:section:channels"))
    assert len(cap.edited) == 1
    assert "Channels" in cap.edited[0]["text"]
    assert "DM policy:" in cap.edited[0]["text"]
    assert "Telegram mode:" in cap.edited[0]["text"]
    assert "(read-only)" in cap.edited[0]["text"]
    callbacks = _config_section_callbacks(router._workspace, "channels")
    assert any(
        cb.startswith("cfg:toggle:channels.telegram.reply_keyboard.enabled:") for cb in callbacks
    )
    assert any(cb.startswith("cfg:toggle:channels.telegram.show_routing:") for cb in callbacks)
    assert any(cb.startswith("cfg:toggle:channels.telegram.dm_policy:") for cb in callbacks)
    assert parse_action_callback("cfg:section:channels") is None


@pytest.mark.asyncio
async def test_show_routing_toggle_mutates_and_refreshes(tmp_path: Path) -> None:
    root = tmp_path / "w"
    sevn_json = root / "sevn.json"
    router, cap, ws = _build_router(tmp_path)
    await router.route_incoming(
        _config_callback("cfg:section:channels", callback_query_id="cq-nav"),
    )
    kb = build_config_menu_keyboard(ws, section="channels")
    toggle_btn = next(
        btn
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data", "").startswith("cfg:toggle:channels.telegram.show_routing:true")
    )
    await router.route_incoming(
        _config_callback(toggle_btn["callback_data"], callback_query_id="cq-toggle"),
    )
    doc = load_raw_sevn_json(sevn_json)
    assert _get_nested(doc, "channels.telegram.show_routing") is True
    toggle_edit = cap.edited[-1]
    assert "Show routing footer: on" in toggle_edit["text"]
    routing_labels = [
        btn["text"]
        for row in toggle_edit["reply_markup"]["inline_keyboard"]
        for btn in row
        if "Show routing" in btn.get("text", "")
    ]
    assert any("✅" in label for label in routing_labels)
    assert ("cq-toggle", "✅ Updated.") in cap.answered


@pytest.mark.asyncio
async def test_notifications_section_navigation(tmp_path: Path) -> None:
    router, cap, _ws = _build_router(tmp_path)
    await router.route_incoming(_config_callback("cfg:section:notifications"))
    assert len(cap.edited) == 1
    assert "Notifications" in cap.edited[0]["text"]
    assert "Telegram notify policy:" in cap.edited[0]["text"]
    callbacks = _config_section_callbacks(router._workspace, "notifications")
    assert any(
        cb.startswith("cfg:toggle:channels.telegram.telegram_notify_policy:") for cb in callbacks
    )


@pytest.mark.asyncio
async def test_notifications_policy_cycle_mutates_and_refreshes(tmp_path: Path) -> None:
    root = tmp_path / "w"
    sevn_json = root / "sevn.json"
    router, cap, ws = _build_router(tmp_path)
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
        _config_callback(cycle_btn["callback_data"], callback_query_id="cq-cycle"),
    )
    doc = load_raw_sevn_json(sevn_json)
    assert _get_nested(doc, "channels.telegram.telegram_notify_policy") == "errors"
    toggle_edit = cap.edited[-1]
    assert "Telegram notify policy: errors" in toggle_edit["text"]
    assert ("cq-cycle", "✅ Updated.") in cap.answered


@pytest.mark.asyncio
async def test_advanced_section_navigation(tmp_path: Path) -> None:
    from sevn.config.loader import load_workspace
    from sevn.gateway.config_io.workspace_config_io import mutate_sevn_json
    from sevn.onboarding.web_app import _set_nested

    router, cap, _ws = _build_router(tmp_path)
    root = tmp_path / "w"
    sevn_json = root / "sevn.json"
    mutate_sevn_json(sevn_json, lambda d: _set_nested(d, "web_ui.url", "https://app.example/"))
    ws, _ = load_workspace(sevn_json=sevn_json)
    router._workspace = ws
    router._config_menu_handler._workspace = ws
    await router.route_incoming(_config_callback("cfg:section:advanced"))
    assert len(cap.edited) == 1
    assert "Advanced" in cap.edited[0]["text"]
    assert "Auto-resume tier B" in cap.edited[0]["text"]
    assert "Trace redaction:" in cap.edited[0]["text"]
    callbacks = _config_section_callbacks(ws, "advanced")
    assert any(cb.startswith("cfg:toggle:gateway.restart.auto_resume_b:") for cb in callbacks)
    assert any(cb.startswith("cfg:toggle:tracing.redaction.enabled:") for cb in callbacks)
    assert "cfg:section:rlm" in callbacks
    assert "cfg:section:self_improve" in callbacks
    assert "cfg:section:second_brain" in callbacks
    assert "cfg:section:codemode" in callbacks
    buttons = [btn for row in cap.edited[0]["reply_markup"]["inline_keyboard"] for btn in row]
    assert any(btn.get("url") == "https://app.example/" for btn in buttons)


@pytest.mark.asyncio
async def test_codemode_toggle_updates_caption_in_place(tmp_path: Path) -> None:
    root = tmp_path / "w"
    sevn_json = root / "sevn.json"
    router, cap, ws = _build_router(tmp_path)
    await router.route_incoming(
        _config_callback("cfg:section:codemode", callback_query_id="cq-nav"),
    )
    kb = build_config_menu_keyboard(ws, section="codemode")
    toggle_btn = next(
        btn
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data", "").startswith("cfg:toggle:agent.codemode.enabled:true")
    )
    await router.route_incoming(
        _config_callback(toggle_btn["callback_data"], callback_query_id="cq-toggle"),
    )
    doc = load_raw_sevn_json(sevn_json)
    assert _get_nested(doc, "agent.codemode.enabled") is True
    toggle_edit = cap.edited[-1]
    assert "Tier-B CodeMode: on" in toggle_edit["text"]
    assert ("cq-toggle", "✅ Updated.") in cap.answered


@pytest.mark.asyncio
async def test_advanced_auto_resume_toggle_mutates_and_refreshes(tmp_path: Path) -> None:
    root = tmp_path / "w"
    sevn_json = root / "sevn.json"
    router, cap, ws = _build_router(tmp_path)
    await router.route_incoming(
        _config_callback("cfg:section:advanced", callback_query_id="cq-nav"),
    )
    kb = build_config_menu_keyboard(ws, section="advanced")
    toggle_btn = next(
        btn
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data", "").startswith("cfg:toggle:gateway.restart.auto_resume_b:true")
    )
    await router.route_incoming(
        _config_callback(toggle_btn["callback_data"], callback_query_id="cq-toggle"),
    )
    doc = load_raw_sevn_json(sevn_json)
    assert _get_nested(doc, "gateway.restart.auto_resume_b") is True
    toggle_edit = cap.edited[-1]
    assert "Auto-resume tier B on restart: on" in toggle_edit["text"]
    assert ("cq-toggle", "✅ Updated.") in cap.answered


@pytest.mark.asyncio
async def test_secrets_section_navigation(tmp_path: Path) -> None:
    router, cap, _ws = _build_router(tmp_path)
    await router.route_incoming(_config_callback("cfg:section:secrets"))
    assert len(cap.edited) == 1
    assert "Secrets" in cap.edited[0]["text"]
    assert "Configured secret refs:" in cap.edited[0]["text"]
    callbacks = _config_section_callbacks(router._workspace, "secrets")
    assert "form:secret_wizard" in callbacks
    assert parse_action_callback("form:secret_wizard") == ("form", "secret_wizard", None)


@pytest.mark.asyncio
async def test_self_improve_toggle_updates_caption_in_place(tmp_path: Path) -> None:
    root = tmp_path / "w"
    sevn_json = root / "sevn.json"
    router, cap, ws = _build_router(tmp_path)
    await router.route_incoming(
        _config_callback("cfg:section:self_improve", callback_query_id="cq-nav"),
    )
    kb = build_config_menu_keyboard(ws, section="self_improve")
    toggle_btn = next(
        btn
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data", "").startswith("cfg:toggle:self_improve.enabled:false")
    )
    await router.route_incoming(
        _config_callback(toggle_btn["callback_data"], callback_query_id="cq-toggle"),
    )
    doc = load_raw_sevn_json(sevn_json)
    assert _get_nested(doc, "self_improve.enabled") is False
    toggle_edit = cap.edited[-1]
    assert "Enabled: off" in toggle_edit["text"]
    assert ("cq-toggle", "✅ Updated.") in cap.answered


@pytest.mark.asyncio
async def test_second_brain_toggle_updates_caption_in_place(tmp_path: Path) -> None:
    root = tmp_path / "w"
    sevn_json = root / "sevn.json"
    router, cap, ws = _build_router(tmp_path)
    await router.route_incoming(
        _config_callback("cfg:section:second_brain", callback_query_id="cq-nav"),
    )
    kb = build_config_menu_keyboard(ws, section="second_brain")
    toggle_btn = next(
        btn
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data", "").startswith("cfg:toggle:second_brain.enabled:false")
    )
    await router.route_incoming(
        _config_callback(toggle_btn["callback_data"], callback_query_id="cq-toggle"),
    )
    doc = load_raw_sevn_json(sevn_json)
    assert _get_nested(doc, "second_brain.enabled") is False
    toggle_edit = cap.edited[-1]
    assert "Enabled: off" in toggle_edit["text"]
    assert ("cq-toggle", "✅ Updated.") in cap.answered


@pytest.mark.asyncio
async def test_integrations_section_lists_ids_and_dashboard_link(tmp_path: Path) -> None:
    from sevn.config.loader import load_workspace
    from sevn.gateway.config_io.workspace_config_io import mutate_sevn_json
    from sevn.gateway.menu.menu import _mission_control_url
    from sevn.onboarding.web_app import _set_nested

    router, cap, _ws = _build_router(tmp_path)
    root = tmp_path / "w"
    sevn_json = root / "sevn.json"

    def _patch_integrations(doc: dict[str, object]) -> None:
        _set_nested(doc, "web_ui.url", "https://app.example/")
        _set_nested(doc, "skills.cursor_cloud.enabled", True)

    mutate_sevn_json(sevn_json, _patch_integrations)
    ws, _ = load_workspace(sevn_json=sevn_json)
    router._workspace = ws
    router._config_menu_handler._workspace = ws
    router._menu_action_router._workspace = ws
    expected_url = _mission_control_url(ws, fragment="integrations")
    assert expected_url is not None
    await router.route_incoming(_config_callback("cfg:section:integrations"))
    assert len(cap.edited) == 1
    assert "Integrations" in cap.edited[0]["text"]
    assert "cursor" in cap.edited[0]["text"]
    assert expected_url in cap.edited[0]["text"]
    buttons = [btn for row in cap.edited[0]["reply_markup"]["inline_keyboard"] for btn in row]
    assert any(btn.get("url") == expected_url for btn in buttons)
