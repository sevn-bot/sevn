"""Inline source (a): agent-answer rows + ``run_turn`` outbound capture (I2.1).

Module: sevn.gateway.telegram_inline_agent
Depends: asyncio, contextvars, html, json, uuid, weakref, sevn.gateway.telegram_inline_base,
    sevn.gateway.telegram_inline_types

Splits the agent-answer turn wiring out of ``telegram_inline_sources`` (finding-4)
and replaces the unguarded ``router.route_outgoing`` monkey-patch with a
context-local capture sink so concurrent inline queries can no longer
cross-contaminate captured text (finding-7).

Exports:
    build_agent_inline_results — source (a) agent answer (operator/allowlist only).
    capture_router_outbound_text — capture first ``route_outgoing`` text during a coroutine.
    make_run_turn_agent_answer_fn — factory for agent-path answers via ``run_turn``.

Examples:
    >>> import inspect
    >>> inspect.iscoroutinefunction(capture_router_outbound_text)
    True
"""

from __future__ import annotations

import asyncio
import html
import json
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from weakref import WeakKeyDictionary

from sevn.gateway.telegram_inline_base import (
    DEFAULT_INLINE_AGENT_TIMEOUT_S,
    DEFAULT_INLINE_MAX_RESULTS_PER_SOURCE,
    AgentAnswerFn,
    InlineBuildContext,
    InlineSourceResult,
    _inline_cfg_from_dispatch,
    _result_id,
    _truncate,
    inline_article_result,
)
from sevn.gateway.telegram_inline_types import InlineSourceKind, inline_source_cache_time

if TYPE_CHECKING:
    from sevn.gateway.channel_router import ChannelRouter

_OUTBOUND_CAPTURE_SINK: ContextVar[list[str] | None] = ContextVar(
    "telegram_inline_outbound_capture_sink",
    default=None,
)


@dataclass
class _OutboundCaptureState:
    """Refcounted ``route_outgoing`` wrapper state for one router (finding-7)."""

    original: Callable[[Any], Awaitable[None]]
    depth: int = 0


_CAPTURE_STATES: WeakKeyDictionary[Any, _OutboundCaptureState] = WeakKeyDictionary()


async def build_agent_inline_results(
    ctx: InlineBuildContext,
    *,
    answer_fn: AgentAnswerFn | None = None,
    timeout_s: float = DEFAULT_INLINE_AGENT_TIMEOUT_S,
    max_results: int = DEFAULT_INLINE_MAX_RESULTS_PER_SOURCE,
) -> InlineSourceResult:
    """Build source (a) agent-answer inline results (D8/D9).

    Agent answers run only when ``dispatch.auth.agent_source_allowed`` is true.
    Latency is bounded by ``timeout_s``; timeouts yield an empty result set.
    A non-positive ``max_results`` suppresses agent rows entirely (finding-14).

    Args:
        ctx (InlineBuildContext): Query + auth context.
        answer_fn (AgentAnswerFn | None): Async answer provider; when ``None``,
            returns no rows.
        timeout_s (float): Wall-clock cap for the agent callback.
        max_results (int): Maximum article rows (typically ``1`` for agent answers).

    Returns:
        InlineSourceResult: Zero or one article row with short ``cache_time``.

    Examples:
        >>> import asyncio
        >>> from sevn.gateway.telegram_inline import build_inline_dispatch_context
        >>> from sevn.config.sections.channels import TelegramInlineConfig
        >>> dispatch = build_inline_dispatch_context(
        ...     "1",
        ...     inline_cfg=TelegramInlineConfig(enabled=True),
        ...     owner_ids=frozenset({"1"}),
        ...     allowed_users=[],
        ... )
        >>> ctx = InlineBuildContext(
        ...     query="hello",
        ...     user_id="1",
        ...     inline_query_id="iq",
        ...     content_root=__import__("pathlib").Path("."),
        ...     dispatch=dispatch,
        ... )
        >>> out = asyncio.run(build_agent_inline_results(ctx, answer_fn=None))
        >>> out.results
        ()
    """
    source: InlineSourceKind = "agent"
    cache_time = inline_source_cache_time(source, _inline_cfg_from_dispatch(ctx.dispatch))
    if max_results <= 0:
        return InlineSourceResult(source=source, cache_time=cache_time, results=())
    if not ctx.dispatch.sources_enabled.get(source, False):
        return InlineSourceResult(source=source, cache_time=cache_time, results=())
    if not ctx.dispatch.auth.agent_source_allowed:
        return InlineSourceResult(source=source, cache_time=cache_time, results=())
    query = ctx.query.strip()
    if not query or answer_fn is None:
        return InlineSourceResult(source=source, cache_time=cache_time, results=())

    try:
        answer = await asyncio.wait_for(answer_fn(query), timeout=timeout_s)
    except TimeoutError:
        return InlineSourceResult(
            source=source,
            cache_time=cache_time,
            results=(),
            error=f"agent answer timed out after {timeout_s}s",
        )
    except Exception as exc:
        return InlineSourceResult(
            source=source,
            cache_time=cache_time,
            results=(),
            error=str(exc),
        )

    if not answer or not str(answer).strip():
        return InlineSourceResult(source=source, cache_time=cache_time, results=())

    text = str(answer).strip()
    title = _truncate(text.splitlines()[0], 128)
    description = _truncate(text, 256)
    body = html.escape(text)
    row = inline_article_result(
        result_id=_result_id(source, 0, ctx.inline_query_id),
        title=title,
        description=description,
        message_text=f"<pre>{body}</pre>",
        markdown_source=text,
    )
    return InlineSourceResult(source=source, cache_time=cache_time, results=(row,))


