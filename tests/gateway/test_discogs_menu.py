"""Telegram ``/config → Skills → Discogs → Setup`` menu contracts (W1.10 / D18/D19/D21)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.gateway.agent_turn import build_agent_run_turn
from sevn.gateway.channel_router import ChannelRouter, IncomingMessage
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.config_io.workspace_config_io import load_raw_sevn_json
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.menu.menu import build_config_menu_keyboard
from sevn.gateway.menu.menu_registry import match_menu_button_spec
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.onboarding.web_app import _get_nested
from sevn.security.llm_guard_scanner import LLMGuardScanner
from sevn.workspace.layout import WorkspaceLayout
from tests.gateway.test_menu import _conn, _MenuCaptureTelegram, _workspace

_SECTION = "skills:discogs"
_SETUP_SECTION = "skills:discogs:setup"


def _import_discogs_menu() -> Any:
    from sevn.gateway.menu import discogs_menu as mod

    return mod


def _sevn_json_with_discogs(root: Path) -> None:
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
                    "discogs": {
                        "enabled": False,
                        "auth_method": "user_token",
                        "confirm_writes": True,
                        "database.enabled": True,
                        "marketplace.enabled": True,
                        "collection.enabled": True,
                        "wantlist.enabled": True,
                        "identity.enabled": True,
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
    _sevn_json_with_discogs(root)
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


def _callbacks_for_section(ws: Any, section: str) -> list[str]:
    kb = build_config_menu_keyboard(ws, section=section)  # type: ignore[arg-type]
    return [
        str(btn["callback_data"])
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data")
    ]


def test_skills_tile_includes_discogs_when_schema_present() -> None:
    callbacks = _callbacks_for_section(_workspace(), "skills")
    assert any("skills:discogs" in cb for cb in callbacks)


def test_discogs_keyboard_group_and_skill_toggles() -> None:
    mod = _import_discogs_menu()
    rows = mod.build_discogs_keyboard_rows(_workspace())
    callbacks = [btn["callback_data"] for row in rows for btn in row]
    assert any("skills.discogs.enabled" in cb for cb in callbacks)
    for domain in ("database", "marketplace", "collection", "wantlist", "identity"):
        assert any(f"skills.discogs.{domain}.enabled" in cb for cb in callbacks)
    assert any("skills.discogs.auth_method" in cb for cb in callbacks)
    assert any("skills.discogs.confirm_writes" in cb for cb in callbacks)
    assert "cfg:section:skills:discogs:setup" in callbacks


def test_discogs_setup_keyboard_buttons() -> None:
    mod = _import_discogs_menu()
    rows = mod.build_discogs_setup_keyboard_rows(_workspace())
    callbacks = [btn["callback_data"] for row in rows for btn in row]
    assert "form:secret_wizard:discogs.user_token" in callbacks
    assert "act:discogs:whoami" in callbacks


@pytest.mark.parametrize(
    "callback",
    [
        "cfg:section:skills:discogs",
        "cfg:section:skills:discogs:setup",
        "form:secret_wizard:discogs.user_token",
        "act:discogs:whoami",
    ],
)
def test_menu_registry_covers_discogs_callbacks(callback: str) -> None:
    spec = match_menu_button_spec(callback)
    assert spec is not None
    assert spec.implemented is True


def test_discogs_section_caption_mentions_auth() -> None:
    mod = _import_discogs_menu()
    text = mod.discogs_menu_caption(_workspace())
    assert "Discogs" in text
    assert "auth" in text.lower() or "token" in text.lower()


@pytest.mark.asyncio
async def test_user_token_wizard_sets_auth_method(tmp_path: Path) -> None:
    router, cap, _root, sevn_json = _build_router(tmp_path)
    await router.route_incoming(
        IncomingMessage(
            channel="telegram",
            user_id="owner",
            text="my-discogs-token",
            metadata={
                "callback_data": "form:secret_wizard:discogs.user_token",
                "callback_query_id": "cq-discogs-token",
                "chat_id": 42,
                "message_id": 100,
                "owner": True,
            },
        ),
    )
    await router.route_incoming(
        IncomingMessage(
            channel="telegram",
            user_id="owner",
            text="my-discogs-token",
            metadata={"chat_id": 42, "owner": True},
        ),
    )
    doc = load_raw_sevn_json(sevn_json)
    assert _get_nested(doc, "skills.discogs.auth_method") == "user_token"
    assert ("cq-discogs-token", "✅") in cap.answered or cap.sent
