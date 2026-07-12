"""Rich-send decision gate and guaranteed legacy fallback (D3-D4, finding-2 split).

Module: sevn.channels.telegram_rich_fallback
Depends: re, enum, typing, collections.abc, sevn.channels.telegram_capabilities,
    sevn.channels.telegram_format, sevn.config.defaults, sevn.config.sections.channels

Exports:
    RichFallbackReason — enum of rich-to-legacy degrade causes for tracing.
    resolve_rich_config — normalise ``TelegramRichConfig`` with defaults.
    is_reply_rich_worthy — heuristic rich-block detector for ``auto`` mode.
    should_use_rich — capability + config gate (D3).
    send_with_rich_fallback — rich send wrapper with guaranteed legacy degrade (D4).

Examples:
    >>> from sevn.channels.telegram_rich_fallback import is_reply_rich_worthy
    >>> is_reply_rich_worthy("plain text")
    False
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Literal

from sevn.channels.telegram_capabilities import RichCapability
from sevn.channels.telegram_format import _TABLE_BLOCK_RE, to_telegram
from sevn.config.defaults import DEFAULT_TELEGRAM_RICH_MODE
from sevn.config.sections.channels import TelegramRichConfig

_DETAILS_RE = re.compile(r"<details[\s>]", re.IGNORECASE)
_MATH_BLOCK_RE = re.compile(r"\$\$[\s\S]+?\$\$")
_MATH_INLINE_RE = re.compile(r"(?<!\$)\$(?!\$)[^\$\n]+?\$(?!\$)")
_MEDIA_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
_SLIDESHOW_MARKER_RE = re.compile(
    r"(?:<!--\s*sevn:slideshow\s*-->|\bsevn-slideshow\b|RichBlockSlideshow)",
    re.IGNORECASE,
)
_COLLAGE_MARKER_RE = re.compile(
    r"(?:<!--\s*sevn:collage\s*-->|\bsevn-collage\b|RichBlockCollage)",
    re.IGNORECASE,
)


class RichFallbackReason(StrEnum):
    """Reason a rich send degraded to the legacy ``to_telegram()`` path (D4)."""

    NOT_CAPABLE = "not_capable"
    SEND_FAILED = "send_failed"
    PARSE_ERROR = "parse_error"
    API_CLIENT_ERROR = "api_client_error"
    RICH_UNAVAILABLE = "rich_unavailable"


def resolve_rich_config(cfg: TelegramRichConfig | None) -> TelegramRichConfig:
    """Return ``cfg`` or a default ``TelegramRichConfig`` (``mode=auto``).

    Args:
        cfg (TelegramRichConfig | None): Workspace ``channels.telegram.rich`` block.

    Returns:
        TelegramRichConfig: Normalised rich config with defaults applied.

    Examples:
        >>> resolve_rich_config(None).mode
        'auto'
    """
    if cfg is None:
        return TelegramRichConfig(mode=DEFAULT_TELEGRAM_RICH_MODE)
    return cfg


def is_reply_rich_worthy(reply: str) -> bool:
    """Return whether *reply* contains blocks that benefit from Bot API 10.1 rich messages.

    Heuristic detector for ``auto`` mode (tables, details, math, media markers,
    slideshow/collage markers). Simple emphasis-only Markdown is not rich-worthy.

    Args:
        reply (str): Agent Markdown reply body.

    Returns:
        bool: ``True`` when a structured rich block is likely present.

    Examples:
        >>> is_reply_rich_worthy("plain text")
        False
        >>> is_reply_rich_worthy("| A | B |\\n|---|---|\\n| 1 | 2 |")
        True
    """
    if not reply or not reply.strip():
        return False
    if _TABLE_BLOCK_RE.search(reply):
        return True
    if _DETAILS_RE.search(reply):
        return True
    if _MATH_BLOCK_RE.search(reply) or _MATH_INLINE_RE.search(reply):
        return True
    if _SLIDESHOW_MARKER_RE.search(reply) or _COLLAGE_MARKER_RE.search(reply):
        return True
    return bool(_MEDIA_IMAGE_RE.search(reply))


def should_use_rich(
    reply: str,
    capability: RichCapability,
    cfg: TelegramRichConfig | None,
    *,
    streaming_active: bool = False,
) -> bool:
    """Decide whether the outbound path should attempt rich rendering (D3).

    ``off`` never uses rich. ``all`` uses rich when capable. ``auto`` uses rich when
    capable and the reply is rich-worthy or streaming is active.

    Args:
        reply (str): Agent Markdown reply body.
        capability (RichCapability): Cached Bot API probe verdict.
        cfg (TelegramRichConfig | None): ``channels.telegram.rich`` settings.
        streaming_active (bool, optional): Whether a streaming draft is in flight.
            Defaults to ``False``.

    Returns:
        bool: ``True`` when the rich send path should be attempted.

    Examples:
        >>> should_use_rich("| A |\\n|---|---|\\n| 1 |", RichCapability.CAPABLE, None)
        True
        >>> should_use_rich("hello", RichCapability.CAPABLE, TelegramRichConfig(mode="off"))
        False
    """
    rich_cfg = resolve_rich_config(cfg)
    if rich_cfg.mode == "off":
        return False
    if capability is not RichCapability.CAPABLE:
        return False
    if rich_cfg.mode == "all":
        return True
    return streaming_active or is_reply_rich_worthy(reply)


async def _emit_rich_fallback(
    emit_trace: Callable[..., Awaitable[None]] | None,
    *,
    reason: RichFallbackReason,
    parse_mode: str,
) -> None:
    """Emit ``channel.telegram.rich_fallback`` when configured.

    Args:
        emit_trace (Callable[..., Awaitable[None]] | None): Trace sink callback.
        reason (RichFallbackReason): Degrade classifier.
        parse_mode (str): Legacy parse mode used for fallback.

    Examples:
        >>> import asyncio
        >>> asyncio.run(
        ...     _emit_rich_fallback(None, reason=RichFallbackReason.SEND_FAILED, parse_mode="HTML")
        ... )
    """
    if emit_trace is None:
        return
    await emit_trace(
        kind="channel.telegram.rich_fallback",
        status="degraded",
        attrs={"reason": reason.value, "parse_mode": parse_mode},
    )


async def send_with_rich_fallback[T](
    *,
    reply: str,
    capability: RichCapability,
    rich_cfg: TelegramRichConfig | None,
    parse_mode: Literal["HTML", "MarkdownV2"],
    legacy_send: Callable[[str], Awaitable[T]],
    rich_send: Callable[[], Awaitable[T]] | None = None,
    emit_trace: Callable[..., Awaitable[None]] | None = None,
    streaming_active: bool = False,
) -> T:
    """Attempt rich send when gated on; degrade to ``to_telegram()`` on any failure (D4).

    When :func:`should_use_rich` is false the legacy path runs without a fallback trace.
    Rich failures emit ``channel.telegram.rich_fallback`` with :class:`RichFallbackReason`.

    Args:
        reply (str): Agent Markdown reply body.
        capability (RichCapability): Cached Bot API probe verdict.
        rich_cfg (TelegramRichConfig | None): ``channels.telegram.rich`` settings.
        parse_mode (Literal["HTML", "MarkdownV2"]): Legacy Telegram parse mode.
        legacy_send (Callable[[str], Awaitable[T]]): Send converted legacy body.
        rich_send (Callable[[], Awaitable[T]] | None, optional): Rich send callable.
            Defaults to ``None`` (renderer not wired yet).
        emit_trace (Callable[..., Awaitable[None]] | None, optional): Trace sink
            compatible with :meth:`TelegramAdapter._emit_trace`. Defaults to ``None``.
        streaming_active (bool, optional): Streaming draft flag for ``auto`` mode.
            Defaults to ``False``.

    Returns:
        T: Result from the successful send path.

    Examples:
        >>> import asyncio
        >>> async def _legacy(body: str) -> str:
        ...     return body
        >>> asyncio.run(
        ...     send_with_rich_fallback(
        ...         reply="hello",
        ...         capability=RichCapability.NOT_CAPABLE,
        ...         rich_cfg=None,
        ...         parse_mode="HTML",
        ...         legacy_send=_legacy,
        ...     )
        ... )
        'hello'
    """
    legacy_body = to_telegram(reply, parse_mode)
    if not should_use_rich(
        reply,
        capability,
        rich_cfg,
        streaming_active=streaming_active,
    ):
        return await legacy_send(legacy_body)

    if rich_send is None:
        await _emit_rich_fallback(
            emit_trace,
            reason=RichFallbackReason.RICH_UNAVAILABLE,
            parse_mode=parse_mode,
        )
        return await legacy_send(legacy_body)

    try:
        return await rich_send()
    except ValueError as exc:
        reason = RichFallbackReason.PARSE_ERROR
        if "parse" not in str(exc).lower():
            reason = RichFallbackReason.SEND_FAILED
        await _emit_rich_fallback(emit_trace, reason=reason, parse_mode=parse_mode)
        return await legacy_send(legacy_body)
    except Exception as exc:
        reason = RichFallbackReason.SEND_FAILED
        exc_name = type(exc).__name__.lower()
        if "parse" in str(exc).lower():
            reason = RichFallbackReason.PARSE_ERROR
        elif "connect" in exc_name or "timeout" in exc_name or "http" in exc_name:
            reason = RichFallbackReason.API_CLIENT_ERROR
        if capability is not RichCapability.CAPABLE:
            reason = RichFallbackReason.NOT_CAPABLE
        await _emit_rich_fallback(emit_trace, reason=reason, parse_mode=parse_mode)
        return await legacy_send(legacy_body)