async def capture_router_outbound_text(
    router: ChannelRouter,
    coro: Awaitable[None],
) -> str | None:
    """Run *coro* and return the first non-empty ``route_outgoing`` text captured.

    Capture is context-local: a single transparent wrapper is installed on
    ``router.route_outgoing`` and shared across concurrent captures, while each
    call records into its own :class:`~contextvars.ContextVar` sink. This
    prevents the cross-contamination the previous per-call monkey-patch allowed
    (finding-7); the wrapper is removed once the last active capture finishes.

    Args:
        router (ChannelRouter): Gateway router whose ``route_outgoing`` is wrapped.
        coro (Awaitable[None]): Turn dispatch coroutine (typically ``run_turn``).

    Returns:
        str | None: First outbound assistant-visible text, if any.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(capture_router_outbound_text)
        True
    """
    sink: list[str] = []
    state = _CAPTURE_STATES.get(router)
    if state is None:
        state = _OutboundCaptureState(original=router.route_outgoing)

        async def _capture_outgoing(msg: Any) -> None:
            current = _OUTBOUND_CAPTURE_SINK.get()
            text = getattr(msg, "text", None)
            if current is not None and isinstance(text, str) and text.strip():
                current.append(text.strip())
            await state.original(msg)

        _CAPTURE_STATES[router] = state
        router.route_outgoing = _capture_outgoing  # type: ignore[method-assign]
    state.depth += 1
    token = _OUTBOUND_CAPTURE_SINK.set(sink)
    try:
        await coro
    finally:
        _OUTBOUND_CAPTURE_SINK.reset(token)
        state.depth -= 1
        if state.depth <= 0:
            router.route_outgoing = state.original  # type: ignore[assignment]
            _CAPTURE_STATES.pop(router, None)
    return sink[0] if sink else None


def make_run_turn_agent_answer_fn(
    router: ChannelRouter,
    *,
    channel: str,
    user_id: str,
    scope_key: str | None = None,
    timeout_s: float = DEFAULT_INLINE_AGENT_TIMEOUT_S,
) -> AgentAnswerFn:
    """Return an :data:`AgentAnswerFn` that drives ``router._run_turn`` (I2.1).

    Persists the inline query as a user message, runs the wired agent turn, and
    captures the first outbound reply text. Intended for I3 wiring — unit tests
    should inject a simpler :data:`AgentAnswerFn` mock.

    Args:
        router (ChannelRouter): Bootstrapped gateway router with ``run_turn`` wired.
        channel (str): Channel key for the ephemeral session (``telegram``).
        user_id (str): Telegram user id owning the session.
        scope_key (str | None): Optional session scope override.
        timeout_s (float): Wall-clock cap for the agent turn.

    Returns:
        AgentAnswerFn: Async callable accepting the inline query string.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(make_run_turn_agent_answer_fn)
        True
    """
    scope = scope_key or f"{channel}:{user_id}"

    async def _answer(query: str) -> str | None:
        run_turn = router._run_turn
        if run_turn is None:
            return None
        sessions = router._sessions
        session_id = await sessions.ensure_session(
            scope_key=scope,
            channel=channel,
            user_id=user_id,
        )
        turn_id = uuid.uuid4().hex
        await sessions.add_message(
            session_id,
            role="user",
            kind="message",
            content=query,
            visible_to_llm=1,
            status="sent",
            turn_id=turn_id,
            metadata_blob=json.dumps({"inline_query": True}),
        )

        async def _dispatch() -> None:
            await run_turn(session_id, turn_id)

        try:
            return await asyncio.wait_for(
                capture_router_outbound_text(router, _dispatch()),
                timeout=timeout_s,
            )
        except TimeoutError:
            return None

    return _answer


__all__ = [
    "build_agent_inline_results",
    "capture_router_outbound_text",
    "make_run_turn_agent_answer_fn",
]
