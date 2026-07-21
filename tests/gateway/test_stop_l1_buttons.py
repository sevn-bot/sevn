"""RED suite for ``/stop`` L1 picker + D8 empty path (plan D7-D9 / D11 / #27 / W5)."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from sevn.agent.subagents.registry import SubAgentRegistry
from sevn.agent.subagents.supervisor import SubAgentSpec, SubAgentSupervisor
from sevn.agent.tracing.sink import NullTraceSink
from sevn.config.sections.subagents import SubAgentsWorkspaceConfig
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.agent_turn import build_agent_run_turn
from sevn.gateway.channel_router import ChannelRouter, IncomingMessage
from sevn.gateway.commands.core_commands import CoreCommandHandler
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.commands.menu_action_router import MenuActionRouter
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.security.llm_guard_scanner import LLMGuardScanner
from sevn.workspace.layout import WorkspaceLayout
from tests.gateway.test_menu import _conn, _MenuCaptureTelegram, _workspace

_STOPPED = "Stopped."


def _layout(tmp_path: Path) -> WorkspaceLayout:
    root = tmp_path / "w"
    root.mkdir(exist_ok=True)
    sevn_json = root / "sevn.json"
    if not sevn_json.exists():
        sevn_json.write_text(
            (
                '{"schema_version":1,"workspace_root":".",'
                '"gateway":{"token":"${SECRET:keychain:sevn.gateway.token}"},'
                '"subagents":{"enabled":true}}'
            ),
            encoding="utf-8",
        )
    return WorkspaceLayout(sevn_json, root)


def _reply_text(reply: Any) -> str:
    if isinstance(reply, str):
        return reply
    text = getattr(reply, "text", None)
    assert isinstance(text, str)
    return text


def _reply_markup(reply: Any) -> dict[str, Any] | None:
    if isinstance(reply, str) or reply is None:
        return None
    markup = getattr(reply, "reply_markup", None)
    return markup if isinstance(markup, dict) else None


def _markup_callbacks(markup: dict[str, Any]) -> list[str]:
    rows = markup.get("inline_keyboard")
    if not isinstance(rows, list):
        return []
    out: list[str] = []
    for row in rows:
        if not isinstance(row, list):
            continue
        for btn in row:
            if isinstance(btn, dict) and btn.get("callback_data"):
                out.append(str(btn["callback_data"]))
    return out


async def _spawn_l1(
    supervisor: SubAgentSupervisor,
    *,
    summary: str = "stop-me",
    role: str = "tier_b",
) -> str:
    async def _work() -> None:
        await asyncio.sleep(120)

    handle = await supervisor.spawn(
        SubAgentSpec(
            level=1,
            role=role,
            body=_work,
            session_id="s-stop",
            channel="telegram",
            task_summary=summary,
        ),
    )
    return handle.id


# --- D8: no L1 → session cancel (already live; regression lock, not xfail) ---


@pytest.mark.asyncio
async def test_stop_no_l1_cancels_dispatch_and_returns_stopped(tmp_path: Path) -> None:
    """D8: always ``cancel_active_dispatch`` then ``\"Stopped.\"`` when no L1s."""
    layout = _layout(tmp_path)
    ws = WorkspaceConfig.minimal()
    conn = _conn()
    sessions = SessionManager(conn)
    cancel_calls: list[str] = []

    async def _track_cancel(session_id: str) -> bool:
        cancel_calls.append(session_id)
        return False  # no-op cancel still yields Stopped.

    sessions.cancel_active_dispatch = _track_cancel  # type: ignore[method-assign]
    router = ChannelRouter.__new__(ChannelRouter)
    router._subagent_supervisor = SubAgentSupervisor(
        registry=SubAgentRegistry(),
        config=SubAgentsWorkspaceConfig(),
    )
    handler = CoreCommandHandler(
        workspace=ws,
        layout=layout,
        router=router,  # type: ignore[arg-type]
        sessions=sessions,
    )
    reply = await handler.handle(
        IncomingMessage(channel="telegram", user_id="1", text="/stop"),
        session_id="sess-empty",
    )
    assert _reply_text(reply) == _STOPPED
    assert cancel_calls == ["sess-empty"]
    markup = _reply_markup(reply)
    assert markup is None or not _markup_callbacks(markup)


@pytest.mark.asyncio
async def test_stop_no_l1_via_handle_returns_stopped(tmp_path: Path) -> None:
    """D8 via ``handle('/stop')`` — confirmation copy locked by W0."""
    layout = _layout(tmp_path)
    ws = WorkspaceConfig.minimal()
    conn = _conn()
    sessions = SessionManager(conn)
    router = ChannelRouter.__new__(ChannelRouter)
    router._subagent_supervisor = SubAgentSupervisor(
        registry=SubAgentRegistry(),
        config=SubAgentsWorkspaceConfig(),
    )
    handler = CoreCommandHandler(
        workspace=ws,
        layout=layout,
        router=router,  # type: ignore[arg-type]
        sessions=sessions,
    )
    reply = await handler.handle(
        IncomingMessage(channel="telegram", user_id="1", text="/stop"),
        session_id="sess-2",
    )
    assert _reply_text(reply) == _STOPPED


