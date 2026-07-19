"""RED suite for ``/agents`` running-inventory (plan D6/D11 / issue #28 / W4)."""

from __future__ import annotations

import asyncio
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
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.security.llm_guard_scanner import LLMGuardScanner
from sevn.workspace.layout import WorkspaceLayout
from tests.gateway.test_menu import _conn, _MenuCaptureTelegram, _workspace

_XFAIL_W4 = pytest.mark.xfail(
    reason="green after W4: /agents running inventory (D6/D11)",
    strict=False,
)

_EMPTY_COPY = "No agents running."


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


def _handler(
    tmp_path: Path,
    *,
    router: ChannelRouter | None = None,
) -> tuple[CoreCommandHandler, ChannelRouter, Path]:
    layout = _layout(tmp_path)
    ws = WorkspaceConfig.minimal(subagents=SubAgentsWorkspaceConfig(enabled=True))
    conn = _conn()
    sessions = SessionManager(conn)
    if router is None:
        router = ChannelRouter(
            workspace=ws,
            content_root=layout.content_root,
            sessions=sessions,
            dispatcher=CommandDispatcher(),
            scanner=LLMGuardScanner(layout.content_root, ws),
            trace=NullTraceSink(),
            rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
            media=MediaStore(conn, layout.content_root),
            run_turn=AsyncMock(),
            owner_user_ids=frozenset({"owner1"}),
        )
    handler = CoreCommandHandler(
        workspace=ws,
        layout=layout,
        router=router,
        sessions=sessions,
    )
    return handler, router, layout.content_root


async def _spawn_l1_l2(
    supervisor: SubAgentSupervisor,
    *,
    l1_summary: str = "parent task",
    l2_summary: str = "child task",
) -> tuple[str, str]:
    async def _work() -> None:
        await asyncio.sleep(120)

    l1 = await supervisor.spawn(
        SubAgentSpec(
            level=1,
            role="tier_b",
            body=_work,
            session_id="s-agents",
            channel="telegram",
            task_summary=l1_summary,
        ),
    )

    async def _child() -> None:
        await asyncio.sleep(120)

    l2 = await supervisor.spawn(
        SubAgentSpec(
            level=2,
            role="tier_b",
            body=_child,
            session_id="s-agents",
            channel="telegram",
            task_summary=l2_summary,
            parent_id=l1.id,
        ),
    )
    return l1.id, l2.id


@_XFAIL_W4
def test_matches_slash_agents() -> None:
    """``/agents`` is recognized as a core slash command (D6)."""
    h = CoreCommandHandler.__new__(CoreCommandHandler)
    assert h.matches_slash(
        IncomingMessage(channel="telegram", user_id="1", text="/agents"),
    )


@_XFAIL_W4
@pytest.mark.asyncio
async def test_agents_empty_state_copy(tmp_path: Path) -> None:
    """Empty registry → clear empty-state copy (D6)."""
    handler, router, _ = _handler(tmp_path)
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry=registry, config=SubAgentsWorkspaceConfig())
    router._subagent_supervisor = supervisor
    reply = await handler.handle(
        IncomingMessage(channel="telegram", user_id="owner1", text="/agents"),
        session_id="sess-1",
    )
    text = reply if isinstance(reply, str) else getattr(reply, "text", None)
    assert text == _EMPTY_COPY


@_XFAIL_W4
@pytest.mark.asyncio
async def test_agents_groups_l2_under_parent_id(tmp_path: Path) -> None:
    """Rich inventory groups L2 under parent L1 via ``parent_id`` (D6)."""
    from sevn.gateway.menu.menu import format_running_agents_inventory

    handler, router, _ = _handler(tmp_path)
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry=registry, config=SubAgentsWorkspaceConfig())
    router._subagent_supervisor = supervisor
    l1_id, l2_id = await _spawn_l1_l2(supervisor)

    running = await registry.running()
    rows = [
        {
            "id": r.id,
            "level": r.level,
            "role": r.role,
            "parent_id": r.parent_id,
            "task_summary": r.task_summary,
            "status": r.status.value,
            "age_s": 0.1,
        }
        for r in running
    ]
    # Shared formatter (W4.1) — L2 appears after its parent.
    text = format_running_agents_inventory(rows)
    assert l1_id in text
    assert l2_id in text
    assert text.index(l1_id) < text.index(l2_id)
    assert "parent task" in text
    assert "child task" in text

    reply = await handler.handle(
        IncomingMessage(channel="telegram", user_id="owner1", text="/agents"),
        session_id="sess-1",
    )
    body = reply if isinstance(reply, str) else getattr(reply, "text", "")
    assert l1_id in body
    assert l2_id in body


@_XFAIL_W4
def test_agents_inventory_caps_overflow_detail() -> None:
    """Many rows: detail is capped / overflow summarized (D6)."""
    from sevn.gateway.menu.menu import format_running_agents_inventory

    rows: list[dict[str, Any]] = []
    for i in range(20):
        rows.append(
            {
                "id": f"l1{i:02x}",
                "level": 1,
                "role": "tier_b",
                "parent_id": None,
                "task_summary": f"task-{i}",
                "status": "running",
                "age_s": float(i),
            },
        )
    text = format_running_agents_inventory(rows)
    assert "l100" in text or "l101" in text
    # Overflow must be signaled rather than dumping all 20 full detail blocks.
    assert "more" in text.lower() or "…" in text or "..." in text or text.count("task-") <= 12


@_XFAIL_W4
@pytest.mark.asyncio
async def test_agents_list_visible_to_non_owner(tmp_path: Path) -> None:
    """D11: inventory visible to non-owners (same as Config→Sub-agents Running)."""
    handler, router, root = _handler(tmp_path)
    registry = SubAgentRegistry()
    supervisor = SubAgentSupervisor(registry=registry, config=SubAgentsWorkspaceConfig())
    router._subagent_supervisor = supervisor
    l1_id, _l2_id = await _spawn_l1_l2(supervisor, l1_summary="visible to all")

    reply = await handler.handle(
        IncomingMessage(channel="telegram", user_id="not-owner", text="/agents"),
        session_id="sess-guest",
    )
    body = reply if isinstance(reply, str) else getattr(reply, "text", "")
    assert l1_id in body
    assert "visible to all" in body
    # List-only command: no kill controls / no owner-only denial of the list.
    assert "not allowed" not in body.lower()
    assert "owner-only" not in body.lower() or "Kill controls are owner-only." in body
    _ = root


@_XFAIL_W4
def test_agents_registered_in_set_my_commands() -> None:
    """``setMyCommands`` / core command list includes ``agents`` (D6)."""
    from sevn.channels.telegram_poll import core_bot_commands

    names = {c.get("command") for c in core_bot_commands()}
    assert "agents" in names


@_XFAIL_W4
@pytest.mark.asyncio
async def test_slash_agents_sends_inventory_via_agent_turn(tmp_path: Path) -> None:
    """End-to-end: once ``matches_slash`` accepts ``/agents``, slash path sends inventory.

    Fail-fast on ``matches_slash`` so an unregistered command cannot fall through
    into the LLM turn pipeline (which hangs under AsyncMock ``run_turn``).
    """
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

    # Core handler attached by build_agent_run_turn — probe matches before route.
    core = getattr(router, "_core_command_handler", None)
    if core is None:
        # Fallback: construct and assert registration contract.
        core, _, _ = _handler(tmp_path, router=router)
    msg = IncomingMessage(channel="telegram", user_id="owner1", text="/agents")
    assert core.matches_slash(msg)

    await router.route_incoming(msg)
    assert cap.sent
    assert any(_EMPTY_COPY in text for text, _md in cap.sent)
