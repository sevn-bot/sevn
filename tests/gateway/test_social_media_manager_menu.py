"""Telegram ``/config`` Social Media Manager menu contracts (W1.6 / D9)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.browser.recipes.social import _SUPPORTED_SITES
from sevn.gateway.agent_turn import build_agent_run_turn
from sevn.gateway.channel_router import ChannelRouter, IncomingMessage
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.config_io.workspace_config_io import load_raw_sevn_json
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.menu.menu import build_config_menu_keyboard, config_menu_message_text
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.onboarding.web_app import _get_nested
from sevn.security.llm_guard_scanner import LLMGuardScanner
from sevn.workspace.layout import WorkspaceLayout
from tests.gateway.test_menu import _conn, _MenuCaptureTelegram, _workspace

_SECTION = "skills:social_media_manager"
_CYCLE_PREFIX = "cfg:cycle:skills.social_media_manager"


def _sevn_json_with_smm(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "sevn.json").write_text(
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
                "skills": {
                    "social_media_manager": {
                        "default_medium": "browser",
                        "twexapi": {"enabled": False},
                        "platforms": {
                            site: {"medium": "browser"} for site in sorted(_SUPPORTED_SITES)
                        },
                    },
                },
                "channels": {"telegram": {"quick_actions": {"show_regen": True}}},
                "security": {"scanner": {"heuristic_only": True}},
                "providers": {
                    "use_main_model_for_all": False,
                    "tier_default": {"triager": "test/triager", "B": "test/tier-b"},
                },
            },
        ),
        encoding="utf-8",
    )


def _build_router(tmp_path: Path) -> tuple[ChannelRouter, _MenuCaptureTelegram, Path, Path]:
    root = tmp_path / "w"
    _sevn_json_with_smm(root)
    sevn_json = root / "sevn.json"
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
    return router, cap, root, sevn_json


def _config_callback(
    data: str,
    *,
    chat_id: int = 42,
    message_id: int = 99,
    callback_query_id: str = "cq-smm-1",
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


def _callbacks_for_section(ws: Any, section: str) -> list[str]:
    kb = build_config_menu_keyboard(ws, section=section)  # type: ignore[arg-type]
    return [
        str(btn["callback_data"])
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data")
    ]


def test_section_navigation_reachable() -> None:
    ws = _workspace()
    callbacks = _callbacks_for_section(ws, "skills")
    assert any("social_media_manager" in cb for cb in callbacks)


def test_caption_shows_readiness_hints() -> None:
    ws = _workspace()
    text = config_menu_message_text(ws, section=_SECTION)
    assert "default medium" in text.lower() or "Default medium" in text
    assert "TwexAPI" in text
    assert "CDP" in text or "profile" in text.lower()


@pytest.mark.parametrize("site", sorted(_SUPPORTED_SITES))
def test_per_site_cycle_callback_present(site: str) -> None:
    ws = _workspace()
    callbacks = _callbacks_for_section(ws, _SECTION)
    prefix = f"{_CYCLE_PREFIX}.platforms.{site}.medium:"
    assert any(cb.startswith(prefix) for cb in callbacks), f"missing cycle for {site}"


def test_x_cycle_values_include_twexapi() -> None:
    ws = _workspace()
    callbacks = _callbacks_for_section(ws, _SECTION)
    x_cycles = [cb for cb in callbacks if cb.startswith(f"{_CYCLE_PREFIX}.platforms.x.medium:")]
    assert x_cycles
    assert any(":twexapi" in cb or cb.endswith(":twexapi") for cb in x_cycles)


def test_facebook_cycle_excludes_twexapi() -> None:
    ws = _workspace()
    callbacks = _callbacks_for_section(ws, _SECTION)
    fb_cycles = [cb for cb in callbacks if "platforms.facebook.medium" in cb]
    assert fb_cycles
    assert not any("twexapi" in cb for cb in fb_cycles)


def test_default_medium_cycle_present() -> None:
    ws = _workspace()
    callbacks = _callbacks_for_section(ws, _SECTION)
    assert any("default_medium" in cb for cb in callbacks)


def test_twexapi_enabled_toggle_present() -> None:
    ws = _workspace()
    callbacks = _callbacks_for_section(ws, _SECTION)
    assert any("twexapi.enabled" in cb for cb in callbacks)


def test_twexapi_key_wizard_uses_secret_alias() -> None:
    ws = _workspace()
    callbacks = _callbacks_for_section(ws, _SECTION)
    assert "form:secret_wizard" in callbacks or any("SEVN_SECRET_TWEXAPI" in cb for cb in callbacks)


@pytest.mark.asyncio
async def test_x_medium_cycle_mutates_sevn_json(tmp_path: Path) -> None:
    router, cap, _root, sevn_json = _build_router(tmp_path)
    await router.route_incoming(
        _config_callback("cfg:section:skills", callback_query_id="cq-nav"),
    )
    ws = router._workspace
    kb = build_config_menu_keyboard(ws, section=_SECTION)
    cycle_btn = next(
        btn
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data", "").startswith(
            f"{_CYCLE_PREFIX}.platforms.x.medium:",
        )
    )
    await router.route_incoming(
        _config_callback(cycle_btn["callback_data"], callback_query_id="cq-x-cycle"),
    )
    doc = load_raw_sevn_json(sevn_json)
    medium = _get_nested(doc, "skills.social_media_manager.platforms.x.medium")
    assert medium in ("browser", "twexapi")
    assert ("cq-x-cycle", "✅ Updated.") in cap.answered
