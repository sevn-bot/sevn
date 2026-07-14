"""``multi`` queue-mode integration (`specs/17-gateway.md` · `specs/36-sub-agents.md` W4)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.agent.triager.relatedness import RelatednessInput, RelatednessResult
from sevn.config.workspace_config import (
    GatewayConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WorkspaceConfig,
    parse_workspace_config,
)
from sevn.gateway.channel_router import ChannelRouter, IncomingMessage
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.queue.queue_multi import MultiDispatchHooks, MultiSpawnOutcome
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager, unanswered_tail_message_id
from sevn.onboarding.validate import validate_workspace_document
from sevn.security.llm_guard_scanner import LLMGuardScanner, ScanResult, ScanVerdict
from sevn.storage.migrate import apply_migrations


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


def _router(
    tmp_path: Path,
    conn: sqlite3.Connection,
    *,
    run_turn: Any,
    classify: Any | None = None,
) -> ChannelRouter:
    root = tmp_path / "w"
    root.mkdir()
    ws = WorkspaceConfig(
        schema_version=1,
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        gateway=GatewayConfig(queue_mode="multi", token="${SECRET:keychain:sevn.gateway.token}"),  # type: ignore[arg-type]
    )
    router = ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=SessionManager(conn),
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
        media=MediaStore(conn, root),
        run_turn=run_turn,
        queue_mode="multi",
    )
    if classify is not None:

        async def _spawn(_sid: str, _cid: str) -> MultiSpawnOutcome:
            return MultiSpawnOutcome.SPAWNED

        async def _notify(_sid: str, _line: str) -> None:
            return None

        async def _classify_busy(
            _in_flight: str,
            _queued: tuple[str, ...],
            _new: str,
        ) -> tuple[str, bool]:
            result = await classify(
                RelatednessInput(_in_flight, _queued, _new),
            )
            if isinstance(result, RelatednessResult):
                return result.label, result.fallback
            return str(result), False  # type: ignore[arg-type]

        router._spawn_multi_l1_tier_b = _spawn  # type: ignore[attr-defined]

        router._test_multi_hooks = MultiDispatchHooks(  # type: ignore[attr-defined]
            classify_busy=_classify_busy,
            spawn_new_task=_spawn,
            notify_operator=_notify,
        )
    return router


@pytest.fixture
def allow_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _stub(
        _self: LLMGuardScanner,
        *,
        text: str,
        channel: str,
        user_id: str,
        actor_is_owner: bool,
        source: str,
    ) -> ScanResult:
        _ = text, channel, user_id, actor_is_owner, source
        return ScanResult(
            verdict=ScanVerdict.allow,
            reasons=(),
            scores={},
            provider_used=None,
            details={},
        )

    monkeypatch.setattr(LLMGuardScanner, "scan_inbound", _stub)


@pytest.mark.asyncio
async def test_multi_related_steer_queues_second_dispatch(
    tmp_path: Path,
    allow_scan: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = asyncio.Event()

    async def slow_run(_sid: str, _cid: str) -> None:
        gate.set()
        await asyncio.sleep(0.25)

    async def classify(_inp: RelatednessInput) -> RelatednessResult:
        return RelatednessResult(label="related_steer", fallback=False)

    conn = _memory_conn()
    router = _router(tmp_path, conn, run_turn=slow_run, classify=classify)
    monkeypatch.setattr(
        router,
        "build_multi_dispatch_hooks",
        lambda **_k: router._test_multi_hooks,
    )
    try:
        t1 = asyncio.create_task(
            router.route_incoming(IncomingMessage(channel="webchat", user_id="m1", text="one")),
        )
        await asyncio.wait_for(gate.wait(), timeout=2.0)
        t2 = asyncio.create_task(
            router.route_incoming(IncomingMessage(channel="webchat", user_id="m1", text="two")),
        )
        await asyncio.sleep(0.03)
        row = conn.execute(
            "SELECT session_id FROM gateway_sessions WHERE scope_key = ?",
            ("webchat:m1",),
        ).fetchone()
        assert row is not None
        depth, running = router.session_manager.dispatch_queue_snapshot(str(row[0]))
        assert running is True
        assert depth >= 1
        await asyncio.gather(t1, t2)
    finally:
        await router.session_manager.drain()
        conn.close()


@pytest.mark.asyncio
async def test_multi_supersede_cancel_aborts_in_flight(
    tmp_path: Path,
    allow_scan: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_run(_sid: str, _cid: str) -> None:
        started.set()
        await release.wait()

    async def classify(_inp: RelatednessInput) -> RelatednessResult:
        return RelatednessResult(label="supersede_cancel", fallback=False)

    conn = _memory_conn()
    router = _router(tmp_path, conn, run_turn=slow_run, classify=classify)
    monkeypatch.setattr(
        router,
        "build_multi_dispatch_hooks",
        lambda **_k: router._test_multi_hooks,
    )
    try:
        t1 = asyncio.create_task(
            router.route_incoming(IncomingMessage(channel="webchat", user_id="mc", text="a")),
        )
        await asyncio.wait_for(started.wait(), timeout=2.0)
        await router.route_incoming(IncomingMessage(channel="webchat", user_id="mc", text="b"))
        release.set()
        await t1
        row = conn.execute(
            "SELECT session_id FROM gateway_sessions WHERE scope_key = ?",
            ("webchat:mc",),
        ).fetchone()
        assert row is not None
        sid = str(row[0])
        assert router.session_manager.was_cancel_superseded_recently(sid)
        tail = unanswered_tail_message_id(conn, sid)
        last_user = conn.execute(
            "SELECT id FROM gateway_messages WHERE session_id = ? AND role = 'user' "
            "ORDER BY id DESC LIMIT 1",
            (sid,),
        ).fetchone()
        assert last_user is not None
        assert tail == int(last_user[0])
    finally:
        release.set()
        await router.session_manager.drain()
        conn.close()


@pytest.mark.asyncio
async def test_multi_classifier_timeout_falls_back_to_steer_with_notice(
    tmp_path: Path,
    allow_scan: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = asyncio.Event()
    notices: list[str] = []

    async def slow_run(_sid: str, _cid: str) -> None:
        gate.set()
        await asyncio.sleep(0.25)

    async def classify(_inp: RelatednessInput) -> RelatednessResult:
        return RelatednessResult(label="related_steer", fallback=True)

    async def notify(_sid: str, line: str) -> None:
        notices.append(line)

    conn = _memory_conn()
    router = _router(tmp_path, conn, run_turn=slow_run, classify=classify)
    hooks = router._test_multi_hooks
    router._test_multi_hooks = MultiDispatchHooks(  # type: ignore[attr-defined]
        classify_busy=hooks.classify_busy,
        spawn_new_task=hooks.spawn_new_task,
        notify_operator=notify,
    )
    monkeypatch.setattr(
        router,
        "build_multi_dispatch_hooks",
        lambda **_k: router._test_multi_hooks,
    )
    try:
        t1 = asyncio.create_task(
            router.route_incoming(IncomingMessage(channel="webchat", user_id="mt", text="one")),
        )
        await asyncio.wait_for(gate.wait(), timeout=2.0)
        t2 = asyncio.create_task(
            router.route_incoming(IncomingMessage(channel="webchat", user_id="mt", text="two")),
        )
        await asyncio.gather(t1, t2)
        assert any("timed out" in n.lower() for n in notices)
    finally:
        await router.session_manager.drain()
        conn.close()


@pytest.mark.asyncio
async def test_multi_limit_exceeded_steers_with_notice(
    tmp_path: Path,
    allow_scan: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = asyncio.Event()
    notices: list[str] = []

    async def slow_run(_sid: str, _cid: str) -> None:
        gate.set()
        await asyncio.sleep(0.25)

    async def classify(_inp: RelatednessInput) -> RelatednessResult:
        return RelatednessResult(label="new_task", fallback=False)

    async def spawn_limit(_sid: str, _cid: str) -> MultiSpawnOutcome:
        return MultiSpawnOutcome.LIMIT_STEER

    async def notify(_sid: str, line: str) -> None:
        notices.append(line)

    conn = _memory_conn()
    router = _router(tmp_path, conn, run_turn=slow_run, classify=classify)
    router._test_multi_hooks = MultiDispatchHooks(  # type: ignore[attr-defined]
        classify_busy=router._test_multi_hooks.classify_busy,
        spawn_new_task=spawn_limit,
        notify_operator=notify,
    )
    monkeypatch.setattr(
        router,
        "build_multi_dispatch_hooks",
        lambda **_k: router._test_multi_hooks,
    )
    try:
        t1 = asyncio.create_task(
            router.route_incoming(IncomingMessage(channel="webchat", user_id="ml", text="one")),
        )
        await asyncio.wait_for(gate.wait(), timeout=2.0)
        t2 = asyncio.create_task(
            router.route_incoming(IncomingMessage(channel="webchat", user_id="ml", text="two")),
        )
        await asyncio.gather(t1, t2)
        assert any("limit" in n.lower() for n in notices)
    finally:
        await router.session_manager.drain()
        conn.close()


@pytest.mark.asyncio
async def test_multi_new_task_spawns_without_queueing(
    tmp_path: Path,
    allow_scan: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = asyncio.Event()
    spawned: list[str] = []

    async def slow_run(_sid: str, _cid: str) -> None:
        gate.set()
        await asyncio.sleep(0.25)

    async def classify(_inp: RelatednessInput) -> RelatednessResult:
        return RelatednessResult(label="new_task", fallback=False)

    async def spawn_ok(_sid: str, cid: str) -> MultiSpawnOutcome:
        spawned.append(cid)
        return MultiSpawnOutcome.SPAWNED

    conn = _memory_conn()
    router = _router(tmp_path, conn, run_turn=slow_run, classify=classify)
    router._test_multi_hooks = MultiDispatchHooks(  # type: ignore[attr-defined]
        classify_busy=router._test_multi_hooks.classify_busy,
        spawn_new_task=spawn_ok,
        notify_operator=router._test_multi_hooks.notify_operator,
    )
    monkeypatch.setattr(
        router,
        "build_multi_dispatch_hooks",
        lambda **_k: router._test_multi_hooks,
    )
    try:
        t1 = asyncio.create_task(
            router.route_incoming(IncomingMessage(channel="webchat", user_id="mn", text="one")),
        )
        await asyncio.wait_for(gate.wait(), timeout=2.0)
        await router.route_incoming(IncomingMessage(channel="webchat", user_id="mn", text="two"))
        await asyncio.sleep(0.03)
        row = conn.execute(
            "SELECT session_id FROM gateway_sessions WHERE scope_key = ?",
            ("webchat:mn",),
        ).fetchone()
        assert row is not None
        depth, _running = router.session_manager.dispatch_queue_snapshot(str(row[0]))
        assert depth == 0
        assert len(spawned) == 1
        await t1
    finally:
        await router.session_manager.drain()
        conn.close()


def test_routing_footer_includes_distinct_subagent_tags() -> None:
    from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
    from sevn.gateway.routing.routing_footer import append_routing_footer

    triage = TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="hi",
        tools=[],
        skills=[],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
    )
    a = append_routing_footer("alpha", triage, subagent_id="a1f3")
    b = append_routing_footer("beta", triage, subagent_id="b2c4")
    assert "⋮a1f3" in a
    assert "⋮b2c4" in b
    assert a != b


def test_config_validate_accepts_multi_queue_fixture() -> None:
    fixture = (
        Path(__file__).resolve().parents[1] / "fixtures" / "config" / "schema_v2_multi_queue.json"
    )
    doc = json.loads(fixture.read_text(encoding="utf-8"))
    validate_workspace_document(doc)
    cfg = parse_workspace_config(doc)
    assert cfg.gateway is not None
    assert cfg.gateway.queue_mode == "multi"
