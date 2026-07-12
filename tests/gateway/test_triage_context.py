"""Gateway Triager context builders (`plan/gateway-agent-glue-wave-plan.md` Wave 2)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from sevn.agent.triager.context import RegistrySnapshot, SessionView, TriagePromptContext
from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
from sevn.agent.triager.prompt import GROUP_TRIAGE_INSTRUCTION_V1, build_triager_prompt_segments
from sevn.config.defaults import INITIAL_REGISTRY_VERSION
from sevn.config.workspace_config import parse_workspace_config
from sevn.gateway.triage_audit import persist_triage_decision
from sevn.gateway.triage_context import (
    group_triage_block_would_inject,
    is_triager_enabled,
    latest_prior_triage_result,
    passthrough_triage_result,
    registry_snapshot_from_tool_set,
    session_view_from_session,
    triage_context_from_session,
)
from sevn.storage.migrate import apply_migrations
from sevn.tools.base import ToolDefinition
from sevn.tools.registry import ToolSet, build_session_registry
from sevn.workspace.layout import WorkspaceLayout


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


def _seed_session(
    conn: sqlite3.Connection,
    *,
    session_id: str = "sess-1",
    metadata: dict[str, object] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO gateway_sessions (
            session_id, scope_key, channel, user_id, created_at, updated_at,
            unanswered_tail_message_id, last_final_assistant_message_id, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            "telegram:-100",
            "telegram",
            "9001",
            "2026-05-21T00:00:00",
            "2026-05-21T00:00:00",
            None,
            None,
            json.dumps(metadata) if metadata is not None else None,
        ),
    )


def test_registry_snapshot_from_tool_set_maps_native_mcp_and_skills() -> None:
    native = (
        ToolDefinition(
            name="tick",
            category="session",
            description="health check",
            parameters={"type": "object", "properties": {}},
        ),
    )
    mcp = (
        ToolDefinition(
            name="remote.echo",
            category="mcp",
            description="remote echo",
            parameters={"type": "object", "properties": {}},
        ),
    )
    tool_set = ToolSet(5, native, mcp, {"zebra": "skill summary"})
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "tools": {"add_core_tools_to_all_context": False},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    snap = registry_snapshot_from_tool_set(tool_set, workspace=ws)
    assert snap.registry_version == 5
    assert snap.tools[0].identifier == "tick"
    assert snap.mcp_servers[0].identifier == "remote.echo"
    assert snap.skills[0].identifier == "zebra"
    assert snap.add_core_tools_to_all_context is False


def test_registry_snapshot_surfaces_available_skill_inventory() -> None:
    native = (
        ToolDefinition(
            name="tick",
            category="session",
            description="health check",
            parameters={"type": "object", "properties": {}},
        ),
    )
    tool_set = ToolSet(
        5,
        native,
        (),
        {"zebra": "skill summary"},
        {
            "zebra": {
                "summary": "skill summary",
                "scripts": ["scripts/status.py"],
                "runnables": ["index"],
            }
        },
    )
    snap = registry_snapshot_from_tool_set(tool_set)
    assert snap.available_skills
    assert snap.available_skills[0].name == "zebra"
    assert "scripts/status.py" in snap.available_skills[0].scripts


def test_registry_snapshot_lists_bundled_core_skills(tmp_path: Path) -> None:
    """Live ``build_session_registry`` skill index surfaces bundled core ids."""
    from sevn.skills.manager import SkillsManager

    SkillsManager.reset_singletons_for_tests()
    root = tmp_path / "ws"
    root.mkdir()
    (root / "skills").mkdir()
    ws = parse_workspace_config(
        {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
    )
    layout = WorkspaceLayout(root / "sevn.json", root)
    _exe, tool_set = build_session_registry(
        workspace_root=root,
        layout=layout,
        workspace_config=ws,
    )
    snap = registry_snapshot_from_tool_set(tool_set, workspace=ws)
    skill_ids = {entry.identifier for entry in snap.skills}
    assert {"canvas", "second_brain"} & skill_ids
    assert tool_set.registry_version >= INITIAL_REGISTRY_VERSION


def test_triage_context_from_session_builds_transcript_and_flags() -> None:
    conn = _memory_conn()
    try:
        _seed_session(conn)
        conn.execute(
            """
            INSERT INTO gateway_messages (
                session_id, role, kind, content, visible_to_llm, status, extras_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "sess-1",
                "user",
                "message",
                "earlier hello",
                1,
                "sent",
                None,
                "2026-05-21T00:00:01",
            ),
        )
        conn.execute(
            """
            INSERT INTO gateway_messages (
                session_id, role, kind, content, visible_to_llm, status, extras_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "sess-1",
                "assistant",
                "message",
                "hi back",
                1,
                "sent",
                None,
                "2026-05-21T00:00:02",
            ),
        )
        conn.execute(
            """
            INSERT INTO gateway_messages (
                session_id, role, kind, content, visible_to_llm, status, extras_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "sess-1",
                "user",
                "message",
                "current turn",
                1,
                "sent",
                None,
                "2026-05-21T00:00:03",
            ),
        )
        ws = parse_workspace_config(
            {
                "schema_version": 1,
                "plan_approval": {"enabled": True},
                "permissions": {"scope_narrowing": {"enabled": True}},
                "triager": {"history_turns_n": 4},
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            },
        )
        ctx = triage_context_from_session(conn, "sess-1", ws, "current turn")
        assert ctx.current_message == "current turn"
        assert ctx.plan_approval_enabled is True
        assert ctx.permissions_scope_narrowing_enabled is True
        assert ctx.transcript_turns == ["user: earlier hello", "assistant: hi back"]
    finally:
        conn.close()


