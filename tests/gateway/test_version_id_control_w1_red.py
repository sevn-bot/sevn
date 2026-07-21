"""PR #53 version_id / agent-control RED tests (green after W19)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.channels.telegram import TelegramAdapter
from sevn.config.sections.subagents import SubAgentsWorkspaceConfig
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.agent_turn import build_agent_run_turn
from sevn.gateway.channel_router import ChannelRouter, IncomingMessage
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.commands.menu_action_router import MenuActionRouter
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.security.llm_guard_scanner import LLMGuardScanner
from sevn.workspace.layout import WorkspaceLayout
from tests.gateway.test_menu import _conn, _workspace
from tests.gateway.test_my_sevn_version_id import (
    _build_owner_router,
    _callback,
)


class _ProductionAnswerTelegram(TelegramAdapter):
    """Test double exposing production ``answer_callback`` (not ``answer_callback_query``)."""

    def __init__(self) -> None:
        super().__init__(resolved_bot_token="test-token")
        self.answered: list[tuple[str, str | None]] = []
        self.sent: list[tuple[str, dict[str, Any]]] = []
        self.edited: list[dict[str, Any]] = []

    async def send(self, message: Any) -> list[str]:
        md = dict(message.metadata) if isinstance(message.metadata, dict) else {}
        self.sent.append((message.text, md))
        return ["501"]

    async def answer_callback(self, callback_query_id: str, *, text: str = "") -> None:
        self.answered.append((callback_query_id, text or None))

    async def edit_message_text(self, **kwargs: Any) -> bool:
        self.edited.append(dict(kwargs))
        return True


@pytest.mark.xfail(reason="green after W19: test double uses answer_callback", strict=False)
def test_menu_capture_telegram_exposes_answer_callback() -> None:
    """Production TelegramAdapter defines ``answer_callback`` — doubles must match."""
    from tests.gateway import test_menu as menu_mod

    cap = menu_mod._MenuCaptureTelegram()
    assert hasattr(cap, "answer_callback")
    assert callable(cap.answer_callback)
    # Must not be the only probe name used by _answer_callback.
    assert not hasattr(cap, "answer_callback_query") or hasattr(cap, "answer_callback")


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W19: version_id toast via answer_callback", strict=False)
async def test_version_id_toast_via_production_answer_callback(tmp_path: Path) -> None:
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
    cap = _ProductionAnswerTelegram()
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
    router._version_id = "tg-build-99"  # type: ignore[attr-defined]
    await router.route_incoming(_callback("cfg:logs:version_id", callback_query_id="cq-vid"))
    answers = dict(cap.answered)
    assert "cq-vid" in answers
    assert "tg-build-99" in (answers["cq-vid"] or "")


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W19: version_id fallback chat toast", strict=False)
async def test_version_id_fallback_toast_when_inline_answer_fails(tmp_path: Path) -> None:
    router, cap, _root = _build_owner_router(tmp_path)
    router._version_id = "tg-build-99"  # type: ignore[attr-defined]

    class _FailAnswer(type(cap)):
        async def answer_callback_query(
            self, *, callback_query_id: str, text: str | None = None
        ) -> bool:
            return False

    # Force inline answer to no-op; fallback chat text must still appear.
    cap.answer_callback_query = _FailAnswer.answer_callback_query.__get__(cap, type(cap))  # type: ignore[method-assign]
    await router.route_incoming(_callback("cfg:logs:version_id", callback_query_id="cq-fail"))
    assert any("tg-build-99" in (t or "") for t, _md in cap.sent) or any(
        "tg-build-99" in (t or "") for _cq, t in cap.answered
    )


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W19: slash /stop picker refresh after kill", strict=False)
async def test_slash_stop_kill_refreshes_stop_picker(tmp_path: Path) -> None:
    from sevn.agent.subagents.registry import SubAgentRegistry
    from sevn.agent.subagents.supervisor import SubAgentSupervisor

    layout = WorkspaceLayout(tmp_path / "sevn.json", tmp_path)
    (tmp_path / "sevn.json").write_text(
        '{"schema_version":1,"gateway":{"token":"t"}}', encoding="utf-8"
    )
    ws = WorkspaceConfig.minimal(subagents=SubAgentsWorkspaceConfig(enabled=True))
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry=registry, config=SubAgentsWorkspaceConfig())
    run = await registry.register(
        level=1,
        role="tier_b",
        session_id="sess",
        channel="telegram",
        task_summary="t",
    )
    await registry.mark_running(run.id)

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
    stop_calls: list[Any] = []

    async def _track_stop(*_a: Any, **_k: Any) -> bool:
        stop_calls.append((_a, _k))
        return True

    mar._refresh_stop_picker_after_kill = _track_stop  # type: ignore[method-assign]

    msg = IncomingMessage(
        channel="telegram",
        user_id="1",
        text="",
        metadata={
            "callback_data": f"act:subagents:kill:{run.id}",
            "chat_id": 42,
            "message_id": 99,
            # No registered config host → slash /stop picker path.
        },
    )
    await mar.handle(msg, session_id="sess")
    assert stop_calls, "slash /stop kill must refresh the stop picker"