# --- D7/D11: L1 picker ---


@pytest.mark.asyncio
async def test_stop_with_l1_offers_per_id_and_all_buttons(tmp_path: Path) -> None:
    """D7: ≥1 L1 → do not auto-kill; inline buttons per L1 + ALL."""
    layout = _layout(tmp_path)
    ws = WorkspaceConfig.minimal(subagents=SubAgentsWorkspaceConfig(enabled=True))
    conn = _conn()
    sessions = SessionManager(conn)
    cancel_calls: list[str] = []

    async def _track_cancel(session_id: str) -> bool:
        cancel_calls.append(session_id)
        return True

    sessions.cancel_active_dispatch = _track_cancel  # type: ignore[method-assign]
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry=registry, config=SubAgentsWorkspaceConfig())
    router = ChannelRouter.__new__(ChannelRouter)
    router._subagent_supervisor = supervisor
    router._resolve_owner_flag = lambda _msg: True  # type: ignore[method-assign]
    handler = CoreCommandHandler(
        workspace=ws,
        layout=layout,
        router=router,  # type: ignore[arg-type]
        sessions=sessions,
    )
    run_id = await _spawn_l1(supervisor, summary="long running job")
    reply = await handler.handle(
        IncomingMessage(channel="telegram", user_id="owner1", text="/stop"),
        session_id="sess-l1",
    )
    # Must not auto-kill via session cancel when presenting the picker.
    assert cancel_calls == []
    markup = _reply_markup(reply)
    assert markup is not None
    cbs = _markup_callbacks(markup)
    assert f"act:subagents:kill:{run_id}" in cbs
    assert "act:subagents:kill_all" in cbs
    # Labels include short id + role + truncated task_summary (D7).
    labels = [
        str(btn.get("text", ""))
        for row in markup["inline_keyboard"]
        for btn in row
        if isinstance(btn, dict)
    ]
    joined = " ".join(labels)
    assert run_id in joined
    assert "tier_b" in joined
    assert "long running" in joined or "long runni" in joined


def test_stop_l1_keyboard_omits_kill_for_non_owner() -> None:
    """D11: stop picker kill buttons are owner-only."""
    from sevn.gateway.menu.menu import build_stop_l1_keyboard

    running = (
        {"id": "a1f3", "role": "tier_b", "level": 1, "task_summary": "slow"},
        {"id": "b2c4", "role": "triager", "level": 1, "task_summary": "classify"},
    )
    owner_kb = build_stop_l1_keyboard(running, is_owner=True)
    non_owner_kb = build_stop_l1_keyboard(running, is_owner=False)
    owner_cbs = _markup_callbacks(owner_kb)
    guest_cbs = _markup_callbacks(non_owner_kb)
    assert "act:subagents:kill:a1f3" in owner_cbs
    assert "act:subagents:kill_all" in owner_cbs
    assert not any(cb.startswith("act:subagents:kill") for cb in guest_cbs)


@pytest.mark.asyncio
async def test_stop_with_l1_non_owner_gets_owner_only_copy(tmp_path: Path) -> None:
    """D11: non-owner ``/stop`` with L1 runs explains owner-only kill controls."""
    from sevn.gateway.subagents.surfaces import STOP_L1_OWNER_ONLY_COPY

    layout = _layout(tmp_path)
    ws = WorkspaceConfig.minimal(subagents=SubAgentsWorkspaceConfig(enabled=True))
    conn = _conn()
    sessions = SessionManager(conn)
    cancel_calls: list[str] = []

    async def _track_cancel(session_id: str) -> bool:
        cancel_calls.append(session_id)
        return True

    sessions.cancel_active_dispatch = _track_cancel  # type: ignore[method-assign]
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry=registry, config=SubAgentsWorkspaceConfig())
    router = ChannelRouter.__new__(ChannelRouter)
    router._subagent_supervisor = supervisor
    router._resolve_owner_flag = lambda _msg: False  # type: ignore[method-assign]
    handler = CoreCommandHandler(
        workspace=ws,
        layout=layout,
        router=router,  # type: ignore[arg-type]
        sessions=sessions,
    )
    await _spawn_l1(supervisor, summary="guest cannot kill")
    reply = await handler.handle(
        IncomingMessage(channel="telegram", user_id="guest", text="/stop"),
        session_id="sess-guest",
    )
    assert cancel_calls == []
    assert _reply_text(reply) == STOP_L1_OWNER_ONLY_COPY
    assert _reply_markup(reply) is None


