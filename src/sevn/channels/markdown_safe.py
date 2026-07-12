r"""MarkdownV2 escape pipeline for outbound Telegram text (`PROBLEMS.md` §9).

Module: sevn.channels.markdown_safe
Depends: re

Telegram's MarkdownV2 parser rejects any unescaped occurrence of the 18
reserved characters inside literal text (Bot API ``formatting-options``).
The historical adapter pipeline used the legacy ``Markdown`` (v1) parse
mode and only escaped after a 400 round trip — wasting one Bot API call
per turn for any message containing ``_*[]()~`>#+-=|{}.!`` literals (the
intent footer alone trips ``=`` and ``.``). This module ships the escape
eagerly so the adapter can use ``MarkdownV2`` from the first send and
drop the legacy ``Markdown`` parse mode entirely.

Tradeoff: model-emitted *intentional* Markdown (e.g. ``**bold**``) is
escaped along with everything else, so the user sees literal backslashes.
This is judged acceptable to cut a Bot API round trip per turn; the
``plain`` fallback (no ``parse_mode``) remains as a safety net for any
remaining 400.

Exports:
    escape_markdown_v2 — backslash-escape every reserved char in a string.
    escape_intent_footer — escape a footer body (caller wraps in ``_…_``).

The module-level constant ``MARKDOWN_V2_RESERVED`` (frozenset of the 18
reserved characters) is also part of the public surface; see its
docstring for the inventory.

Examples:
    >>> escape_markdown_v2("hello")
    'hello'
    >>> escape_markdown_v2("a_b")
    'a\\_b'
"""

from __future__ import annotations

import re

# The 18 reserved characters per Telegram Bot API §formatting-options
# (MarkdownV2). The backslash itself is reserved when literal — added to
# the escape pattern so already-escaped input gets passed through unchanged
# only when the caller wants idempotence (see :func:`escape_markdown_v2`).
MARKDOWN_V2_RESERVED: frozenset[str] = frozenset(
    "_*[]()~`>#+-=|{}.!",
)
"""The 18 reserved MarkdownV2 characters.

Examples:
    >>> "_" in MARKDOWN_V2_RESERVED
    True
    >>> len(MARKDOWN_V2_RESERVED)
    18
"""

# Anchored at single chars; backslash is included so callers running the
# escape twice produce ``\\_`` (double-escaped) rather than ``\_`` collapsing
# back. Callers that want idempotence on already-escaped input must check
# beforehand — we do NOT silently skip ``\X`` sequences because the input
# could legitimately contain a literal backslash followed by a reserved
# char (e.g. ``"\."`` in a regex string).
_RESERVED_CHARS_PATTERN = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")


def escape_markdown_v2(text: str) -> str:
    r"""Backslash-escape every MarkdownV2-reserved character in ``text``.

    The adapter uses this as the eager-pre-send transform when sending
    with ``parse_mode=MarkdownV2``. Reserved characters per Telegram Bot
    API ``formatting-options``: ``_*[]()~`>#+-=|{}.!`` plus backslash.

    Args:
        text (str): Outbound text, possibly containing reserved chars.

    Returns:
        str: ``text`` with every reserved character backslash-escaped.

    Examples:
        Plain ASCII passes through unchanged.

        >>> escape_markdown_v2("hello world")
        'hello world'

        Single reserved chars get one backslash each.

        >>> escape_markdown_v2("a_b")
        'a\\_b'
        >>> escape_markdown_v2("(x)")
        '\\(x\\)'

        Sequences of reserved chars are each escaped independently.

        >>> escape_markdown_v2("**bold**")
        '\\*\\*bold\\*\\*'

        The intent-footer pattern (``=``, ``·``, ``.``) — ``·`` is U+00B7
        and is NOT in the reserved set, so it passes through.

        >>> escape_markdown_v2("intent=NEW · conf=0.95")
        'intent\\=NEW · conf\\=0\\.95'

        Backslash itself escapes to a literal backslash so re-running the
        escape on already-escaped input produces a *doubly*-escaped output.
        This is deliberate — callers should escape exactly once.

        >>> escape_markdown_v2("a\\_b")
        'a\\\\\\_b'

        Empty input is a no-op.

        >>> escape_markdown_v2("")
        ''
    """
    return _RESERVED_CHARS_PATTERN.sub(r"\\\1", text)


def escape_intent_footer(footer_body: str) -> str:
    r"""Escape the intent-footer body so it parses inside an italic wrapper.

    Caller wraps the result in ``_…_`` for MarkdownV2 italic. Only the body
    text is escaped — the wrapping underscores are intentional formatting
    and must NOT pass through this function (otherwise italics break).

    Args:
        footer_body (str): The ``intent=… · tier=… · conf=…`` payload, with
            no surrounding underscores.

    Returns:
        str: Footer body with reserved chars escaped.

    Examples:
        >>> escape_intent_footer("intent=NEW_REQUEST · tier=B · conf=0.82")
        'intent\\=NEW\\_REQUEST · tier\\=B · conf\\=0\\.82'

        Empty body is a no-op so callers can compose conditionally.

        >>> escape_intent_footer("")
        ''
    """
    return escape_markdown_v2(footer_body)


__all__ = [
    "MARKDOWN_V2_RESERVED",
    "escape_intent_footer",
    "escape_markdown_v2",
]
