"""Markdown → rich-message AST parser (R1-R3, finding-2 parse split).

Module: sevn.channels.telegram_rich_parse
Depends: re, dataclasses, typing, collections.abc, sevn.channels.telegram_format,
    sevn.channels.telegram_markdown_regions, sevn.channels.telegram_rich_blocks

Exports:
    AstInlineText — plain text inline leaf.
    AstInlineStyled — styled inline span (bold, italic, …).
    AstInlineCode — inline code span.
    AstInlineLink — Markdown link ``[label](url)``.
    AstInlineMath — inline LaTeX ``$…$``.
    AstInlineMention — Telegram-style ``@username`` mention.
    AstParagraph — paragraph block.
    AstHeading — ATX heading block.
    AstDivider — horizontal rule block.
    AstListItem — list item with optional task checkbox.
    AstList — ordered, unordered, or task list block.
    AstPreformatted — fenced code block.
    AstBlockquote — block quotation block.
    AstTable — GFM pipe table with optional trailing caption paragraph.
    AstDetails — HTML ``<details>`` block.
    AstMathBlock — block LaTeX ``$$…$$``.
    AstMedia — photo/video/audio/voice/animation media block.
    AstSlideshow — multi-slide media container.
    AstCollage — grouped media container.
    AstPullQuote — pull-quote lines (``>>>`` prefix).
    AstFooter — footer block (``<!-- sevn:footer -->`` region).
    AstAnchor — block-level anchor target.
    AstThinking — collapsible reasoning block.
    markdown_to_ast — Markdown → internal AST using ``telegram_format`` regex source (D6).

Examples:
    >>> from sevn.channels.telegram_rich_parse import markdown_to_ast
    >>> markdown_to_ast("**hi**")[0].inlines[0].kind
    'bold'
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from sevn.channels.telegram_format import (
    _BOLD_RE,
    _FENCE_RE,
    _INLINE_CODE_RE,
    _ITALIC_STAR_RE,
    _ITALIC_USCORE_RE,
    _LINK_RE,
    _SPOILER_RE,
    _STRIKE_RE,
    _TABLE_BLOCK_RE,
    _UNDERLINE_RE,
)
from sevn.channels.telegram_markdown_regions import (
    COLLAGE_BLOCK_RE,
    MEDIA_IMAGE_LINE_RE,
    SLIDESHOW_BLOCK_RE,
    TABLE_SEPARATOR_RE,
    parse_table_alignments,
)
from sevn.channels.telegram_rich_blocks import MediaKind, parse_media_directive_attrs

MAX_INLINE_DEPTH = 32

_MATH_BLOCK_STASH_RE = re.compile(r"\$\$([\s\S]+?)\$\$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
_DIVIDER_RE = re.compile(r"^(\*{3,}|-{3,}|_{3,})\s*$")
_UNORDERED_LIST_RE = re.compile(r"^[\-*+]\s+(?!\[[ xX]\])(.+)$")
_TASK_LIST_RE = re.compile(r"^[\-*+]\s+\[([ xX])\]\s+(.+)$")
_ORDERED_LIST_RE = re.compile(r"^\d+\.\s+(.+)$")
_BLOCKQUOTE_RE = re.compile(r"^\s*(?:\*\*)?>\s?(.*)$")
_MATH_INLINE_PARSE_RE = re.compile(r"(?<!\$)\$(?!\$)([^\$\n]+?)\$(?!\$)")
_MENTION_RE = re.compile(r"@([A-Za-z0-9_]{4,})")
_PULL_QUOTE_LINE_RE = re.compile(r"^>>>\s?(.*)$")
_MEDIA_DIRECTIVE_RE = re.compile(
    r"<!--\s*sevn:(photo|video|audio|voice|animation)\s+([^>]+?)\s*-->",
    re.IGNORECASE,
)
_THINKING_BLOCK_RE = re.compile(
    r"<!--\s*sevn:thinking\s*-->(.*?)<!--\s*/sevn:thinking\s*-->",
    re.DOTALL | re.IGNORECASE,
)
_FOOTER_BLOCK_RE = re.compile(
    r"<!--\s*sevn:footer\s*-->(.*?)<!--\s*/sevn:footer\s*-->",
    re.DOTALL | re.IGNORECASE,
)
_ANCHOR_DIRECTIVE_RE = re.compile(
    r"<!--\s*sevn:anchor\s+(?:id=([^\s>]+)|([^\s>]+))\s*-->",
    re.IGNORECASE,
)

_MEDIA_IMAGE_LINE_RE = MEDIA_IMAGE_LINE_RE
_SLIDESHOW_BLOCK_RE = SLIDESHOW_BLOCK_RE
_COLLAGE_BLOCK_RE = COLLAGE_BLOCK_RE
_TABLE_SEPARATOR_RE = TABLE_SEPARATOR_RE
_parse_table_alignments = parse_table_alignments


@dataclass(frozen=True)
class AstInlineText:
    """Plain text inline leaf."""

    text: str


@dataclass(frozen=True)
class AstInlineStyled:
    """Styled inline span (bold, italic, …) wrapping nested inlines."""

    kind: Literal[
        "bold",
        "italic",
        "underline",
        "strikethrough",
        "spoiler",
    ]
    children: tuple[AstInline, ...] = ()


@dataclass(frozen=True)
class AstInlineCode:
    """Inline code span."""

    text: str


@dataclass(frozen=True)
class AstInlineLink:
    """Markdown link ``[label](url)``."""

    label: tuple[AstInline, ...]
    url: str


@dataclass(frozen=True)
class AstInlineMath:
    """Inline LaTeX ``$…$``."""

    text: str


@dataclass(frozen=True)
class AstInlineMention:
    """Telegram-style ``@username`` mention."""

    text: str


AstInline = (
    AstInlineText
    | AstInlineStyled
    | AstInlineCode
    | AstInlineLink
    | AstInlineMath
    | AstInlineMention
)


@dataclass(frozen=True)
class AstParagraph:
    """Paragraph block."""

    inlines: tuple[AstInline, ...]


@dataclass(frozen=True)
class AstHeading:
    """ATX heading ``# …``."""

    level: int
    inlines: tuple[AstInline, ...]


