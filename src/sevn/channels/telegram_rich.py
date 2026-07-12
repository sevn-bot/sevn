"""Rich-message renderer facade — stable public surface over the split modules (R1-R3).

Module: sevn.channels.telegram_rich
Depends: sevn.channels.telegram_rich_parse, sevn.channels.telegram_rich_map,
    sevn.channels.telegram_rich_validate, sevn.channels.telegram_rich_fallback

The 1.5k-line renderer monolith was split (finding-2) into focused modules:
``telegram_rich_parse`` (Markdown → AST), ``telegram_rich_map`` (AST → Bot API JSON),
``telegram_rich_validate`` (shape + serialize), and ``telegram_rich_fallback``
(decision gate + guaranteed legacy degrade). This module re-exports the public
surface so existing imports stay stable.

Re-exported (defined in the split modules): ``RichFallbackReason``,
``resolve_rich_config``, ``is_reply_rich_worthy``, ``should_use_rich``,
``send_with_rich_fallback`` (telegram_rich_fallback); ``markdown_to_ast`` and the
``Ast*`` node types (telegram_rich_parse); ``inline_to_rich_json``,
``inline_to_rich_text``, ``ast_to_input_rich_message`` (telegram_rich_map);
``validate_rich_message_shape``, ``serialize_input_rich_message``
(telegram_rich_validate).

Exports:
    rich_module_ready — return whether the rich renderer package is importable.
    build_input_rich_message_markdown — Markdown → ``InputRichMessage`` wire payload
        (``{"markdown": …}``); use this for outbound ``rich_message`` fields.
    render_markdown_to_rich_message — Markdown → block-tree ``RichMessage`` (the
        *received* representation, for parsing/fixtures — not a wire payload).

Examples:
    >>> from sevn.channels.telegram_rich import build_input_rich_message_markdown
    >>> build_input_rich_message_markdown("**hi**")
    {'markdown': '**hi**'}
"""

from __future__ import annotations

from typing import Any

from sevn.channels.telegram_rich_fallback import RichFallbackReason as RichFallbackReason
from sevn.channels.telegram_rich_fallback import is_reply_rich_worthy as is_reply_rich_worthy
from sevn.channels.telegram_rich_fallback import resolve_rich_config as resolve_rich_config
from sevn.channels.telegram_rich_fallback import send_with_rich_fallback as send_with_rich_fallback
from sevn.channels.telegram_rich_fallback import should_use_rich as should_use_rich
from sevn.channels.telegram_rich_map import MAX_RICH_BLOCKS as MAX_RICH_BLOCKS
from sevn.channels.telegram_rich_map import ast_to_input_rich_message as ast_to_input_rich_message
from sevn.channels.telegram_rich_map import inline_to_rich_json as inline_to_rich_json
from sevn.channels.telegram_rich_map import inline_to_rich_text as inline_to_rich_text
from sevn.channels.telegram_rich_parse import _COLLAGE_BLOCK_RE as _COLLAGE_BLOCK_RE
from sevn.channels.telegram_rich_parse import _MEDIA_IMAGE_LINE_RE as _MEDIA_IMAGE_LINE_RE
from sevn.channels.telegram_rich_parse import _SLIDESHOW_BLOCK_RE as _SLIDESHOW_BLOCK_RE
from sevn.channels.telegram_rich_parse import _TABLE_SEPARATOR_RE as _TABLE_SEPARATOR_RE
from sevn.channels.telegram_rich_parse import MAX_INLINE_DEPTH as MAX_INLINE_DEPTH
from sevn.channels.telegram_rich_parse import AstAnchor as AstAnchor
from sevn.channels.telegram_rich_parse import AstBlock as AstBlock
from sevn.channels.telegram_rich_parse import AstBlockquote as AstBlockquote
from sevn.channels.telegram_rich_parse import AstCollage as AstCollage
from sevn.channels.telegram_rich_parse import AstDetails as AstDetails
from sevn.channels.telegram_rich_parse import AstDivider as AstDivider
from sevn.channels.telegram_rich_parse import AstFooter as AstFooter
from sevn.channels.telegram_rich_parse import AstHeading as AstHeading
from sevn.channels.telegram_rich_parse import AstInline as AstInline
from sevn.channels.telegram_rich_parse import AstInlineCode as AstInlineCode
from sevn.channels.telegram_rich_parse import AstInlineLink as AstInlineLink
from sevn.channels.telegram_rich_parse import AstInlineMath as AstInlineMath
from sevn.channels.telegram_rich_parse import AstInlineMention as AstInlineMention
from sevn.channels.telegram_rich_parse import AstInlineStyled as AstInlineStyled
from sevn.channels.telegram_rich_parse import AstInlineText as AstInlineText
from sevn.channels.telegram_rich_parse import AstList as AstList
from sevn.channels.telegram_rich_parse import AstListItem as AstListItem
from sevn.channels.telegram_rich_parse import AstMathBlock as AstMathBlock
from sevn.channels.telegram_rich_parse import AstMedia as AstMedia
from sevn.channels.telegram_rich_parse import AstParagraph as AstParagraph
from sevn.channels.telegram_rich_parse import AstPreformatted as AstPreformatted
from sevn.channels.telegram_rich_parse import AstPullQuote as AstPullQuote
from sevn.channels.telegram_rich_parse import AstSlideshow as AstSlideshow
from sevn.channels.telegram_rich_parse import AstTable as AstTable
from sevn.channels.telegram_rich_parse import AstThinking as AstThinking
from sevn.channels.telegram_rich_parse import _parse_inline as _parse_inline
from sevn.channels.telegram_rich_parse import _parse_table_alignments as _parse_table_alignments
from sevn.channels.telegram_rich_parse import markdown_to_ast as markdown_to_ast
from sevn.channels.telegram_rich_validate import (
    MAX_RICH_MESSAGE_JSON_BYTES as MAX_RICH_MESSAGE_JSON_BYTES,
)
from sevn.channels.telegram_rich_validate import (
    serialize_input_rich_message as serialize_input_rich_message,
)
from sevn.channels.telegram_rich_validate import (
    validate_rich_message_shape as validate_rich_message_shape,
)

