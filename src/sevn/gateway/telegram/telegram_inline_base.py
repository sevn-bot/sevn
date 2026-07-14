"""Shared inline-source primitives, payload types, and result containers (I2).

Module: sevn.gateway.telegram.telegram_inline_base
Depends: dataclasses, html, pathlib, typing, uuid, sevn.config.sections.channels,
    sevn.gateway.telegram.telegram_inline_types

Holds the value types and small helpers shared by the per-source builders
(``telegram_inline_agent``, ``telegram_inline_printing_press``,
``telegram_inline_sources``). Splitting these out of the former 998-line
``telegram_inline_sources`` keeps each source module focused (finding-4).

Exports:
    InlineArticleResult — typed Telegram ``article`` inline result payload (finding-18).
    InlineBuildContext — inputs for one inline query build pass.
    InlineInputMessageContent — typed ``input_message_content`` sub-payload (finding-18).
    InlineSourceResult — one source's ``answerInlineQuery`` result rows + cache TTL.
    inline_article_result — build one Telegram ``article`` inline result dict.

Examples:
    >>> inline_article_result(
    ...     result_id="a:0", title="Hi", description="d", message_text="x"
    ... )["type"]
    'article'
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict, cast

from sevn.config.sections.channels import TelegramInlineConfig
from sevn.gateway.telegram.telegram_inline_types import (
    InlineDispatchContext,
    InlineSourceKind,
    inline_source_cache_time,
)

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig

DEFAULT_INLINE_AGENT_TIMEOUT_S = 15.0
DEFAULT_INLINE_MAX_RESULTS_PER_SOURCE = 5
DEFAULT_INLINE_MAX_TOTAL_RESULTS = 20

AgentAnswerFn = Callable[[str], Awaitable[str | None]]
PrintingPressRunnerFn = Callable[[str, list[str], float], dict[str, Any]]

InlineResultDict = dict[str, Any]


class InlineInputMessageContent(TypedDict):
    """Telegram ``input_message_content`` payload for an inline result (finding-18)."""

    message_text: str
    parse_mode: str


class InlineArticleResult(TypedDict, total=False):
    """Telegram ``article`` inline result payload for ``answerInlineQuery`` (finding-18).

    ``total=False`` because optional internal hints (``_inline_markdown``,
    ``_viewer_spec``) are attached only when present; the Bot API ignores the
    ``_``-prefixed keys, which I3 strips before sending.
    """

    type: str
    id: str
    title: str
    description: str
    input_message_content: InlineInputMessageContent
    _inline_markdown: str
    _viewer_spec: dict[str, Any]


@dataclass(frozen=True)
class InlineBuildContext:
    """Inputs for building inline results for one ``inline_query`` (I2).

    Attributes:
        query: Raw inline query text from Telegram.
        user_id: Requesting Telegram user id (string form).
        inline_query_id: Telegram ``inline_query.id`` (for stable result ids).
        content_root: Workspace content root (``sevn.json`` parent).
        dispatch: Auth, cache, and per-source toggles from I1.
        second_brain_scope: Optional second-brain scope override.
        workspace: Parsed workspace config (second-brain subtree, etc.).
    """

    query: str
    user_id: str
    inline_query_id: str
    content_root: Path
    dispatch: InlineDispatchContext
    second_brain_scope: str | None = None
    workspace: WorkspaceConfig | None = None


@dataclass(frozen=True)
class InlineSourceResult:
    """One content source's inline rows plus ``cache_time`` (I2).

    Attributes:
        source: Content source identifier (D9).
        cache_time: Seconds for ``answerInlineQuery.cache_time``.
        results: Telegram inline result dicts (typically ``type=article``).
        error: Set when the builder failed but was isolated (I2.5).
    """

    source: InlineSourceKind
    cache_time: int
    results: tuple[InlineResultDict, ...] = field(default_factory=tuple)
    error: str | None = None


def inline_article_result(
    *,
    result_id: str,
    title: str,
    description: str,
    message_text: str,
    parse_mode: str = "HTML",
    markdown_source: str | None = None,
) -> InlineResultDict:
    """Build one Telegram ``article`` inline result dict.

    Args:
        result_id (str): Unique result id (<= 64 bytes for Bot API).
        title (str): Result title shown in the inline list.
        description (str): Result subtitle / description.
        message_text (str): Body sent when the result is chosen.
        parse_mode (str): Telegram parse mode for ``message_text``. Defaults to ``HTML``.
        markdown_source (str | None): Optional Markdown/plain source for I3 rich upgrade.

    Returns:
        InlineResultDict: Bot API inline result object.

    Examples:
        >>> r = inline_article_result(
        ...     result_id="a:0",
        ...     title="Hi",
        ...     description="d",
        ...     message_text="<b>x</b>",
        ...     markdown_source="**x**",
        ... )
        >>> r["type"]
        'article'
    """
    safe_title = title.strip() or "Result"
    safe_desc = description.strip()
    body = message_text.strip() or safe_title
    row: InlineArticleResult = {
        "type": "article",
        "id": result_id[:64],
        "title": safe_title[:256],
        "description": safe_desc[:256],
        "input_message_content": {
            "message_text": body[:4096],
            "parse_mode": parse_mode,
        },
    }
    if markdown_source and markdown_source.strip():
        row["_inline_markdown"] = markdown_source.strip()
    return cast("InlineResultDict", row)


def _truncate(text: str, limit: int) -> str:
    """Return ``text`` trimmed to ``limit`` characters with an ellipsis suffix.

    Args:
        text (str): Input string.
        limit (int): Maximum returned length including ellipsis when truncated.

    Returns:
        str: Trimmed string.

    Examples:
        >>> _truncate("hello world", 20)
        'hello world'
    """
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _result_id(source: InlineSourceKind, index: int, inline_query_id: str) -> str:
    """Build a stable Telegram inline ``result_id`` for one row.

    Args:
        source (InlineSourceKind): Content source identifier.
        index (int): Row index within the source block.
        inline_query_id (str): Telegram inline query id.

    Returns:
        str: Unique result id (<= 64 bytes).

    Examples:
        >>> _result_id("agent", 0, "iq-1").startswith("agent:0:")
        True
    """
    digest = uuid.uuid5(uuid.NAMESPACE_OID, f"{inline_query_id}:{source}:{index}").hex[:10]
    return f"{source}:{index}:{digest}"


def _inline_cfg_from_dispatch(dispatch: InlineDispatchContext) -> TelegramInlineConfig:
    """Reconstruct a minimal ``TelegramInlineConfig`` for cache-time lookup.

    Args:
        dispatch (InlineDispatchContext): Inline dispatch context from I1.

    Returns:
        TelegramInlineConfig: Config carrying only cache TTL fields.

    Examples:
        >>> from sevn.gateway.telegram.telegram_inline import build_inline_dispatch_context
        >>> from sevn.config.sections.channels import TelegramInlineConfig
        >>> dispatch = build_inline_dispatch_context(
        ...     "1",
        ...     inline_cfg=TelegramInlineConfig(enabled=True),
        ...     owner_ids=frozenset(),
        ...     allowed_users=[],
        ... )
        >>> _inline_cfg_from_dispatch(dispatch).cache_time_agent
        10
    """
    return TelegramInlineConfig(
        cache_time_agent=dispatch.cache_time_agent,
        cache_time_static=dispatch.cache_time_static,
    )


def _empty_source_result(
    source: InlineSourceKind, dispatch: InlineDispatchContext
) -> InlineSourceResult:
    """Return an empty result block for a disabled or skipped source.

    Args:
        source (InlineSourceKind): Content source identifier.
        dispatch (InlineDispatchContext): Inline dispatch context.

    Returns:
        InlineSourceResult: Empty rows with the correct per-source ``cache_time``.

    Examples:
        >>> from sevn.gateway.telegram.telegram_inline import build_inline_dispatch_context
        >>> from sevn.config.sections.channels import TelegramInlineConfig
        >>> dispatch = build_inline_dispatch_context(
        ...     "1",
        ...     inline_cfg=TelegramInlineConfig(enabled=True),
        ...     owner_ids=frozenset(),
        ...     allowed_users=[],
        ... )
        >>> _empty_source_result("agent", dispatch).results
        ()
    """
    return InlineSourceResult(
        source=source,
        cache_time=inline_source_cache_time(source, _inline_cfg_from_dispatch(dispatch)),
        results=(),
    )