@dataclass(frozen=True)
class AstDivider:
    """Horizontal rule."""


@dataclass(frozen=True)
class AstListItem:
    """List item with optional task checkbox."""

    inlines: tuple[AstInline, ...]
    checked: bool | None = None


@dataclass(frozen=True)
class AstList:
    """Ordered, unordered, or task list."""

    style: Literal["ordered", "unordered", "task"]
    items: tuple[AstListItem, ...]


@dataclass(frozen=True)
class AstPreformatted:
    """Fenced code block."""

    language: str
    text: str


@dataclass(frozen=True)
class AstBlockquote:
    """Block quotation (``>`` lines)."""

    inlines: tuple[AstInline, ...]
    expandable: bool = False


@dataclass(frozen=True)
class AstTable:
    """GFM pipe table with optional trailing caption paragraph."""

    raw: str
    caption: tuple[AstInline, ...] = ()


@dataclass(frozen=True)
class AstDetails:
    """HTML ``<details>`` block."""

    raw: str


@dataclass(frozen=True)
class AstMathBlock:
    """Block LaTeX ``$$…$$``."""

    text: str


@dataclass(frozen=True)
class AstMedia:
    """Photo/video/audio/voice/animation media block."""

    kind: MediaKind
    source: str
    alt: str = ""


@dataclass(frozen=True)
class AstSlideshow:
    """Multi-slide media container."""

    items: tuple[AstMedia, ...]


@dataclass(frozen=True)
class AstCollage:
    """Grouped media container."""

    items: tuple[AstMedia, ...]


@dataclass(frozen=True)
class AstPullQuote:
    """Pull-quote lines (``>>>`` prefix)."""

    inlines: tuple[AstInline, ...]


@dataclass(frozen=True)
class AstFooter:
    """Footer block from ``<!-- sevn:footer -->`` region."""

    inlines: tuple[AstInline, ...]


@dataclass(frozen=True)
class AstAnchor:
    """Block-level anchor target."""

    anchor_id: str


@dataclass(frozen=True)
class AstThinking:
    """Collapsible reasoning block."""

    inlines: tuple[AstInline, ...]


