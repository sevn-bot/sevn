"""Telegram Config → My sevn bot exposes ``version_id`` (D5 / W3 / #30)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

from sevn.agent.tracing.sink import NullTraceSink
from sevn.gateway.agent_turn import build_agent_run_turn
from sevn.gateway.channel_router import ChannelRouter, IncomingMessage
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.menu.menu import (
    _build_my_sevn_bot_keyboard_rows,
    build_config_menu_keyboard,
)
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.security.llm_guard_scanner import LLMGuardScanner
from sevn.workspace.layout import WorkspaceLayout
from tests.gateway.test_menu import _conn, _MenuCaptureTelegram, _workspace

# D5 allows either peer of deployment_id.
_VERSION_ID_CALLBACKS = frozenset({"cfg:logs:version_id", "cfg:my_sevn:version_id"})


def _callbacks(rows: list[list[dict[str, Any]]]) -> list[str]:
    return [btn["callback_data"] for row in rows for btn in row]


def _build_owner_router(tmp_path: Path) -> tuple[ChannelRouter, _MenuCaptureTelegram, Path]:
    root = tmp_path / "w"
    root.mkdir()
    sevn_json = root / "sevn.json"
    sevn_json.write_text(
        (
            '{"schema_version":1,"workspace_root":".",'
            '"gateway":{"host":"127.0.0.1","port":3001,"queue_mode":"cancel",'
            '"token":"${SECRET:keychain:sevn.gateway.token}"},'
            '"version_id":"tg-build-99",'
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


def _callback(
    data: str,
    *,
    user_id: str = "owner1",
    callback_query_id: str = "cq-ver",
) -> IncomingMessage:
    return IncomingMessage(
        channel="telegram",
        user_id=user_id,
        text=data,
        metadata={
            "callback_data": data,
            "callback_query_id": callback_query_id,
            "chat_id": 42,
            "message_id": 99,
        },
    )


def test_my_sevn_bot_keyboard_includes_version_id_and_deployment_id() -> None:
    """D1+D5: My sevn bot keeps Deployment id and adds a version_id row."""
    rows = _build_my_sevn_bot_keyboard_rows(_workspace(), is_owner=True)
    cbs = _callbacks(rows)
    assert "cfg:logs:deployment_id" in cbs
    assert _VERSION_ID_CALLBACKS.intersection(cbs), cbs


def test_my_sevn_bot_section_keyboard_exposes_version_id() -> None:
    """Section keyboard (gated) includes the version_id callback."""
    kb = build_config_menu_keyboard(_workspace(), section="my_sevn_bot", is_owner=True)
    cbs = [btn.get("callback_data", "") for row in kb["inline_keyboard"] for btn in row]
    assert "cfg:logs:deployment_id" in cbs
    assert _VERSION_ID_CALLBACKS.intersection(cbs), cbs


async def test_version_id_callback_toasts_current_value(tmp_path: Path) -> None:
    """Callback peer of deployment_id answers with the current ``version_id`` (D5)."""
    router, cap, _root = _build_owner_router(tmp_path)
    # Prefer router-stashed value when present (mirrors deployment_id pattern).
    router._version_id = "tg-build-99"  # type: ignore[attr-defined]

    # Probe which callback the keyboard advertises once W3 lands.
    rows = _build_my_sevn_bot_keyboard_rows(router._workspace, is_owner=True)
    cbs = set(_callbacks(rows))
    chosen = next(iter(_VERSION_ID_CALLBACKS.intersection(cbs)), "cfg:logs:version_id")

    await router.route_incoming(_callback(chosen, callback_query_id="cq-vid"))
    answers = dict(cap.answered)
    assert "cq-vid" in answers
    toast = answers["cq-vid"] or ""
    assert "tg-build-99" in toast