@pytest.mark.asyncio
async def test_stop_kill_callback_kills_individual_l1(tmp_path: Path) -> None:
    """Reuse ``act:subagents:kill:<id>`` — individual kill (existing path; D7)."""
    layout = _layout(tmp_path)
    ws = WorkspaceConfig.minimal(subagents=SubAgentsWorkspaceConfig(enabled=True))
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry=registry, config=SubAgentsWorkspaceConfig())
    run_id = await _spawn_l1(supervisor)

    router = ChannelRouter.__new__(ChannelRouter)
    router._adapters = {}
    router._workspace = ws
    router._resolve_owner_flag = lambda _msg: True  # type: ignore[method-assign]
    router._config_menu_nav = {}
    router._subagent_supervisor = supervisor

    mar = MenuActionRouter(
        workspace=ws,
        router=router,
        conn=sqlite3.connect(":memory:"),
        content_root=layout.content_root,
        sevn_json_path=layout.sevn_json_path,
    )

    msg = IncomingMessage(
        channel="telegram",
        user_id="1",
        text="",
        metadata={"callback_data": f"act:subagents:kill:{run_id}"},
    )
    toast = await mar.handle(msg, session_id="sess")
    assert toast is None or "Killed" in toast or toast == ""
    updated = await supervisor.registry.get(run_id)
    assert updated is not None
    assert updated.status.value == "killed"


@pytest.mark.asyncio
async def test_stop_kill_all_callback_kills_all_l1(tmp_path: Path) -> None:
    """Reuse ``act:subagents:kill_all`` (existing path; D7)."""
    layout = _layout(tmp_path)
    ws = WorkspaceConfig.minimal(subagents=SubAgentsWorkspaceConfig(enabled=True))
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry=registry, config=SubAgentsWorkspaceConfig())
    id_a = await _spawn_l1(supervisor, summary="a")
    id_b = await _spawn_l1(supervisor, summary="b", role="triager")

    router = ChannelRouter.__new__(ChannelRouter)
    router._adapters = {}
    router._workspace = ws
    router._resolve_owner_flag = lambda _msg: True  # type: ignore[method-assign]
    router._config_menu_nav = {}
    router._subagent_supervisor = supervisor

    mar = MenuActionRouter(
        workspace=ws,
        router=router,
        conn=sqlite3.connect(":memory:"),
        content_root=layout.content_root,
        sevn_json_path=layout.sevn_json_path,
    )

    msg = IncomingMessage(
        channel="telegram",
        user_id="1",
        text="",
        metadata={"callback_data": "act:subagents:kill_all"},
    )
    await mar.handle(msg, session_id="sess")
    for run_id in (id_a, id_b):
        updated = await supervisor.registry.get(run_id)
        assert updated is not None
        assert updated.status.value == "killed"


@pytest.mark.asyncio
async def test_stop_kill_callback_refreshes_registered_config_menu(tmp_path: Path) -> None:
    """Kill from a registered ``/config`` host refreshes the config menu, not ``/stop``."""
    layout = _layout(tmp_path)
    ws = WorkspaceConfig.minimal(subagents=SubAgentsWorkspaceConfig(enabled=True))
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry=registry, config=SubAgentsWorkspaceConfig())
    run_id = await _spawn_l1(supervisor)

    router = ChannelRouter.__new__(ChannelRouter)
    router._adapters = {}
    router._workspace = ws
    router._resolve_owner_flag = lambda _msg: True  # type: ignore[method-assign]
    router._config_menu_nav = {(42, 99): object()}
    router._subagent_supervisor = supervisor

    mar = MenuActionRouter(
        workspace=ws,
        router=router,
        conn=sqlite3.connect(":memory:"),
        content_root=layout.content_root,
        sevn_json_path=layout.sevn_json_path,
    )
    config_calls: list[tuple[Any, ...]] = []
    stop_calls: list[tuple[Any, ...]] = []

    async def _track_config(*_a: Any, **_k: Any) -> bool:
        config_calls.append((_a, _k))
        return True

    async def _track_stop(*_a: Any, **_k: Any) -> bool:
        stop_calls.append((_a, _k))
        return True

    mar._refresh_config_menu_after_action = _track_config  # type: ignore[method-assign]
    mar._refresh_stop_picker_after_kill = _track_stop  # type: ignore[method-assign]

    msg = IncomingMessage(
        channel="telegram",
        user_id="1",
        text="",
        metadata={
            "callback_data": f"act:subagents:kill:{run_id}",
            "chat_id": 42,
            "message_id": 99,
        },
    )
    await mar.handle(msg, session_id="sess")
    assert len(config_calls) == 1
    assert stop_calls == []
    updated = await supervisor.registry.get(run_id)
    assert updated is not None
    assert updated.status.value == "killed"


