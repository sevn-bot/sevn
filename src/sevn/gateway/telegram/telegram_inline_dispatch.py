"""Inline answer-assembly helpers: offset, dedupe, paginate, content (I3.1-I3.2).

Module: sevn.gateway.telegram.telegram_inline_dispatch
Depends: html, re, typing, loguru, sevn.channels.telegram_rich,
    sevn.gateway.telegram.telegram_inline_types

Pure (router-free) building blocks for one ``answerInlineQuery`` page. The
``telegram_inline`` router imports these and orchestrates them in
``dispatch_telegram_inline_query``; keeping them here shrinks the router module
(finding-3) without touching the source-builder test patch points.

Exports:
    parse_inline_result_offset — parse Telegram ``offset`` string to a start index.
    dedupe_inline_results — drop duplicate rows by ``id`` and title/description.
    compute_inline_answer_cache_time — merged ``cache_time`` for one answer page (D10).
    build_inline_input_message_content — ``InputRichMessageContent`` or HTML (D10).
    upgrade_inline_results_for_capability — apply rich/HTML content to result rows.
    paginate_inline_results — slice merged rows with ``next_offset``.
    sanitize_inline_results_for_api — strip internal keys before Bot API send.
    build_answer_inline_query_payload — assemble ``answerInlineQuery`` body (I3.1).
    is_inline_botfather_setup_error — classify BotFather ``/setinline`` setup failures.

Examples:
    >>> parse_inline_result_offset("20")
    20
"""

from __future__ import annotations

import html
import re
from typing import Any

from loguru import logger

from sevn.channels.telegram_capabilities import bot_api_error_description
from sevn.channels.telegram_rich import build_input_rich_message_markdown
from sevn.gateway.telegram.telegram_inline_types import DEFAULT_INLINE_PAGE_SIZE

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def parse_inline_result_offset(offset: str) -> int:
    """Parse Telegram inline ``offset`` to a zero-based start index (I3.1).

    Args:
        offset (str): Raw ``inline_query.offset`` string from Telegram.

    Returns:
        int: Non-negative slice start index.

    Examples:
        >>> parse_inline_result_offset("")
        0
        >>> parse_inline_result_offset("20")
        20
        >>> parse_inline_result_offset("bad")
        0
    """
    text = offset.strip()
    if not text:
        return 0
    try:
        return max(0, int(text))
    except ValueError:
        return 0