RICH_MODULE_VERSION = "0.3.0-r3"


def rich_module_ready() -> bool:
    """Return ``True`` when the rich renderer package is importable.

    Returns:
        bool: Always ``True`` once R2 renderer core is present.

    Examples:
        >>> rich_module_ready()
        True
    """
    return True


def build_input_rich_message_markdown(
    markdown: str,
    *,
    is_rtl: bool = False,
    skip_entity_detection: bool = False,
) -> dict[str, Any]:
    """Build a Bot API 10.1 ``InputRichMessage`` wire payload from agent Markdown.

    The Bot API parses Rich Markdown **server-side**: an ``InputRichMessage`` sent
    over the wire is ``{"markdown": <str>}`` (or ``{"html": <str>}``), *not* a
    pre-rendered ``blocks`` tree. The block/``RichText`` classes describe the
    *received* :class:`RichMessage` representation, not what a bot sends. Sending a
    ``blocks`` payload makes Telegram see neither ``html`` nor ``markdown`` and
    reject it with ``Bad Request: rich message must be non-empty``.

    See https://core.telegram.org/bots/api#inputrichmessage and the Rich Markdown
    grammar at https://core.telegram.org/bots/api#rich-message-formatting-options
    (GFM-compatible, so agent Markdown passes through directly).

    Args:
        markdown (str): Agent Markdown reply body (Rich Markdown / GFM).
        is_rtl (bool): Set ``is_rtl`` when the message must render right-to-left.
        skip_entity_detection (bool): Skip auto-detection of URLs, mentions, etc.

    Returns:
        dict[str, Any]: ``InputRichMessage`` JSON-ready dict (``{"markdown": …}``).

    Raises:
        ValueError: When ``markdown`` is empty or whitespace-only (Telegram rejects
            an empty rich message).

    Examples:
        >>> build_input_rich_message_markdown("**hi**")
        {'markdown': '**hi**'}
    """
    if not markdown or not markdown.strip():
        raise ValueError("InputRichMessage markdown must be non-empty")
    payload: dict[str, Any] = {"markdown": markdown}
    if is_rtl:
        payload["is_rtl"] = True
    if skip_entity_detection:
        payload["skip_entity_detection"] = True
    return payload


def render_markdown_to_rich_message(markdown: str) -> dict[str, Any]:
    """Render Markdown to a validated block-tree ``RichMessage`` dict.

    Note:
        This produces the *received* ``RichMessage`` block representation and must
        **not** be used as a ``sendRichMessage``/``editMessageText`` wire payload —
        use :func:`build_input_rich_message_markdown` for outbound ``rich_message``
        fields.
        Retained for parsing/inspection and fixtures.

    Args:
        markdown (str): Agent Markdown reply body.

    Returns:
        dict[str, Any]: ``RichMessage`` block dict.

    Examples:
        >>> render_markdown_to_rich_message("plain")["blocks"][0]["type"]
        'paragraph'
    """
    message = ast_to_input_rich_message(markdown_to_ast(markdown))
    return validate_rich_message_shape(message)
