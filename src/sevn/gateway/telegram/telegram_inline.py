"""Telegram inline-query router (I1 plumbing; I2 sources; I3 answer assembly).

Module: sevn.gateway.telegram.telegram_inline
Depends: typing, loguru, sevn.channels.telegram_capabilities,
    sevn.gateway.telegram.telegram_inline_types, sevn.gateway.telegram.telegram_inline_dispatch,
    sevn.gateway.telegram.telegram_inline_sources

Router + dispatch orchestration for Telegram inline updates. Shared value types
and config/auth helpers live in :mod:`sevn.gateway.telegram.telegram_inline_types`; pure
answer-assembly helpers in :mod:`sevn.gateway.telegram.telegram_inline_dispatch`. Both are
re-exported here for the stable ``telegram_inline`` import surface (gateway/tests).
The I2 source builders are imported at module top (no E402 cycle) and remain the
test patch point for :func:`dispatch_telegram_inline_query`.

Exports:
    handle_chosen_inline_result_feedback — trace chosen-result feedback (I3.3).
    maybe_emit_botfather_inline_warning — one-shot runtime operator warning (I3.4).
    dispatch_telegram_inline_query — build sources + answer one inline query (I3).
    try_route_telegram_inline — non-turn inbound branch from ``route_incoming``.

Re-exports (stable import surface for gateway/tests; see ``__all__``): the
``telegram_inline_types`` value/config helpers and ``telegram_inline_dispatch``
answer-assembly helpers, plus the I2 source builders from
``telegram_inline_sources``.

Examples:
    >>> "inline_query" in telegram_allowed_updates(
    ...     __import__(
    ...         "sevn.config.sections.channels",
    ...         fromlist=["TelegramInlineConfig"],
    ...     ).TelegramInlineConfig(enabled=True)
    ... )
    True
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, cast

from loguru import logger

from sevn.agent.tracing.sink import SYSTEM_TURN_ID
from sevn.channels.telegram_capabilities import RichCapability
from sevn.config.sections.channels import TelegramInlineConfig
from sevn.gateway.telegram.telegram_inline_dispatch import (
    build_answer_inline_query_payload,
    build_inline_input_message_content,
    compute_inline_answer_cache_time,
    dedupe_inline_results,
    is_inline_botfather_setup_error,
    paginate_inline_results,
    parse_inline_result_offset,
    sanitize_inline_results_for_api,
    upgrade_inline_results_for_capability,
)
from sevn.gateway.telegram.telegram_inline_sources import (
    InlineBuildContext,
    build_all_inline_source_results,
    make_run_turn_agent_answer_fn,
    merge_inline_query_results,
)
from sevn.gateway.telegram.telegram_inline_types import (
    DEFAULT_INLINE_PAGE_SIZE,
    INLINE_BOTFATHER_SETUP_NOTE,
    INLINE_MODULE_VERSION,
    InlineAuthContext,
    InlineDispatchContext,
    InlineSourceKind,
    build_inline_dispatch_context,
    inline_source_cache_time,
    inline_user_may_use_agent_source,
    resolve_inline_config,
    telegram_allowed_updates,
)

if TYPE_CHECKING:
    from sevn.gateway.channel_router import ChannelRouter, IncomingMessage


async def maybe_emit_botfather_inline_warning(router: ChannelRouter, data: dict[str, Any]) -> None:
    """Emit a one-shot runtime warning when BotFather inline toggles are likely off (I3.4).

    Operator-deferred manual setup (``/setinline``, ``/setinlinefeedback``,
    ``/setinlinegeo``) is documented in Final — this trace nudges the operator at runtime.

    Args:
        router (ChannelRouter): Gateway router with trace wired.
        data (dict[str, Any]): Parsed ``answerInlineQuery`` response.

    Returns:
        None

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(maybe_emit_botfather_inline_warning)
        True
    """
    if not is_inline_botfather_setup_error(data):
        return
    if router._inline_botfather_warned:
        return
    router._inline_botfather_warned = True
    logger.warning("telegram_inline_botfather_setup_required note={}", INLINE_BOTFATHER_SETUP_NOTE)
    await router._emit(
        kind="gateway.telegram.inline.botfather_setup",
        session_id="",
        turn_id=SYSTEM_TURN_ID,
        status="operator_deferred",
        attrs={"note": INLINE_BOTFATHER_SETUP_NOTE},
    )


async def handle_chosen_inline_result_feedback(
    router: ChannelRouter,
    msg: IncomingMessage,
    *,
    correlation_id: str,
) -> None:
    """Record ``chosen_inline_result`` feedback without PII in trace attrs (I3.3).

    Args:
        router (ChannelRouter): Gateway router with trace wired.
        msg (IncomingMessage): Parsed chosen-inline envelope.
        correlation_id (str): Correlation id for the inbound update.

    Returns:
        None

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(handle_chosen_inline_result_feedback)
        True
    """
    md = msg.metadata if isinstance(msg.metadata, dict) else {}
    await router._emit(
        kind="gateway.telegram.inline.chosen_result",
        session_id="",
        turn_id=correlation_id,
        status="feedback",
        attrs={
            "result_id": md.get("inline_result_id"),
            "query_len": len(msg.text or ""),
            "has_location": bool(md.get("inline_location")),
        },
    )


async def dispatch_telegram_inline_query(
    router: ChannelRouter,
    msg: IncomingMessage,
    *,
    inline_cfg: TelegramInlineConfig,
    dispatch_ctx: InlineDispatchContext,
) -> dict[str, Any]:
    """Build four-source results and send ``answerInlineQuery`` (I3.1-I3.2).

    Args:
        router (ChannelRouter): Bootstrapped gateway router.
        msg (IncomingMessage): Parsed ``inline_query`` envelope.
        inline_cfg (TelegramInlineConfig): Resolved inline config.
        dispatch_ctx (InlineDispatchContext): Auth/cache/source toggles.

    Returns:
        dict[str, Any]: Parsed Bot API response from ``answerInlineQuery`` (may be empty).

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(dispatch_telegram_inline_query)
        True
    """
    md = msg.metadata if isinstance(msg.metadata, dict) else {}
    inline_query_id = str(md.get("inline_query_id") or "")
    offset = str(md.get("inline_offset") or "")
    if not inline_query_id:
        return {}

    adapter = router._adapters.get("telegram")
    if adapter is None:
        return {}

    answer_fn = None
    if dispatch_ctx.auth.agent_source_allowed and router._run_turn is not None:
        answer_fn = make_run_turn_agent_answer_fn(
            router,
            channel="telegram",
            user_id=msg.user_id,
        )

    build_ctx = InlineBuildContext(
        query=msg.text or "",
        user_id=msg.user_id,
        inline_query_id=inline_query_id,
        content_root=router._content_root,
        dispatch=dispatch_ctx,
        workspace=router._workspace,
    )
    source_blocks = await build_all_inline_source_results(build_ctx, answer_fn=answer_fn)
    merged = merge_inline_query_results(source_blocks)
    merged = dedupe_inline_results(merged)
    page, next_offset = paginate_inline_results(merged, offset=offset)

    rich_capable = getattr(adapter, "rich_capability", RichCapability.NOT_CAPABLE) is (
        RichCapability.CAPABLE
    )
    page = upgrade_inline_results_for_capability(page, rich_capable=rich_capable)
    from sevn.gateway.webapp.webapp_viewer import attach_inline_viewer_launch_buttons

    page = attach_inline_viewer_launch_buttons(
        page,
        workspace=router._workspace,
        conn=router._sessions.connection,
        user_id=msg.user_id,
    )
    cache_time = compute_inline_answer_cache_time(
        page,
        cache_time_agent=dispatch_ctx.cache_time_agent,
        cache_time_static=dispatch_ctx.cache_time_static,
    )
    api_results = sanitize_inline_results_for_api(page)

    correlation_id = str(md.get("__correlation_id") or msg.user_id)
    await router._emit(
        kind="gateway.telegram.inline.answer",
        session_id="",
        turn_id=correlation_id,
        status="sending",
        attrs={
            "result_count": len(api_results),
            "cache_time": cache_time,
            "is_personal": dispatch_ctx.auth.is_personal,
            "rich_capable": rich_capable,
            "next_offset": next_offset or None,
            "source_errors": [
                {"source": b.source, "error": b.error} for b in source_blocks if b.error
            ],
        },
    )

    answer = getattr(adapter, "answer_inline_query", None)
    if not callable(answer):
        return {}
    answer_inline_query = cast(
        "Callable[..., Awaitable[dict[str, Any]]]",
        answer,
    )
    response = await answer_inline_query(
        inline_query_id,
        results=api_results,
        cache_time=cache_time,
        is_personal=dispatch_ctx.auth.is_personal,
        next_offset=next_offset,
    )
    await maybe_emit_botfather_inline_warning(
        router, response if isinstance(response, dict) else {}
    )
    status = "ok" if isinstance(response, dict) and response.get("ok") else "error"
    await router._emit(
        kind="gateway.telegram.inline.answer",
        session_id="",
        turn_id=correlation_id,
        status=status,
        attrs={
            "result_count": len(api_results),
            "ok": bool(isinstance(response, dict) and response.get("ok")),
        },
    )
    return response if isinstance(response, dict) else {}


def _telegram_inline_config_from_router(router: ChannelRouter) -> TelegramInlineConfig:
    """Load resolved inline config from the router workspace.

    Args:
        router (ChannelRouter): Gateway router with workspace config.

    Returns:
        TelegramInlineConfig: Normalised ``channels.telegram.inline`` block.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_telegram_inline_config_from_router)
        True
    """
    ch = router._workspace.channels
    tg = ch.telegram if ch is not None else None
    return resolve_inline_config(tg.inline if tg is not None else None)


def _telegram_allowed_users_from_router(router: ChannelRouter) -> list[int]:
    """Return ``channels.telegram.allowed_users`` as ints from the router workspace.

    Args:
        router (ChannelRouter): Gateway router with workspace config.

    Returns:
        list[int]: Telegram user ids allowed to DM the bot.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_telegram_allowed_users_from_router)
        True
    """
    ch = router._workspace.channels
    tg = ch.telegram if ch is not None else None
    if tg is None or not tg.allowed_users:
        return []
    return [int(x) for x in tg.allowed_users]


async def try_route_telegram_inline(router: ChannelRouter, msg: IncomingMessage) -> bool:
    """Handle Telegram inline updates as a non-turn branch (``specs/17-gateway`` §4.3).

    Parses tags on ``IncomingMessage.metadata`` from
    :meth:`sevn.channels.telegram.TelegramAdapter._parse_inline_query` /
    ``_parse_chosen_inline_result``. Does not persist a conversation turn or
    invoke the agent spine for chosen-result feedback; inline queries call
    ``answerInlineQuery`` via :func:`dispatch_telegram_inline_query` (I3).

    Args:
        router (ChannelRouter): Gateway router with workspace + trace wired.
        msg (IncomingMessage): Adapter-parsed inbound envelope.

    Returns:
        bool: ``True`` when the message was an inline update and was handled.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(try_route_telegram_inline)
        True
    """
    md = msg.metadata if isinstance(msg.metadata, dict) else {}
    if msg.channel != "telegram":
        return False
    inline_cfg = _telegram_inline_config_from_router(router)
    if not inline_cfg.enabled:
        return False
    correlation_id = str(md.get("__correlation_id") or msg.user_id)
    allowed_users = _telegram_allowed_users_from_router(router)

    if md.get("is_chosen_inline_result"):
        if not inline_cfg.feedback:
            return False
        await handle_chosen_inline_result_feedback(
            router,
            msg,
            correlation_id=correlation_id,
        )
        return True

    if not md.get("is_inline_query"):
        return False

    ctx = build_inline_dispatch_context(
        msg.user_id,
        inline_cfg=inline_cfg,
        owner_ids=router._owner_ids,
        allowed_users=allowed_users,
    )
    await router._emit(
        kind="gateway.telegram.inline.query",
        session_id="",
        turn_id=correlation_id,
        status="routed",
        attrs={
            "query_len": len(msg.text or ""),
            "inline_query_id": md.get("inline_query_id"),
            "agent_source_allowed": ctx.auth.agent_source_allowed,
            "is_personal": ctx.auth.is_personal,
            "cache_time_agent": ctx.cache_time_agent,
            "cache_time_static": ctx.cache_time_static,
            "sources_enabled": dict(ctx.sources_enabled),
        },
    )
    await dispatch_telegram_inline_query(
        router,
        msg,
        inline_cfg=inline_cfg,
        dispatch_ctx=ctx,
    )
    return True


__all__ = [
    "DEFAULT_INLINE_PAGE_SIZE",
    "INLINE_BOTFATHER_SETUP_NOTE",
    "INLINE_MODULE_VERSION",
    "InlineAuthContext",
    "InlineBuildContext",
    "InlineDispatchContext",
    "InlineSourceKind",
    "build_all_inline_source_results",
    "build_answer_inline_query_payload",
    "build_inline_dispatch_context",
    "build_inline_input_message_content",
    "compute_inline_answer_cache_time",
    "dedupe_inline_results",
    "dispatch_telegram_inline_query",
    "handle_chosen_inline_result_feedback",
    "inline_source_cache_time",
    "inline_user_may_use_agent_source",
    "is_inline_botfather_setup_error",
    "maybe_emit_botfather_inline_warning",
    "paginate_inline_results",
    "parse_inline_result_offset",
    "resolve_inline_config",
    "sanitize_inline_results_for_api",
    "telegram_allowed_updates",
    "try_route_telegram_inline",
    "upgrade_inline_results_for_capability",
]