def dedupe_inline_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop duplicate inline rows by ``id`` and title/description fingerprint (I3.1).

    Args:
        results (list[dict[str, Any]]): Merged inline result dicts in D9 order.

    Returns:
        list[dict[str, Any]]: Deduped list preserving first occurrence order.

    Examples:
        >>> a = {"type": "article", "id": "1", "title": "A", "description": "d"}
        >>> b = {"type": "article", "id": "2", "title": "A", "description": "d"}
        >>> dedupe_inline_results([a, b])
        [{'type': 'article', 'id': '1', 'title': 'A', 'description': 'd'}]
    """
    seen_ids: set[str] = set()
    seen_fp: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for row in results:
        rid = str(row.get("id") or "")
        if rid and rid in seen_ids:
            continue
        title = str(row.get("title") or "").strip().lower()
        desc = str(row.get("description") or "").strip().lower()
        fp = (title, desc)
        if title and fp in seen_fp:
            continue
        if rid:
            seen_ids.add(rid)
        if title:
            seen_fp.add(fp)
        out.append(row)
    return out


def compute_inline_answer_cache_time(
    page_results: list[dict[str, Any]],
    *,
    cache_time_agent: int,
    cache_time_static: int,
) -> int:
    """Pick merged ``answerInlineQuery.cache_time`` for one results page (D10).

    Agent rows on the page force the short agent TTL; otherwise use the static TTL.

    Args:
        page_results (list[dict[str, Any]]): Inline rows being returned now.
        cache_time_agent (int): Short TTL seconds for agent answers.
        cache_time_static (int): Longer TTL for static sources.

    Returns:
        int: ``cache_time`` value for ``answerInlineQuery``.

    Examples:
        >>> compute_inline_answer_cache_time(
        ...     [{"id": "agent:0:abc"}],
        ...     cache_time_agent=10,
        ...     cache_time_static=300,
        ... )
        10
        >>> compute_inline_answer_cache_time(
        ...     [{"id": "second_brain:0:abc"}],
        ...     cache_time_agent=10,
        ...     cache_time_static=300,
        ... )
        300
    """
    for row in page_results:
        rid = str(row.get("id") or "")
        if rid.startswith("agent:"):
            return cache_time_agent
    return cache_time_static


def _markdown_for_rich_upgrade(row: dict[str, Any]) -> str:
    """Return Markdown/plain source text for rich inline content upgrade.

    Args:
        row (dict[str, Any]): Inline result dict, optionally with ``_inline_markdown``.

    Returns:
        str: Markdown or plain text suitable for
        :func:`build_input_rich_message_markdown`.

    Examples:
        >>> _markdown_for_rich_upgrade({"_inline_markdown": "**hi**"})
        '**hi**'
    """
    internal = row.get("_inline_markdown")
    if isinstance(internal, str) and internal.strip():
        return internal.strip()
    imc = row.get("input_message_content")
    if not isinstance(imc, dict):
        return ""
    text = imc.get("message_text")
    if not isinstance(text, str):
        return ""
    plain = _HTML_TAG_RE.sub("", text)
    return html.unescape(plain).strip()


def build_inline_input_message_content(
    message_text: str,
    *,
    rich_capable: bool,
    markdown_source: str | None = None,
) -> dict[str, Any]:
    """Build ``input_message_content`` as rich or HTML (I3.2, D10).

    Args:
        message_text (str): HTML body for the legacy path.
        rich_capable (bool): When ``True`` and rendering succeeds, emit
            ``InputRichMessageContent`` (``rich_message`` key).
        markdown_source (str | None): Optional Markdown/plain source for rich render.

    Returns:
        dict[str, Any]: Bot API ``InputMessageContent`` object.

    Examples:
        >>> html_body = build_inline_input_message_content(
        ...     "<b>x</b>",
        ...     rich_capable=False,
        ... )
        >>> html_body["parse_mode"]
        'HTML'
        >>> rich_body = build_inline_input_message_content(
        ...     "<b>x</b>",
        ...     rich_capable=True,
        ...     markdown_source="**x**",
        ... )
        >>> "rich_message" in rich_body
        True
    """
    if rich_capable:
        md = markdown_source if markdown_source else _HTML_TAG_RE.sub("", message_text)
        md = html.unescape(md).strip() or message_text
        try:
            rich_message = build_input_rich_message_markdown(md)
            return {"rich_message": rich_message}
        except Exception:
            logger.debug("inline_rich_content_fallback_to_html")
    return {
        "message_text": message_text[:4096],
        "parse_mode": "HTML",
    }


def upgrade_inline_results_for_capability(
    results: list[dict[str, Any]],
    *,
    rich_capable: bool,
) -> list[dict[str, Any]]:
    """Apply ``InputRichMessageContent`` or HTML to each result row (I3.2).

    Args:
        results (list[dict[str, Any]]): Inline article rows from I2 builders.
        rich_capable (bool): When ``True``, attempt rich render per row.

    Returns:
        list[dict[str, Any]]: Rows with upgraded ``input_message_content``.

    Examples:
        >>> row = {
        ...     "type": "article",
        ...     "id": "1",
        ...     "title": "t",
        ...     "description": "d",
        ...     "input_message_content": {"message_text": "<b>x</b>", "parse_mode": "HTML"},
        ...     "_inline_markdown": "**x**",
        ... }
        >>> upgraded = upgrade_inline_results_for_capability([row], rich_capable=False)
        >>> upgraded[0]["input_message_content"]["parse_mode"]
        'HTML'
    """
    if not results:
        return []
    out: list[dict[str, Any]] = []
    for row in results:
        patched = dict(row)
        imc = patched.get("input_message_content")
        message_text = ""
        if isinstance(imc, dict):
            raw = imc.get("message_text")
            if isinstance(raw, str):
                message_text = raw
        patched["input_message_content"] = build_inline_input_message_content(
            message_text,
            rich_capable=rich_capable,
            markdown_source=_markdown_for_rich_upgrade(row),
        )
        out.append(patched)
    return out


def paginate_inline_results(
    results: list[dict[str, Any]],
    *,
    offset: str,
    page_size: int = DEFAULT_INLINE_PAGE_SIZE,
) -> tuple[list[dict[str, Any]], str]:
    """Slice merged inline rows and compute ``next_offset`` (I3.1).

    Args:
        results (list[dict[str, Any]]): Full merged inline result list.
        offset (str): Telegram ``inline_query.offset`` cursor.
        page_size (int): Maximum rows per ``answerInlineQuery`` page.

    Returns:
        tuple[list[dict[str, Any]], str]: ``(page_rows, next_offset)`` where
        ``next_offset`` is empty when no further pages exist.

    Examples:
        >>> rows = [{"id": str(i)} for i in range(3)]
        >>> page, nxt = paginate_inline_results(rows, offset="", page_size=2)
        >>> len(page)
        2
        >>> nxt
        '2'
    """
    start = parse_inline_result_offset(offset)
    end = start + max(1, page_size)
    page = results[start:end]
    next_offset = str(end) if end < len(results) else ""
    return page, next_offset


def sanitize_inline_results_for_api(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip internal ``_`` keys from inline rows before Bot API send (I3.1).

    Args:
        results (list[dict[str, Any]]): Inline result dicts.

    Returns:
        list[dict[str, Any]]: API-safe copies.

    Examples:
        >>> sanitize_inline_results_for_api([{"id": "1", "_inline_markdown": "x"}])
        [{'id': '1'}]
    """
    cleaned: list[dict[str, Any]] = []
    for row in results:
        cleaned.append({k: v for k, v in row.items() if not str(k).startswith("_")})
    return cleaned


