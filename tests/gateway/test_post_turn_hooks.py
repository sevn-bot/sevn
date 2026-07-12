"""Tests for gateway post-turn hook registry (CW-1)."""

from __future__ import annotations

import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sevn.gateway.post_turn_hooks import (
    PostTurnContext,
    clear_post_turn_hooks,
    register_post_turn_hook,
    run_post_turn_hooks,
)


@pytest.fixture(autouse=True)
def _clean_hooks() -> None:
    clear_post_turn_hooks()
    yield
    clear_post_turn_hooks()


def _ctx(*, terminal_status: str = "ok") -> PostTurnContext:
    router = MagicMock()
    conn = sqlite3.connect(":memory:")
    trace = MagicMock()
    return PostTurnContext(
        router=router,
        conn=conn,
        trace=trace,
        session_id="sess-1",
        correlation_id="turn-1",
        terminal_status=terminal_status,
        turn_wall_ns=1_000_000_000,
    )


@pytest.mark.asyncio
async def test_run_post_turn_hooks_core_cleanup() -> None:
    ctx = _ctx()
    with (
        patch("sevn.gateway.agent_turn._emit_gateway_span", new_callable=AsyncMock) as emit,
        patch("sevn.gateway.post_turn_hooks.record_turn_finished") as record,
    ):
        await run_post_turn_hooks(ctx)
    ctx.router.cancel_telegram_typing.assert_called_once_with("sess-1")
    emit.assert_awaited_once()
    assert emit.await_args.kwargs["kind"] == "gateway.turn.complete"
    record.assert_called_once()


@pytest.mark.asyncio
async def test_registered_hooks_run_in_priority_order() -> None:
    order: list[str] = []

    async def hook_a(_ctx: PostTurnContext) -> None:
        order.append("a")

    async def hook_b(_ctx: PostTurnContext) -> None:
        order.append("b")

    register_post_turn_hook("b", hook_b, priority=10)
    register_post_turn_hook("a", hook_a, priority=0)

    with (
        patch("sevn.gateway.agent_turn._emit_gateway_span", new_callable=AsyncMock),
        patch("sevn.gateway.post_turn_hooks.record_turn_finished"),
    ):
        await run_post_turn_hooks(_ctx())

    assert order == ["a", "b"]


@pytest.mark.asyncio
async def test_hook_failure_is_isolated() -> None:
    seen: list[str] = []

    async def fail(_ctx: PostTurnContext) -> None:
        msg = "boom"
        raise RuntimeError(msg)

    async def after(_ctx: PostTurnContext) -> None:
        seen.append("after")

    register_post_turn_hook("fail", fail, priority=0)
    register_post_turn_hook("after", after, priority=1)

    with (
        patch("sevn.gateway.agent_turn._emit_gateway_span", new_callable=AsyncMock),
        patch("sevn.gateway.post_turn_hooks.record_turn_finished"),
    ):
        await run_post_turn_hooks(_ctx())

    assert seen == ["after"]


def test_register_post_turn_hook_rejects_duplicate_name() -> None:
    async def _noop(_ctx: PostTurnContext) -> None:
        return None

    register_post_turn_hook("dup", _noop)
    with pytest.raises(ValueError, match="already registered"):
        register_post_turn_hook("dup", _noop)
