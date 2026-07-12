"""Wave 3 cancel supersession tests (P9)."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig

from sevn.agent.executors.b_types import BTurnOutcome, ChannelPayload, ResolvedTierBModel
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import ChatCompletionsTransport
from sevn.gateway import agent_turn as agent_turn_mod
from sevn.gateway.agent_turn import _is_triager_opener_ack, build_agent_run_turn
from sevn.gateway.session_manager import SessionManager
from tests.gateway.test_agent_turn_escalation import (
    _E2E_STUB,
    _CaptureTelegram,
    _CapturingTraceSink,
    _memory_conn,
    _router_bundle,
)


def test_is_triager_opener_ack() -> None:
    assert _is_triager_opener_ack("On it — running the full pipeline.")
    assert not _is_triager_opener_ack("Here is the full registry list:")


def test_session_manager_cancel_supersession_markers() -> None:
    mgr = SessionManager(_memory_conn())
    sid = "s-cancel-suppress"
    assert not mgr.was_cancel_superseded_recently(sid)
    mgr._cancel_superseded_at[sid] = time.monotonic()
    assert mgr.was_cancel_superseded_recently(sid)
    assert mgr.consume_cancel_supersession(sid)
    assert not mgr.was_cancel_superseded_recently(sid)


@pytest.mark.asyncio
async def test_cancel_interrupt_suppressed_when_replacement_queued(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P9: rapid cancel-mode supersession skips the 'interrupted' terminal."""
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv("SEVN_TRIAGER_STUB_FIXTURE_PATH", str(_E2E_STUB))

    cancel_event = asyncio.Event()

    async def _slow_run_b_turn(**_kwargs: Any) -> BTurnOutcome:
        cancel_event.set()
        await asyncio.sleep(3600)
        return BTurnOutcome(
            status="completed",
            final_messages=(ChannelPayload(text="unreachable"),),
            escalation=None,
            rounds_used=1,
        )

    async def _bundle_factory(_ws: WorkspaceConfig) -> ResolvedTierBModel:
        transport = ChatCompletionsTransport(proxy_base_url="http://w3-cancel.test.invalid")
        return ResolvedTierBModel(
            model_id="openai/gpt-b",
            transport=transport,
            budget=ModelBudget(model_id="openai/gpt-b", regime=BudgetRegime.FREE_LOCAL),
        )

    monkeypatch.setattr(agent_turn_mod, "run_b_turn", _slow_run_b_turn)

    cap_trace = _CapturingTraceSink()
    conn = _memory_conn()
    router, ws, layout = _router_bundle(tmp_path, conn)
    cap = _CaptureTelegram()
    router.register_adapter(cap)
    run_turn = build_agent_run_turn(
        router,
        conn,
        ws,
        layout,
        cap_trace,  # type: ignore[arg-type]
        tier_b_bundle_factory=_bundle_factory,
        runtime_bindings=MagicMock(),
    )
    session_id: str | None = None
    try:
        session_id = await router.session_manager.ensure_session(
            scope_key="telegram:u-w3-suppress",
            channel="telegram",
            user_id="u-w3-suppress",
        )
        await router.session_manager.add_message(
            session_id,
            role="user",
            kind="message",
            content="first message",
            visible_to_llm=1,
            status="sent",
            metadata_blob=json.dumps({"chat_id": 9903, "message_id": 1}),
            turn_id="t-w3-1",
        )
        await router.session_manager.enqueue_dispatch(
            session_id,
            correlation_id="corr-w3-1",
            queue_mode="queue",
            dispatch=run_turn,
        )
        await asyncio.wait_for(cancel_event.wait(), timeout=5.0)

        await router.session_manager.add_message(
            session_id,
            role="user",
            kind="message",
            content="replacement message",
            visible_to_llm=1,
            status="sent",
            metadata_blob=json.dumps({"chat_id": 9903, "message_id": 2}),
            turn_id="t-w3-2",
        )
        await router.session_manager.enqueue_dispatch(
            session_id,
            correlation_id="corr-w3-2",
            queue_mode="cancel",
            dispatch=run_turn,
        )
        await asyncio.sleep(0.2)

        assert not any(
            "interrupted" in t.lower() or "next message" in t.lower() for t in cap.sent_texts
        ), f"unexpected interrupt message in: {cap.sent_texts}"
        no_answer_events = [e for e in cap_trace.events if e.kind == "gateway.executor.no_answer"]
        assert not any(
            e.attrs.get("reason") == "cancelled_by_new_message" for e in no_answer_events
        )
    finally:
        import contextlib

        for task in (
            *router.session_manager._worker_tasks.values(),
            *router.session_manager._active_dispatch_task.values(),
        ):
            if not task.done():
                task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await asyncio.sleep(0.05)
        conn.close()