def test_triage_context_loads_prior_triage_for_continuation_fast_path() -> None:
    conn = _memory_conn()
    try:
        _seed_session(conn)
        ws = parse_workspace_config(
            {
                "schema_version": 1,
                "workspace_root": "/w",
                "providers": {"tier_default": {"triager": "stub/t"}},
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            },
        )
        prior = TriageResult(
            intent=Intent.NEW_REQUEST,
            complexity=ComplexityTier.B,
            first_message="Working.",
            tools=["read"],
            skills=["pdf"],
            mcp_servers_required=[],
            confidence=0.9,
            requires_vision=False,
            requires_document=False,
        )
        persist_triage_decision(
            conn,
            workspace=ws,
            session_id="sess-1",
            turn_id="turn-prior",
            triage=prior,
            registry_version=1,
            personality_version=0,
        )
        loaded = latest_prior_triage_result(conn, session_id="sess-1", workspace=ws)
        assert loaded is not None
        assert loaded.tools == ["read"]
        ctx = triage_context_from_session(conn, "sess-1", ws, "go ahead")
        assert ctx.prior_triage_result is not None
        assert ctx.prior_triage_result.skills == ["pdf"]
    finally:
        conn.close()


def test_session_view_group_member_count_from_metadata_and_extras() -> None:
    conn = _memory_conn()
    try:
        _seed_session(conn, metadata={"chat_member_count": 5})
        sv = session_view_from_session(conn, "sess-1", channel="telegram", user_id="9001")
        assert sv.chat_member_count == 5

        conn.execute("DELETE FROM gateway_sessions")
        _seed_session(conn, session_id="sess-2")
        conn.execute(
            """
            INSERT INTO gateway_messages (
                session_id, role, kind, content, visible_to_llm, status, extras_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "sess-2",
                "user",
                "message",
                "group ping",
                1,
                "sent",
                json.dumps({"chat_id": -100123, "chat_type": "supergroup"}),
                "2026-05-21T00:00:01",
            ),
        )
        sv2 = session_view_from_session(conn, "sess-2", channel="telegram", user_id="9001")
        assert sv2.chat_member_count >= 2
    finally:
        conn.close()


def test_group_triage_block_would_inject_for_group_chat() -> None:
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "triager": {"group_scope": "all"},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        }
    )
    sv = SessionView(session_id="g", chat_member_count=3)
    ctx = TriagePromptContext(current_message="hello there")
    assert group_triage_block_would_inject(ws, sv, ctx) is True
    _static, _reg, _pers, suffix = build_triager_prompt_segments(
        registry_snapshot=RegistrySnapshot(),
        triage_context=ctx.model_copy(update={"inject_group_triage_block": True}),
    )
    assert GROUP_TRIAGE_INSTRUCTION_V1 in suffix


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1", True),
        ("true", True),
        ("0", False),
        ("false", False),
        ("off", False),
    ],
)
def test_is_triager_enabled_env(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
    expected: bool,
) -> None:
    monkeypatch.setenv("TRIAGER_ENABLED", value)
    assert is_triager_enabled() is expected


def test_passthrough_triage_result_is_tier_b_without_first_message() -> None:
    triage = passthrough_triage_result()
    assert triage.complexity.value == "B"
    assert triage.first_message == ""
    assert triage.disregard is False


@pytest.mark.asyncio
async def test_agent_turn_triager_disabled_passthrough_to_tier_b(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``TRIAGER_ENABLED=0``, glue skips stub Triager and runs tier B."""
    from collections.abc import Awaitable, Callable
    from typing import Any

    from sevn.agent.executors.b_types import ResolvedTierBModel
    from sevn.agent.providers.budget import BudgetRegime, ModelBudget
    from sevn.agent.providers.transport import ChatCompletionsTransport
    from sevn.agent.tracing.sink import NullTraceSink
    from sevn.channels.telegram import TelegramAdapter
    from sevn.gateway.agent_turn import build_agent_run_turn
    from sevn.gateway.channel_router import ChannelRouter
    from sevn.gateway.commands.dispatcher import CommandDispatcher
    from sevn.gateway.media_store import MediaStore
    from sevn.gateway.rate_limit import TokenBucketLimiter
    from sevn.gateway.session_manager import SessionManager
    from sevn.security.llm_guard_scanner import LLMGuardScanner
    from sevn.workspace.layout import WorkspaceLayout

    monkeypatch.setenv("TRIAGER_ENABLED", "0")
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")

    class _ScriptedChatTransport(ChatCompletionsTransport):
        def __init__(self, fn: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]) -> None:
            super().__init__(proxy_base_url="http://passthrough.test.invalid")
            self._fn = fn

        async def complete(self, request: dict[str, object]) -> dict[str, object]:
            return await self._fn(dict(request))

    class _CaptureTelegram(TelegramAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.sent_texts: list[str] = []

        async def send(self, message: Any) -> list[str]:
            self.sent_texts.append(message.text)
            return await super().send(message)

    async def _scripted(_req: dict[str, Any]) -> dict[str, Any]:
        return {
            "choices": [
                {"message": {"role": "assistant", "content": "Passthrough executor reply."}}
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    async def _bundle_factory(_ws: Any) -> ResolvedTierBModel:
        transport = _ScriptedChatTransport(_scripted)
        return ResolvedTierBModel(
            model_id="openai/gpt-passthrough",
            transport=transport,
            budget=ModelBudget(model_id="openai/gpt-passthrough", regime=BudgetRegime.FREE_LOCAL),
        )

    conn = _memory_conn()
    root = tmp_path / "w"
    root.mkdir()
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "providers": {"tier_default": {"B": "stub/tier-b"}},
            "security": {"scanner": {"heuristic_only": True}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    layout = WorkspaceLayout(root / "sevn.json", root)
    sessions = SessionManager(conn)
    media = MediaStore(conn, root)
    router = ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=sessions,
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
        media=media,
    )
    cap = _CaptureTelegram()
    router.register_adapter(cap)
    run_turn = build_agent_run_turn(
        router,
        conn,
        ws,
        layout,
        NullTraceSink(),
        tier_b_bundle_factory=_bundle_factory,
    )
    try:
        session_id = await sessions.ensure_session(
            scope_key="telegram:u-pass",
            channel="telegram",
            user_id="u-pass",
        )
        await sessions.add_message(
            session_id,
            role="user",
            kind="message",
            content="skip triager please",
            visible_to_llm=1,
            status="sent",
            metadata_blob=json.dumps({"chat_id": 8008}),
            turn_id="t-test",
        )
        await run_turn(session_id, "corr-pass-1")
        await sessions.drain()
        assert any("Passthrough executor reply." in t for t in cap.sent_texts)
    finally:
        conn.close()