AstBlock = (
    AstParagraph
    | AstHeading
    | AstDivider
    | AstList
    | AstPreformatted
    | AstBlockquote
    | AstTable
    | AstDetails
    | AstMathBlock
    | AstMedia
    | AstSlideshow
    | AstCollage
    | AstPullQuote
    | AstFooter
    | AstAnchor
    | AstThinking
)


def _parse_inline(
    text: str,
    *,
    depth: int = 0,
    _placeholders: dict[str, AstInline] | None = None,
    _nonce: str | None = None,
) -> tuple[AstInline, ...]:
    """Parse inline Markdown spans into AST nodes (same delimiter order as ``to_telegram``).

    Nested spans (e.g. ``**`code`**``) stash the inner span first, so the outer
    frame's text already contains the inner token when the recursive call runs.
    The ``placeholders`` dict and per-call ``nonce`` are therefore shared across
    the recursion: a recursive frame resolves tokens stashed by outer frames to
    the correct node, and ``len(placeholders)`` stays globally unique. Leftover
    consumed entries in the shared dict are harmless.

    Args:
        text (str): Inline Markdown without block constructs.
        depth (int, optional): Recursion guard. Defaults to ``0``.
        _placeholders (dict[str, AstInline] | None, optional): Shared token →
            node map threaded through recursion. Internal; ``None`` at the
            top-level call seeds a fresh dict.
        _nonce (str | None, optional): Shared token nonce threaded through
            recursion. Internal; ``None`` at the top-level call mints one.

    Returns:
        tuple[AstInline, ...]: Inline AST nodes covering *text*.

    Examples:
        >>> _parse_inline("**bold**")[0].kind
        'bold'
    """
    if depth > MAX_INLINE_DEPTH:
        return (AstInlineText(text=text),)
    if not text:
        return (AstInlineText(text=""),)

    work = text
    placeholders: dict[str, AstInline] = {} if _placeholders is None else _placeholders
    # Per-call nonce so a failed restore can't render as plausible text and
    # crafted input can't collide with a real token. Shared across recursion.
    nonce = uuid.uuid4().hex[:12] if _nonce is None else _nonce

    def _stash(node: AstInline) -> str:
        token = f"\x00I{nonce}:{len(placeholders)}\x00"
        placeholders[token] = node
        return token

    def _recurse(inner: str) -> tuple[AstInline, ...]:
        return _parse_inline(
            inner,
            depth=depth + 1,
            _placeholders=placeholders,
            _nonce=nonce,
        )

    def _code(match: re.Match[str]) -> str:
        return _stash(AstInlineCode(text=match.group(1)))

    work = _INLINE_CODE_RE.sub(_code, work)

    def _link(match: re.Match[str]) -> str:
        label = _recurse(match.group(1))
        return _stash(AstInlineLink(label=label, url=match.group(2)))

    work = _LINK_RE.sub(_link, work)

    def _math(match: re.Match[str]) -> str:
        return _stash(AstInlineMath(text=match.group(1)))

    work = _MATH_INLINE_PARSE_RE.sub(_math, work)

    def _styled(
        kind: Literal["bold", "italic", "underline", "strikethrough", "spoiler"],
        pattern: re.Pattern[str],
    ) -> None:
        nonlocal work

        def _repl(match: re.Match[str]) -> str:
            children = _recurse(match.group(1))
            return _stash(AstInlineStyled(kind=kind, children=children))

        work = pattern.sub(_repl, work)

    _styled("bold", _BOLD_RE)
    _styled("underline", _UNDERLINE_RE)
    _styled("strikethrough", _STRIKE_RE)
    _styled("spoiler", _SPOILER_RE)
    _styled("italic", _ITALIC_STAR_RE)
    _styled("italic", _ITALIC_USCORE_RE)

    def _mention(match: re.Match[str]) -> str:
        username = match.group(1)
        return _stash(AstInlineMention(text=f"@{username}"))

    work = _MENTION_RE.sub(_mention, work)

    parts = re.split(rf"(\x00I{nonce}:\d+\x00)", work)
    nodes: list[AstInline] = []
    for part in parts:
        if not part:
            continue
        if part in placeholders:
            nodes.append(placeholders[part])
        else:
            nodes.append(AstInlineText(text=part))
    return tuple(nodes)


