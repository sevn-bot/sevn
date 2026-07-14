"""Gateway PlanGate Telegram callbacks (`plan/gateway-agent-glue-wave-plan.md` Wave 6)."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from sevn.agent.executors.cd_types import Plan, PlanStep
from sevn.agent.executors.plan_gate_store import load_pending_plan_by_id, store_pending_plan
from sevn.agent.tracing.sink import NullTraceSink
from sevn.channels.telegram import TelegramAdapter
from sevn.config.workspace_config import parse_workspace_config
from sevn.gateway.channel_router import ChannelRouter, IncomingMessage, OutgoingMessage
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.routing.plan_gate import (
    PlanGateCallbackHandler,
    PlanGateWaitRegistry,
    SqlitePlanGate,
)
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.security.llm_guard_scanner import LLMGuardScanner
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout


class _CaptureRouter:
    """Minimal router stub recording ``route_outgoing`` calls."""

    def __init__(self) -> None:
        self.outbound: list[OutgoingMessage] = []

    async def route_outgoing(self, msg: OutgoingMessage) -> None:
        self.outbound.append(msg)


class _CaptureTelegram(TelegramAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.sent_texts: list[str] = []

    async def send(self, message: Any) -> list[str]:
        self.sent_texts.append(message.text)
        return await super().send(message)


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


@pytest.mark.asyncio
async def test_sqlite_plan_gate_approve_unblocks(tmp_path: Path) -> None:
    """``SqlitePlanGate`` persists row, posts plan, resumes on ``plan:*:approve``."""
    conn = _memory_conn()
    sessions = SessionManager(conn)
    await sessions.ensure_session(
        scope_key="telegram:owner",
        channel="telegram",
        user_id="owner",
    )
    session_rows = conn.execute("SELECT session_id FROM gateway_sessions").fetchone()
    assert session_rows is not None
    session_id = str(session_rows[0])
    registry = PlanGateWaitRegistry()
    router = _CaptureRouter()
    gate = SqlitePlanGate(
        conn=conn,
        router=router,  # type: ignore[arg-type]
        registry=registry,
        channel="telegram",
        user_id="owner",
        route_metadata={"chat_id": 99},
    )
    plan = Plan(
        steps=[PlanStep(id="1", title="migrate schema")],
        summary="Two-step migration",
        meta=Plan.Meta(complexity="C", registry_version=1),
    )
    handler = PlanGateCallbackHandler(conn, registry)
    wait_task = asyncio.create_task(
        gate.await_approval(
            plan=plan,
            session_id=session_id,
            turn_id="turn-pg",
            trace=None,
        ),
    )
    for _ in range(50):
        row = conn.execute(
            "SELECT plan_id FROM pending_plans WHERE status = 'awaiting'",
        ).fetchone()
        if row is not None:
            break
        await asyncio.sleep(0.05)
    assert row is not None
    plan_id = str(row[0])
    assert router.outbound
    assert "inline_keyboard" in (router.outbound[0].metadata or {})
    msg = IncomingMessage(
        channel="telegram",
        user_id="owner",
        text=f"plan:{plan_id}:approve",
        metadata={"callback_data": f"plan:{plan_id}:approve"},
    )
    await handler.handle(msg, session_id=session_id)
    outcome = await asyncio.wait_for(wait_task, timeout=3.0)
    assert outcome == "approved"
    loaded = load_pending_plan_by_id(conn, plan_id=plan_id)
    assert loaded is not None
    assert loaded.status == "approved"
    conn.close()


@pytest.mark.asyncio
async def test_plan_gate_callback_via_dispatcher_bypass() -> None:
    """``CommandDispatcher`` matches ``plan:*`` and handler approves the waiter."""
    conn = _memory_conn()
    session_id = await SessionManager(conn).ensure_session(
        scope_key="telegram:owner",
        channel="telegram",
        user_id="owner",
    )
    registry = PlanGateWaitRegistry()
    handler = PlanGateCallbackHandler(conn, registry)
    plan = Plan(
        steps=[PlanStep(id="1", title="step")],
        summary="summary",
        meta=Plan.Meta(complexity="C", registry_version=1),
    )
    rec = store_pending_plan(
        conn,
        session_id=session_id,
        turn_id="turn-1",
        plan=plan,
        c_d_backend="dspy",
        now_ns=1,
    )
    waiter = registry.register(rec.plan_id)
    msg = IncomingMessage(
        channel="telegram",
        user_id="owner",
        text=f"plan:{rec.plan_id}:approve",
        metadata={"callback_data": f"plan:{rec.plan_id}:approve"},
    )
    assert CommandDispatcher().try_dispatch(msg)
    assert handler.matches(msg)
    await handler.handle(msg, session_id=session_id)
    await asyncio.wait_for(waiter.event.wait(), timeout=2.0)
    assert waiter.outcome == "approved"
    conn.close()


@pytest.mark.asyncio
async def test_build_agent_run_turn_wires_plan_handler(tmp_path: Path) -> None:
    """``build_agent_run_turn`` attaches callback handler on the router."""
    from sevn.gateway.agent_turn import build_agent_run_turn

    conn = _memory_conn()
    root = tmp_path / "w"
    root.mkdir()
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "plan_approval": {"enabled": True},
            "security": {"scanner": {"heuristic_only": True}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    layout = WorkspaceLayout(root / "sevn.json", root)
    router = ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=SessionManager(conn),
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=10.0, refill_per_second=5.0),
        media=MediaStore(conn, root),
    )
    build_agent_run_turn(router, conn, ws, layout, NullTraceSink())
    assert getattr(router, "_plan_gate_callback_handler", None) is not None
    assert getattr(router, "_plan_gate_registry", None) is not None
    conn.close()