@pytest.mark.asyncio
async def test_slash_stop_kill_reedits_picker_and_acks_callback(tmp_path: Path) -> None:
    """Kill from an unregistered (slash ``/stop``) host re-edits picker + answers callback."""
    layout = _layout(tmp_path)
    ws = WorkspaceConfig.minimal(subagents=SubAgentsWorkspaceConfig(enabled=True))
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry=registry, config=SubAgentsWorkspaceConfig())
    run_id = await _spawn_l1(supervisor)

    cap = _MenuCaptureTelegram()
    router = ChannelRouter.__new__(ChannelRouter)
    router._adapters = {"telegram": cap}
    router._workspace = ws
    router._resolve_owner_flag = lambda _msg: True  # type: ignore[method-assign]
    router._config_menu_nav = {}  # unregistered → slash /stop picker path
    router._subagent_supervisor = supervisor

    mar = MenuActionRouter(
        workspace=ws,
        router=router,
        conn=sqlite3.connect(":memory:"),
        content_root=layout.content_root,
        sevn_json_path=layout.sevn_json_path,
    )

    msg = IncomingMessage(
        channel="telegram",
        user_id="1",
        text="",
        metadata={
            "callback_data": f"act:subagents:kill:{run_id}",
            "chat_id": 42,
            "message_id": 99,
            "callback_query_id": "cq-stop-kill",
        },
    )
    await mar.handle(msg, session_id="sess")
    updated = await supervisor.registry.get(run_id)
    assert updated is not None
    assert updated.status.value == "killed"
    assert cap.edited, "slash /stop kill must re-edit the picker message"
    edited = cap.edited[-1]
    assert edited["chat_id"] == 42
    assert edited["message_id"] == 99
    assert edited["text"] == _STOPPED
    assert edited["reply_markup"] == {"inline_keyboard": []}
    answers = dict(cap.answered)
    assert "cq-stop-kill" in answers
    assert "Killed" in (answers["cq-stop-kill"] or "")


# --- D9: slash path attaches reply_markup ---


@pytest.mark.asyncio
async def test_slash_stop_attaches_reply_markup_when_l1_running(tmp_path: Path) -> None:
    """D9: agent_turn slash send path attaches ``metadata['reply_markup']`` for /stop."""
    layout = _layout(tmp_path)
    ws = _workspace()
    conn = _conn()
    cap = _MenuCaptureTelegram()
    router = ChannelRouter(
        workspace=ws,
        content_root=layout.content_root,
        sessions=SessionManager(conn),
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(layout.content_root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
        media=MediaStore(conn, layout.content_root),
        run_turn=AsyncMock(),
        owner_user_ids=frozenset({"owner1"}),
    )
    router.register_adapter(cap)
    build_agent_run_turn(router, conn, ws, layout, NullTraceSink())
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry=registry, config=SubAgentsWorkspaceConfig())
    router._subagent_supervisor = supervisor
    run_id = await _spawn_l1(supervisor, summary="picker via slash")

    await router.route_incoming(
        IncomingMessage(channel="telegram", user_id="owner1", text="/stop"),
    )
    assert cap.sent
    text, md = cap.sent[-1]
    assert text  # picker prompt or status copy
    markup = md.get("reply_markup")
    assert isinstance(markup, dict)
    cbs = _markup_callbacks(markup)
    assert f"act:subagents:kill:{run_id}" in cbs
    assert "act:subagents:kill_all" in cbs


@pytest.mark.asyncio
async def test_menu_cmd_stop_attaches_same_reply_markup(tmp_path: Path) -> None:
    """D9: pin/menu ``menu:cmd:stop`` gets the same L1 keyboard as slash /stop."""
    layout = _layout(tmp_path)
    ws = _workspace()
    conn = _conn()
    cap = _MenuCaptureTelegram()
    router = ChannelRouter(
        workspace=ws,
        content_root=layout.content_root,
        sessions=SessionManager(conn),
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(layout.content_root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
        media=MediaStore(conn, layout.content_root),
        run_turn=AsyncMock(),
        owner_user_ids=frozenset({"owner1"}),
    )
    router.register_adapter(cap)
    build_agent_run_turn(router, conn, ws, layout, NullTraceSink())
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry=registry, config=SubAgentsWorkspaceConfig())
    router._subagent_supervisor = supervisor
    run_id = await _spawn_l1(supervisor)

    await router.route_incoming(
        IncomingMessage(
            channel="telegram",
            user_id="owner1",
            text="",
            metadata={
                "callback_data": "menu:cmd:stop",
                "callback_query_id": "cq-stop",
                "chat_id": 42,
                "message_id": 11,
            },
        ),
    )
    assert cap.sent
    _text, md = cap.sent[-1]
    markup = md.get("reply_markup")
    assert isinstance(markup, dict)
    assert f"act:subagents:kill:{run_id}" in _markup_callbacks(markup)