def _inlines_to_plain(inlines: Sequence[AstInline]) -> str:
    """Flatten inline AST to plain text (for unsupported block fallbacks).

    Args:
        inlines (Sequence[AstInline]): Inline nodes.

    Returns:
        str: Concatenated literal text.

    Examples:
        >>> _inlines_to_plain(_parse_inline("**x**"))
        'x'
    """
    parts: list[str] = []
    for node in inlines:
        if isinstance(node, (AstInlineText, AstInlineCode)):
            parts.append(node.text)
        elif isinstance(node, AstInlineMath):
            parts.append(f"${node.text}$")
        elif isinstance(node, AstInlineMention):
            parts.append(node.text)
        elif isinstance(node, AstInlineLink):
            parts.append(_inlines_to_plain(node.label))
        elif isinstance(node, AstInlineStyled):
            parts.append(_inlines_to_plain(node.children))
    return "".join(parts)


def _classify_list_line(line: str) -> tuple[str, str, bool | None] | None:
    """Return list style, body, and optional task checkbox for a list line.

    Args:
        line (str): Single source line.

    Returns:
        tuple[str, str, bool | None] | None: ``(style, body, checked)`` or ``None``.

    Examples:
        >>> _classify_list_line("- [ ] task")
        ('task', 'task', False)
    """
    task = _TASK_LIST_RE.match(line)
    if task:
        checked = task.group(1).lower() == "x"
        return ("task", task.group(2), checked)
    unordered = _UNORDERED_LIST_RE.match(line)
    if unordered:
        return ("unordered", unordered.group(1), None)
    ordered = _ORDERED_LIST_RE.match(line)
    if ordered:
        return ("ordered", ordered.group(1), None)
    return None


def _parse_list_block(lines: list[str]) -> AstList:
    """Parse consecutive list lines into an ``AstList``.

    Args:
        lines (list[str]): Lines belonging to one list block.

    Returns:
        AstList: Parsed list block.

    Examples:
        >>> _parse_list_block(["- a", "- b"]).style
        'unordered'
    """
    style: Literal["ordered", "unordered", "task"] = "unordered"
    items: list[AstListItem] = []
    for line in lines:
        classified = _classify_list_line(line)
        if classified is None:
            continue
        line_style, body, checked = classified
        style = line_style  # type: ignore[assignment]
        items.append(
            AstListItem(inlines=_parse_inline(body), checked=checked),
        )
    return AstList(style=style, items=tuple(items))


def _parse_blockquote_block(lines: list[str]) -> AstBlockquote:
    """Parse blockquote lines into ``AstBlockquote``.

    Args:
        lines (list[str]): Lines starting with ``>``.

    Returns:
        AstBlockquote: Parsed blockquote.

    Examples:
        >>> _inlines_to_plain(_parse_blockquote_block(["> hi"]).inlines)
        'hi'
    """
    expandable = bool(lines and re.match(r"^\s*\*\*>", lines[0]))
    bodies: list[str] = []
    for line in lines:
        match = _BLOCKQUOTE_RE.match(line)
        if match:
            bodies.append(match.group(1))
    joined = "\n".join(bodies)
    return AstBlockquote(inlines=_parse_inline(joined), expandable=expandable)


def _parse_details_html(raw: str) -> tuple[tuple[AstInline, ...], tuple[AstBlock, ...]]:
    """Parse ``<details>`` HTML into summary inlines and nested body blocks.

    Args:
        raw (str): Raw ``<details>…</details>`` HTML fragment.

    Returns:
        tuple[tuple[AstInline, ...], tuple[AstBlock, ...]]: Summary and body AST.

    Examples:
        >>> summary, _ = _parse_details_html(
        ...     "<details><summary>More</summary>Hidden.</details>"
        ... )
        >>> _inlines_to_plain(summary)
        'More'
    """
    summary_match = re.search(
        r"<summary[^>]*>(.*?)</summary>",
        raw,
        re.DOTALL | re.IGNORECASE,
    )
    summary_text = summary_match.group(1).strip() if summary_match else "Details"
    body_match = re.search(
        r"</summary>(.*)</details>",
        raw,
        re.DOTALL | re.IGNORECASE,
    )
    body_md = body_match.group(1).strip() if body_match else ""
    body_blocks = (
        markdown_to_ast(body_md) if body_md else (AstParagraph(inlines=(AstInlineText(text=""),)),)
    )
    return _parse_inline(summary_text), body_blocks


