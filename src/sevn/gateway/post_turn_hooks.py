"""Ordered post-turn hook registry for gateway agent turns.

Module: sevn.gateway.post_turn_hooks
Depends: sevn.gateway.channel_router, sevn.gateway.turn_metadata

Exports:
    PostTurnContext — immutable turn-end context passed to hooks.
    register_post_turn_hook — append a named callback (lanes #3, #5, #6).
    clear_post_turn_hooks — reset registry (tests only).
    run_post_turn_hooks — core turn-end cleanup + registered hooks.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import time_ns

from loguru import logger

from sevn.agent.tracing.sink import TraceSink
from sevn.gateway.channel_router import ChannelRouter
from sevn.gateway.turn_metadata import record_turn_finished

PostTurnHook = Callable[["PostTurnContext"], Awaitable[None]]

_HOOKS: list[tuple[int, str, PostTurnHook]] = []


@dataclass(frozen=True, slots=True)
class PostTurnContext:
    """Context passed to every post-turn hook after ``_run_guarded`` completes."""

    router: ChannelRouter
    conn: sqlite3.Connection
    trace: TraceSink
    session_id: str
    correlation_id: str
    terminal_status: str
    turn_wall_ns: int


def register_post_turn_hook(name: str, hook: PostTurnHook, *, priority: int = 0) -> None:
    """Register a post-turn callback; lanes must use this instead of editing ``finally``.

    Args:
        name (str): Stable hook id for logs (must be unique).
        hook (PostTurnHook): Async callback receiving :class:`PostTurnContext`.
        priority (int): Lower runs first among registered hooks (after core cleanup).

    Examples:
        >>> async def _noop(_ctx: PostTurnContext) -> None:
        ...     return None
        >>> register_post_turn_hook("test", _noop, priority=10)
        >>> any(entry[1] == "test" for entry in _HOOKS)
        True
    """
    if not name.strip():
        msg = "post_turn hook name must be non-empty"
        raise ValueError(msg)
    if any(existing_name == name for _, existing_name, _ in _HOOKS):
        msg = f"post_turn hook already registered: {name}"
        raise ValueError(msg)
    _HOOKS.append((priority, name, hook))


def clear_post_turn_hooks() -> None:
    """Remove all registered hooks (test isolation only).

    Examples:
        >>> clear_post_turn_hooks()
        >>> _HOOKS
        []
    """
    _HOOKS.clear()


async def run_post_turn_hooks(ctx: PostTurnContext) -> None:
    """Run core turn-end cleanup, then registered hooks in priority order.

    Core cleanup (formerly inline in ``agent_turn._run_guarded`` ``finally``):
    cancel Telegram typing, emit ``gateway.turn.complete``, stamp turn metadata.

    Registered hooks run afterward; each failure is logged and isolated.

    Args:
        ctx (PostTurnContext): Turn-end state from ``_run_guarded``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(run_post_turn_hooks)
        True
    """
    ctx.router.cancel_telegram_typing(ctx.session_id)
    elapsed_ms = max(1, int((time_ns() - ctx.turn_wall_ns) / 1_000_000))
    from sevn.gateway.agent_turn import _emit_gateway_span

    turn_attrs: dict[str, object] = {"elapsed_ms": elapsed_ms, "latency_ms": float(elapsed_ms)}
    _HIGH_LATENCY_MS = 5000
    if elapsed_ms >= _HIGH_LATENCY_MS:
        turn_attrs["high_latency"] = True
        turn_attrs["high_latency_threshold_ms"] = _HIGH_LATENCY_MS
    await _emit_gateway_span(
        ctx.trace,
        kind="gateway.turn.complete",
        session_id=ctx.session_id,
        turn_id=ctx.correlation_id,
        status=ctx.terminal_status,
        attrs=turn_attrs,
    )
    try:
        import asyncio

        await asyncio.to_thread(
            record_turn_finished,
            ctx.conn,
            turn_id=ctx.correlation_id,
            status=ctx.terminal_status,
        )
    except Exception:
        logger.exception(
            "agent_turn_record_turn_finished_failed session_id={} turn_id={}",
            ctx.session_id,
            ctx.correlation_id,
        )

    for _priority, hook_name, hook in sorted(_HOOKS, key=lambda row: (row[0], row[1])):
        try:
            await hook(ctx)
        except Exception:
            logger.exception("post_turn_hook_failed name={}", hook_name)


__all__ = [
    "PostTurnContext",
    "PostTurnHook",
    "clear_post_turn_hooks",
    "register_post_turn_hook",
    "run_post_turn_hooks",
]