def build_answer_inline_query_payload(
    *,
    inline_query_id: str,
    results: list[dict[str, Any]],
    cache_time: int,
    is_personal: bool,
    next_offset: str = "",
) -> dict[str, Any]:
    """Assemble one ``answerInlineQuery`` JSON body (I3.1).

    Args:
        inline_query_id (str): Telegram ``inline_query.id``.
        results (list[dict[str, Any]]): Sanitized inline result rows (≤ 50).
        cache_time (int): Client cache TTL in seconds.
        is_personal (bool): ``is_personal`` flag (D8).
        next_offset (str): Pagination cursor when more rows exist.

    Returns:
        dict[str, Any]: Bot API request body for ``answerInlineQuery``.

    Examples:
        >>> body = build_answer_inline_query_payload(
        ...     inline_query_id="iq-1",
        ...     results=[{"type": "article", "id": "1"}],
        ...     cache_time=10,
        ...     is_personal=True,
        ... )
        >>> body["inline_query_id"]
        'iq-1'
        >>> body["is_personal"]
        True
    """
    payload: dict[str, Any] = {
        "inline_query_id": inline_query_id.strip(),
        "results": results[:50],
        "cache_time": max(0, int(cache_time)),
        "is_personal": bool(is_personal),
    }
    offset = next_offset.strip()
    if offset:
        payload["next_offset"] = offset
    return payload


def is_inline_botfather_setup_error(data: dict[str, Any]) -> bool:
    """Return whether a Bot API body indicates missing BotFather inline setup (I3.4).

    Args:
        data (dict[str, Any]): Parsed ``answerInlineQuery`` response.

    Returns:
        bool: ``True`` when inline mode is likely disabled in BotFather.

    Examples:
        >>> is_inline_botfather_setup_error(
        ...     {"ok": False, "description": "Forbidden: bot can't be used in inline mode"}
        ... )
        True
        >>> is_inline_botfather_setup_error({"ok": True})
        False
    """
    desc = bot_api_error_description(data)
    if desc is None:
        return False
    markers = (
        "inline mode",
        "inline queries",
        "bot_inline",
        "can't be used in inline",
        "cannot be used in inline",
    )
    return any(marker in desc for marker in markers)


__all__ = [
    "build_answer_inline_query_payload",
    "build_inline_input_message_content",
    "compute_inline_answer_cache_time",
    "dedupe_inline_results",
    "is_inline_botfather_setup_error",
    "paginate_inline_results",
    "parse_inline_result_offset",
    "sanitize_inline_results_for_api",
    "upgrade_inline_results_for_capability",
]