def _parse_media_image_line(line: str) -> AstMedia | None:
    """Parse a Markdown image line into ``AstMedia`` when it stands alone.

    Args:
        line (str): Single source line.

    Returns:
        AstMedia | None: Parsed photo media node, or ``None``.

    Examples:
        >>> _parse_media_image_line("![cap](file_id:ABC)").kind
        'photo'
    """
    match = _MEDIA_IMAGE_LINE_RE.match(line.strip())
    if match is None:
        return None
    alt, source = match.group(1), match.group(2)
    kind: MediaKind = "animation" if source.lower().endswith(".gif") else "photo"
    return AstMedia(kind=kind, source=source, alt=alt)


def _parse_media_directive_line(line: str) -> AstMedia | None:
    """Parse ``<!-- sevn:photo … -->`` directive into ``AstMedia``.

    Args:
        line (str): Single source line.

    Returns:
        AstMedia | None: Parsed media node, or ``None``.

    Examples:
        >>> _parse_media_directive_line('<!-- sevn:video path="/tmp/a.mp4" -->').kind
        'video'
    """
    match = _MEDIA_DIRECTIVE_RE.match(line.strip())
    if match is None:
        return None
    kind = match.group(1).lower()
    attrs = parse_media_directive_attrs(match.group(2))
    if "file_id" in attrs:
        source = f"file_id:{attrs['file_id']}"
    elif "path" in attrs:
        source = attrs["path"]
    elif "url" in attrs:
        source = attrs["url"]
    else:
        return None
    return AstMedia(kind=kind, source=source, alt=attrs.get("alt", ""))  # type: ignore[arg-type]


def _parse_media_items_from_region(region: str) -> tuple[AstMedia, ...]:
    """Collect ``AstMedia`` items from a slideshow/collage Markdown region.

    Args:
        region (str): Inner Markdown between sevn region markers.

    Returns:
        tuple[AstMedia, ...]: Parsed media nodes in document order.

    Examples:
        >>> len(_parse_media_items_from_region("![a](file_id:A)\\n![b](b.jpg)"))
        2
    """
    items: list[AstMedia] = []
    for line in region.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        media = _parse_media_image_line(stripped) or _parse_media_directive_line(stripped)
        if media is not None:
            items.append(media)
    return tuple(items)


def _is_standalone_media_line(line: str) -> bool:
    """Return whether *line* is a lone media image or sevn media directive.

    Args:
        line (str): Single source line.

    Returns:
        bool: ``True`` when the line should become its own block chunk.

    Examples:
        >>> _is_standalone_media_line('<!-- sevn:photo path="/tmp/a.jpg" -->')
        True
        >>> _is_standalone_media_line("plain text")
        False
    """
    stripped = line.strip()
    if not stripped:
        return False
    return bool(
        _MEDIA_IMAGE_LINE_RE.match(stripped)
        or _MEDIA_DIRECTIVE_RE.match(stripped)
        or _ANCHOR_DIRECTIVE_RE.match(stripped)
    )


def _split_document_blocks(work: str, placeholders: Mapping[str, str]) -> list[str]:
    """Split carved Markdown into block-level chunks.

    Args:
        work (str): Markdown with fence/table placeholders.
        placeholders (Mapping[str, str]): Placeholder token → raw content map.

    Returns:
        list[str]: Raw block chunks (placeholders or text runs).

    Examples:
        >>> _split_document_blocks("a\\n\\nb", {})
        ['a', 'b']
    """
    blocks: list[str] = []
    current: list[str] = []
    for line in work.split("\n"):
        if line in placeholders:
            if current:
                blocks.append("\n".join(current))
                current = []
            blocks.append(line)
            continue
        if not line.strip():
            if current:
                blocks.append("\n".join(current))
                current = []
            continue
        if _is_standalone_media_line(line):
            if current:
                blocks.append("\n".join(current))
                current = []
            blocks.append(line)
            continue
        current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def _parse_block_chunk(
    chunk: str,
    placeholders: Mapping[str, tuple[str, str]],
) -> AstBlock | None:
    """Parse one block chunk into an AST block node.

    Args:
        chunk (str): Raw block text or placeholder token.
        placeholders (Mapping[str, tuple[str, str]]): Token → ``(kind, raw)`` map.

    Returns:
        AstBlock | None: Parsed block, or ``None`` when empty.

    Examples:
        >>> _parse_block_chunk("# Title", {})
        AstHeading(level=1, inlines=(AstInlineText(text='Title'),))
    """
    if chunk in placeholders:
        kind, raw = placeholders[chunk]
        if kind == "fence":
            match = _FENCE_RE.match(raw)
            if match:
                return AstPreformatted(
                    language=match.group(1).strip(),
                    text=match.group(2).rstrip("\n"),
                )
            return AstPreformatted(language="", text=raw)
        if kind == "table":
            return AstTable(raw=raw)
        if kind == "details":
            return AstDetails(raw=raw)
        if kind == "math":
            return AstMathBlock(text=raw.strip())
        if kind == "slideshow":
            return AstSlideshow(items=_parse_media_items_from_region(raw))
        if kind == "collage":
            return AstCollage(items=_parse_media_items_from_region(raw))
        if kind == "thinking":
            return AstThinking(inlines=_parse_inline(raw.strip()))
        if kind == "footer":
            return AstFooter(inlines=_parse_inline(raw.strip()))
        if kind == "anchor":
            anchor_match = _ANCHOR_DIRECTIVE_RE.search(raw)
            anchor_id = ""
            if anchor_match:
                anchor_id = anchor_match.group(1) or anchor_match.group(2) or ""
            return AstAnchor(anchor_id=anchor_id.strip('"'))
        return AstParagraph(inlines=(AstInlineText(text=raw),))

    lines = chunk.split("\n")
    if not lines:
        return None

    if len(lines) == 1:
        anchor = _ANCHOR_DIRECTIVE_RE.match(lines[0].strip())
        if anchor:
            anchor_id = anchor.group(1) or anchor.group(2) or ""
            return AstAnchor(anchor_id=anchor_id.strip('"'))
        media = _parse_media_image_line(lines[0]) or _parse_media_directive_line(lines[0])
        if media is not None:
            return media
        heading = _HEADING_RE.match(lines[0])
        if heading:
            level = len(heading.group(1))
            return AstHeading(level=level, inlines=_parse_inline(heading.group(2)))
        if _DIVIDER_RE.match(lines[0]):
            return AstDivider()

    if all(_classify_list_line(line) for line in lines if line.strip()):
        return _parse_list_block(lines)

    if all(_PULL_QUOTE_LINE_RE.match(line) for line in lines if line.strip()):
        bodies = [
            _PULL_QUOTE_LINE_RE.match(line).group(1)  # type: ignore[union-attr]
            for line in lines
            if line.strip()
        ]
        return AstPullQuote(inlines=_parse_inline("\n".join(bodies)))

    if all(_BLOCKQUOTE_RE.match(line) for line in lines):
        return _parse_blockquote_block(lines)

    if len(lines) == 1:
        return AstParagraph(inlines=_parse_inline(lines[0]))

    return AstParagraph(inlines=_parse_inline("\n".join(lines)))


def _merge_table_captions(blocks: Sequence[AstBlock]) -> list[AstBlock]:
    """Attach a paragraph immediately following a table as the table caption.

    Args:
        blocks (Sequence[AstBlock]): Parsed block AST sequence.

    Returns:
        list[AstBlock]: Blocks with table captions merged into ``AstTable``.

    Examples:
        >>> merged = _merge_table_captions(
        ...     (
        ...         AstTable(raw="| A |\\n| - |\\n| 1 |"),
        ...         AstParagraph(inlines=(AstInlineText(text="cap"),)),
        ...     )
        ... )
        >>> merged[0].caption[0].text
        'cap'
    """
    merged: list[AstBlock] = []
    index = 0
    while index < len(blocks):
        block = blocks[index]
        if isinstance(block, AstTable) and index + 1 < len(blocks):
            nxt = blocks[index + 1]
            if isinstance(nxt, AstParagraph) and nxt.inlines:
                merged.append(AstTable(raw=block.raw, caption=nxt.inlines))
                index += 2
                continue
        merged.append(block)
        index += 1
    return merged


def markdown_to_ast(markdown: str) -> tuple[AstBlock, ...]:
    """Parse Markdown into an internal AST using ``telegram_format`` regex source (D6).

    Uses the same fence/table carving pipeline as :func:`to_telegram` without forking
    delimiter rules. Tables and ``<details>`` are parsed for downstream R3 builders.

    Args:
        markdown (str): Agent Markdown reply body.

    Returns:
        tuple[AstBlock, ...]: Block-level AST nodes in document order.

    Examples:
        >>> blocks = markdown_to_ast("**hi**")
        >>> blocks[0].inlines[0].kind
        'bold'
        >>> markdown_to_ast("# Title")[0].level
        1
    """
    fences: dict[str, str] = {}

    def _stash_fence(match: re.Match[str]) -> str:
        raw = match.group(0)
        token = f"\x00F{len(fences)}\x00"
        fences[token] = raw
        return token

    work = _FENCE_RE.sub(_stash_fence, markdown)

    math_blocks: dict[str, str] = {}

    def _stash_math(match: re.Match[str]) -> str:
        token = f"\x00M{len(math_blocks)}\x00"
        math_blocks[token] = match.group(1).strip()
        return token

    work = _MATH_BLOCK_STASH_RE.sub(_stash_math, work)

    slideshows: dict[str, str] = {}

    def _stash_slideshow(match: re.Match[str]) -> str:
        token = f"\x00S{len(slideshows)}\x00"
        slideshows[token] = match.group(1)
        return token

    work = _SLIDESHOW_BLOCK_RE.sub(_stash_slideshow, work)

    collages: dict[str, str] = {}

    def _stash_collage(match: re.Match[str]) -> str:
        token = f"\x00C{len(collages)}\x00"
        collages[token] = match.group(1)
        return token

    work = _COLLAGE_BLOCK_RE.sub(_stash_collage, work)

    thinking_blocks: dict[str, str] = {}

    def _stash_thinking(match: re.Match[str]) -> str:
        token = f"\x00H{len(thinking_blocks)}\x00"
        thinking_blocks[token] = match.group(1)
        return token

    work = _THINKING_BLOCK_RE.sub(_stash_thinking, work)

    footers: dict[str, str] = {}

    def _stash_footer(match: re.Match[str]) -> str:
        token = f"\x00O{len(footers)}\x00"
        footers[token] = match.group(1)
        return token

    work = _FOOTER_BLOCK_RE.sub(_stash_footer, work)

    anchors: dict[str, str] = {}

    def _stash_anchor(match: re.Match[str]) -> str:
        raw = match.group(0)
        token = f"\x00N{len(anchors)}\x00"
        anchors[token] = raw
        return token

    work = _ANCHOR_DIRECTIVE_RE.sub(_stash_anchor, work)

    tables: dict[str, str] = {}

    def _stash_table(match: re.Match[str]) -> str:
        raw = match.group(0)
        token = f"\x00T{len(tables)}\x00"
        tables[token] = raw
        return token

    work = _TABLE_BLOCK_RE.sub(_stash_table, work)

    details: dict[str, str] = {}

    def _stash_details(match: re.Match[str]) -> str:
        raw = match.group(0)
        token = f"\x00D{len(details)}\x00"
        details[token] = raw
        return token

    work = re.sub(r"(?is)<details\b.*?</details>", _stash_details, work)

    placeholders: dict[str, tuple[str, str]] = {}
    for token, raw in fences.items():
        placeholders[token] = ("fence", raw)
    for token, raw in math_blocks.items():
        placeholders[token] = ("math", raw)
    for token, raw in slideshows.items():
        placeholders[token] = ("slideshow", raw)
    for token, raw in collages.items():
        placeholders[token] = ("collage", raw)
    for token, raw in thinking_blocks.items():
        placeholders[token] = ("thinking", raw)
    for token, raw in footers.items():
        placeholders[token] = ("footer", raw)
    for token, raw in anchors.items():
        placeholders[token] = ("anchor", raw)
    for token, raw in tables.items():
        placeholders[token] = ("table", raw)
    for token, raw in details.items():
        placeholders[token] = ("details", raw)

    blocks: list[AstBlock] = []
    for chunk in _split_document_blocks(work, {k: v[1] for k, v in placeholders.items()}):
        parsed = _parse_block_chunk(chunk, placeholders)
        if parsed is not None:
            blocks.append(parsed)
    return tuple(_merge_table_captions(blocks))
