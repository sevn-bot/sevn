"""``RichBlock*`` builders for Bot API 10.1 rich messages (R2 core, R3 extended).

Module: sevn.channels.telegram_rich_blocks
Depends: typing, collections.abc, re

Exports:
    rich_blocks_module_ready — return whether block builders are importable.
    rich_text_plain — build a ``RichText`` container from a plain string.
    rich_text — wrap inline JSON nodes in a ``RichText`` container.
    build_paragraph — ``RichBlockParagraph`` dict.
    build_section_heading — ``RichBlockSectionHeading`` dict.
    build_divider — ``RichBlockDivider`` dict.
    build_list — ``RichBlockList`` dict.
    build_list_item — ``RichBlockListItem`` dict.
    build_preformatted — ``RichBlockPreformatted`` dict.
    build_block_quotation — ``RichBlockBlockQuotation`` dict.
    build_caption — ``RichBlockCaption`` dict.
    build_table_cell — ``RichBlockTableCell`` dict.
    build_table — ``RichBlockTable`` dict.
    build_details — ``RichBlockDetails`` dict.
    build_math — ``RichBlockMathematicalExpression`` dict.
    parse_media_directive_attrs — parse ``key=value`` attrs from media directives.
    resolve_media_source — map descriptor to ``file_id``/``url``/``path``.
    build_photo — ``RichBlockPhoto`` dict.
    build_video — ``RichBlockVideo`` dict.
    build_audio — ``RichBlockAudio`` dict.
    build_voice_note — ``RichBlockVoiceNote`` dict.
    build_animation — ``RichBlockAnimation`` dict.
    build_slideshow — ``RichBlockSlideshow`` dict.
    build_collage — ``RichBlockCollage`` dict.
    build_pull_quotation — ``RichBlockPullQuotation`` dict.
    build_footer — ``RichBlockFooter`` dict.
    build_anchor — ``RichBlockAnchor`` dict.
    build_thinking — ``RichBlockThinking`` dict.
    build_input_rich_message — ``InputRichMessage`` dict from block list.

Examples:
    >>> from sevn.channels.telegram_rich_blocks import build_paragraph, rich_text_plain
    >>> build_paragraph(rich_text_plain("hello"))
    {'type': 'paragraph', 'text': {'text': [{'type': 'text', 'text': 'hello'}]}}
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal

RICH_BLOCKS_MODULE_VERSION = "0.3.0-r3"

ListStyle = Literal["ordered", "unordered", "task"]
MediaKind = Literal["photo", "video", "audio", "voice", "animation"]
TableAlign = Literal["left", "center", "right"]

_MEDIA_ATTR_RE = re.compile(r'(\w+)=(?:"([^"]*)"|([^\s]+))')


def rich_blocks_module_ready() -> bool:
    """Return ``True`` when core block builders are available (R2).

    Returns:
        bool: Always ``True`` once R2 block builders are present.

    Examples:
        >>> rich_blocks_module_ready()
        True
    """
    return True


def rich_text_plain(text: str) -> dict[str, Any]:
    """Build a ``RichText`` container holding a single plain text leaf.

    Args:
        text (str): Literal text content.

    Returns:
        dict[str, Any]: ``RichText`` JSON shape ``{"text": [{"type": "text", ...}]}``.

    Examples:
        >>> rich_text_plain("hi")
        {'text': [{'type': 'text', 'text': 'hi'}]}
    """
    if not text:
        return {"text": [{"type": "text", "text": ""}]}
    return {"text": [{"type": "text", "text": text}]}


def rich_text(inline_nodes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Wrap inline JSON nodes in a ``RichText`` container.

    Args:
        inline_nodes (Sequence[Mapping[str, Any]]): Bot API inline entity dicts.

    Returns:
        dict[str, Any]: ``RichText`` JSON shape.

    Examples:
        >>> rich_text([{"type": "bold", "text": {"text": [{"type": "text", "text": "x"}]}}])
        {'text': [{'type': 'bold', 'text': {'text': [{'type': 'text', 'text': 'x'}]}}]}
    """
    if not inline_nodes:
        return rich_text_plain("")
    return {"text": list(inline_nodes)}


def build_paragraph(text: Mapping[str, Any]) -> dict[str, Any]:
    """Build a ``RichBlockParagraph`` dict.

    Args:
        text (Mapping[str, Any]): ``RichText`` container.

    Returns:
        dict[str, Any]: ``RichBlockParagraph`` JSON.

    Examples:
        >>> build_paragraph(rich_text_plain("p"))
        {'type': 'paragraph', 'text': {'text': [{'type': 'text', 'text': 'p'}]}}
    """
    return {"type": "paragraph", "text": dict(text)}


def build_section_heading(level: int, text: Mapping[str, Any]) -> dict[str, Any]:
    """Build a ``RichBlockSectionHeading`` dict.

    Args:
        level (int): Heading level ``1``-``6`` (clamped).
        text (Mapping[str, Any]): ``RichText`` container.

    Returns:
        dict[str, Any]: ``RichBlockSectionHeading`` JSON.

    Examples:
        >>> build_section_heading(1, rich_text_plain("Title"))
        {'type': 'heading', 'level': 1, 'text': {'text': [{'type': 'text', 'text': 'Title'}]}}
    """
    clamped = max(1, min(6, level))
    return {"type": "heading", "level": clamped, "text": dict(text)}


def build_divider() -> dict[str, Any]:
    """Build a ``RichBlockDivider`` dict.

    Returns:
        dict[str, Any]: ``RichBlockDivider`` JSON.

    Examples:
        >>> build_divider()
        {'type': 'divider'}
    """
    return {"type": "divider"}


def build_list_item(
    text: Mapping[str, Any],
    *,
    checked: bool | None = None,
) -> dict[str, Any]:
    """Build a ``RichBlockListItem`` dict.

    Args:
        text (Mapping[str, Any]): ``RichText`` container for the item body.
        checked (bool | None, optional): Task-list checkbox state. Defaults to ``None``.

    Returns:
        dict[str, Any]: ``RichBlockListItem`` JSON.

    Examples:
        >>> build_list_item(rich_text_plain("task"), checked=False)
        {'text': {'text': [{'type': 'text', 'text': 'task'}]}, 'checked': False}
    """
    item: dict[str, Any] = {"text": dict(text)}
    if checked is not None:
        item["checked"] = checked
    return item


def build_list(
    style: ListStyle,
    items: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a ``RichBlockList`` dict.

    Args:
        style (ListStyle): ``ordered``, ``unordered``, or ``task``.
        items (Sequence[Mapping[str, Any]]): ``RichBlockListItem`` dicts.

    Returns:
        dict[str, Any]: ``RichBlockList`` JSON.

    Examples:
        >>> build_list("unordered", [build_list_item(rich_text_plain("a"))])
        {'type': 'list', 'style': 'unordered', 'items': [{'text': {'text': [{'type': 'text', 'text': 'a'}]}}]}
    """
    return {"type": "list", "style": style, "items": list(items)}


def build_preformatted(text: str, *, language: str = "") -> dict[str, Any]:
    """Build a ``RichBlockPreformatted`` dict.

    Args:
        text (str): Raw code body (no fence delimiters).
        language (str, optional): Language hint from the fence. Defaults to ``""``.

    Returns:
        dict[str, Any]: ``RichBlockPreformatted`` JSON.

    Examples:
        >>> build_preformatted("x=1", language="python")
        {'type': 'pre', 'text': 'x=1', 'language': 'python'}
    """
    block: dict[str, Any] = {"type": "pre", "text": text}
    if language:
        block["language"] = language
    return block


def build_block_quotation(text: Mapping[str, Any]) -> dict[str, Any]:
    """Build a ``RichBlockBlockQuotation`` dict.

    Args:
        text (Mapping[str, Any]): ``RichText`` container.

    Returns:
        dict[str, Any]: ``RichBlockBlockQuotation`` JSON.

    Examples:
        >>> build_block_quotation(rich_text_plain("quoted"))
        {'type': 'blockquote', 'text': {'text': [{'type': 'text', 'text': 'quoted'}]}}
    """
    return {"type": "blockquote", "text": dict(text)}


def build_caption(text: Mapping[str, Any]) -> dict[str, Any]:
    """Build a ``RichBlockCaption`` dict.

    Args:
        text (Mapping[str, Any]): ``RichText`` container.

    Returns:
        dict[str, Any]: ``RichBlockCaption`` JSON.

    Examples:
        >>> build_caption(rich_text_plain("cap"))
        {'text': {'text': [{'type': 'text', 'text': 'cap'}]}}
    """
    return {"text": dict(text)}


def build_table_cell(
    text: Mapping[str, Any],
    *,
    align: TableAlign | None = None,
) -> dict[str, Any]:
    """Build a ``RichBlockTableCell`` dict.

    Args:
        text (Mapping[str, Any]): ``RichText`` container.
        align (TableAlign | None, optional): Column alignment. Defaults to ``None``.

    Returns:
        dict[str, Any]: ``RichBlockTableCell`` JSON.

    Examples:
        >>> build_table_cell(rich_text_plain("A"), align="center")
        {'text': {'text': [{'type': 'text', 'text': 'A'}]}, 'align': 'center'}
    """
    cell: dict[str, Any] = {"text": dict(text)}
    if align is not None:
        cell["align"] = align
    return cell


def build_table(
    rows: Sequence[Sequence[Mapping[str, Any]]],
    *,
    caption: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a ``RichBlockTable`` dict.

    Args:
        rows (Sequence[Sequence[Mapping[str, Any]]]): Grid of ``RichBlockTableCell`` dicts.
        caption (Mapping[str, Any] | None, optional): ``RichBlockCaption`` dict.
            Defaults to ``None``.

    Returns:
        dict[str, Any]: ``RichBlockTable`` JSON.

    Examples:
        >>> build_table([[build_table_cell(rich_text_plain("x"))]])
        {'type': 'table', 'rows': [[{'text': {'text': [{'type': 'text', 'text': 'x'}]}}]]}
    """
    block: dict[str, Any] = {"type": "table", "rows": [list(row) for row in rows]}
    if caption is not None:
        block["caption"] = dict(caption)
    return block


def build_details(
    summary: Mapping[str, Any],
    body: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a ``RichBlockDetails`` dict.

    Args:
        summary (Mapping[str, Any]): ``RichText`` summary line.
        body (Sequence[Mapping[str, Any]]): Nested ``RichBlock`` dicts.

    Returns:
        dict[str, Any]: ``RichBlockDetails`` JSON.

    Examples:
        >>> build_details(rich_text_plain("More"), [build_paragraph(rich_text_plain("body"))])
        {'type': 'details', 'summary': {'text': [{'type': 'text', 'text': 'More'}]}, 'body': [{'type': 'paragraph', 'text': {'text': [{'type': 'text', 'text': 'body'}]}}]}
    """
    return {
        "type": "details",
        "summary": dict(summary),
        "body": list(body),
    }


def build_math(text: str) -> dict[str, Any]:
    """Build a ``RichBlockMathematicalExpression`` dict.

    Args:
        text (str): Block LaTeX (without ``$$`` delimiters).

    Returns:
        dict[str, Any]: ``RichBlockMathematicalExpression`` JSON.

    Examples:
        >>> build_math("E=mc^2")
        {'type': 'math', 'text': 'E=mc^2'}
    """
    return {"type": "math", "text": text}


def parse_media_directive_attrs(raw: str) -> dict[str, str]:
    """Parse ``key=value`` pairs from a sevn media HTML comment body.

    Args:
        raw (str): Attribute string from ``<!-- sevn:photo path=x alt=y -->``.

    Returns:
        dict[str, str]: Parsed attribute map.

    Examples:
        >>> parse_media_directive_attrs('path="/tmp/a.jpg" alt=diagram')
        {'path': '/tmp/a.jpg', 'alt': 'diagram'}
    """
    attrs: dict[str, str] = {}
    for match in _MEDIA_ATTR_RE.finditer(raw):
        key = match.group(1)
        value = match.group(2) if match.group(2) is not None else match.group(3)
        attrs[key] = value
    return attrs


def resolve_media_source(descriptor: str) -> dict[str, str]:
    """Map a media descriptor to Bot API upload reference fields.

    Accepts ``file_id:…``, ``http(s)://…``, or a local filesystem path.

    Args:
        descriptor (str): Media source string from Markdown or directive attrs.

    Returns:
        dict[str, str]: One of ``{"file_id": …}``, ``{"url": …}``, or ``{"path": …}``.

    Examples:
        >>> resolve_media_source("file_id:AgACAgI")
        {'file_id': 'AgACAgI'}
        >>> resolve_media_source("https://ex.example/a.jpg")
        {'url': 'https://ex.example/a.jpg'}
        >>> resolve_media_source("/tmp/photo.jpg")
        {'path': '/tmp/photo.jpg'}
    """
    desc = descriptor.strip()
    if desc.startswith("file_id:"):
        return {"file_id": desc[8:]}
    if desc.startswith(("http://", "https://")):
        return {"url": desc}
    return {"path": desc}


def _media_block(
    kind: MediaKind,
    source: Mapping[str, str],
    *,
    caption: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a media ``RichBlock`` dict for *kind*.

    Args:
        kind (MediaKind): Media discriminator (``photo``, ``video``, …).
        source (Mapping[str, str]): ``file_id``/``url``/``path`` reference.
        caption (Mapping[str, Any] | None, optional): ``RichBlockCaption`` dict.
            Defaults to ``None``.

    Returns:
        dict[str, Any]: Bot API media block JSON.

    Examples:
        >>> _media_block("photo", {"file_id": "X"})
        {'type': 'photo', 'photo': {'file_id': 'X'}}
    """
    block: dict[str, Any] = {"type": kind, kind: dict(source)}
    if caption is not None:
        block["caption"] = dict(caption)
    return block


def build_photo(
    source: Mapping[str, str],
    *,
    caption: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a ``RichBlockPhoto`` dict.

    Args:
        source (Mapping[str, str]): ``file_id``/``url``/``path`` reference.
        caption (Mapping[str, Any] | None, optional): ``RichBlockCaption`` dict.
            Defaults to ``None``.

    Returns:
        dict[str, Any]: ``RichBlockPhoto`` JSON.

    Examples:
        >>> build_photo({"file_id": "AgAC"})
        {'type': 'photo', 'photo': {'file_id': 'AgAC'}}
    """
    return _media_block("photo", source, caption=caption)


def build_video(
    source: Mapping[str, str],
    *,
    caption: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a ``RichBlockVideo`` dict.

    Args:
        source (Mapping[str, str]): ``file_id``/``url``/``path`` reference.
        caption (Mapping[str, Any] | None, optional): ``RichBlockCaption`` dict.
            Defaults to ``None``.

    Returns:
        dict[str, Any]: ``RichBlockVideo`` JSON.

    Examples:
        >>> build_video({"path": "/tmp/v.mp4"})
        {'type': 'video', 'video': {'path': '/tmp/v.mp4'}}
    """
    return _media_block("video", source, caption=caption)


def build_audio(
    source: Mapping[str, str],
    *,
    caption: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a ``RichBlockAudio`` dict.

    Args:
        source (Mapping[str, str]): ``file_id``/``url``/``path`` reference.
        caption (Mapping[str, Any] | None, optional): ``RichBlockCaption`` dict.
            Defaults to ``None``.

    Returns:
        dict[str, Any]: ``RichBlockAudio`` JSON.

    Examples:
        >>> build_audio({"file_id": "CQAC"})
        {'type': 'audio', 'audio': {'file_id': 'CQAC'}}
    """
    return _media_block("audio", source, caption=caption)


def build_voice_note(
    source: Mapping[str, str],
    *,
    caption: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a ``RichBlockVoiceNote`` dict.

    Args:
        source (Mapping[str, str]): ``file_id``/``url``/``path`` reference.
        caption (Mapping[str, Any] | None, optional): ``RichBlockCaption`` dict.
            Defaults to ``None``.

    Returns:
        dict[str, Any]: ``RichBlockVoiceNote`` JSON.

    Examples:
        >>> build_voice_note({"file_id": "AwAC"})
        {'type': 'voice', 'voice': {'file_id': 'AwAC'}}
    """
    return _media_block("voice", source, caption=caption)


def build_animation(
    source: Mapping[str, str],
    *,
    caption: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a ``RichBlockAnimation`` dict.

    Args:
        source (Mapping[str, str]): ``file_id``/``url``/``path`` reference.
        caption (Mapping[str, Any] | None, optional): ``RichBlockCaption`` dict.
            Defaults to ``None``.

    Returns:
        dict[str, Any]: ``RichBlockAnimation`` JSON.

    Examples:
        >>> build_animation({"path": "/tmp/x.gif"})
        {'type': 'animation', 'animation': {'path': '/tmp/x.gif'}}
    """
    return _media_block("animation", source, caption=caption)


def build_slideshow(slides: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Build a ``RichBlockSlideshow`` dict.

    Args:
        slides (Sequence[Mapping[str, Any]]): Media block dicts (typically photos).

    Returns:
        dict[str, Any]: ``RichBlockSlideshow`` JSON.

    Examples:
        >>> build_slideshow([build_photo({"file_id": "A"})])
        {'type': 'slideshow', 'slides': [{'type': 'photo', 'photo': {'file_id': 'A'}}]}
    """
    return {"type": "slideshow", "slides": list(slides)}


def build_collage(media: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Build a ``RichBlockCollage`` dict.

    Args:
        media (Sequence[Mapping[str, Any]]): Media block dicts.

    Returns:
        dict[str, Any]: ``RichBlockCollage`` JSON.

    Examples:
        >>> build_collage([build_photo({"file_id": "A"})])
        {'type': 'collage', 'media': [{'type': 'photo', 'photo': {'file_id': 'A'}}]}
    """
    return {"type": "collage", "media": list(media)}


def build_pull_quotation(text: Mapping[str, Any]) -> dict[str, Any]:
    """Build a ``RichBlockPullQuotation`` dict.

    Args:
        text (Mapping[str, Any]): ``RichText`` container.

    Returns:
        dict[str, Any]: ``RichBlockPullQuotation`` JSON.

    Examples:
        >>> build_pull_quotation(rich_text_plain("pull"))
        {'type': 'pull_quote', 'text': {'text': [{'type': 'text', 'text': 'pull'}]}}
    """
    return {"type": "pull_quote", "text": dict(text)}


def build_footer(text: Mapping[str, Any]) -> dict[str, Any]:
    """Build a ``RichBlockFooter`` dict.

    Args:
        text (Mapping[str, Any]): ``RichText`` container.

    Returns:
        dict[str, Any]: ``RichBlockFooter`` JSON.

    Examples:
        >>> build_footer(rich_text_plain("foot"))
        {'type': 'footer', 'text': {'text': [{'type': 'text', 'text': 'foot'}]}}
    """
    return {"type": "footer", "text": dict(text)}


def build_anchor(anchor_id: str) -> dict[str, Any]:
    """Build a ``RichBlockAnchor`` dict.

    Args:
        anchor_id (str): Anchor identifier referenced by inline anchors.

    Returns:
        dict[str, Any]: ``RichBlockAnchor`` JSON.

    Examples:
        >>> build_anchor("ref-1")
        {'type': 'anchor', 'id': 'ref-1'}
    """
    return {"type": "anchor", "id": anchor_id}


def build_thinking(
    text: Mapping[str, Any],
    *,
    collapsed: bool = True,
) -> dict[str, Any]:
    """Build a ``RichBlockThinking`` dict.

    Args:
        text (Mapping[str, Any]): ``RichText`` reasoning body.
        collapsed (bool, optional): Whether the block starts collapsed.
            Defaults to ``True``.

    Returns:
        dict[str, Any]: ``RichBlockThinking`` JSON.

    Examples:
        >>> build_thinking(rich_text_plain("hmm"))
        {'type': 'thinking', 'text': {'text': [{'type': 'text', 'text': 'hmm'}]}, 'collapsed': True}
    """
    block: dict[str, Any] = {"type": "thinking", "text": dict(text)}
    if collapsed:
        block["collapsed"] = True
    return block


def build_input_rich_message(blocks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Assemble an ``InputRichMessage`` dict from rich blocks.

    Args:
        blocks (Sequence[Mapping[str, Any]]): ``RichBlock`` dicts in order.

    Returns:
        dict[str, Any]: ``InputRichMessage`` JSON ``{"blocks": [...]}``.

    Examples:
        >>> build_input_rich_message([build_divider()])
        {'blocks': [{'type': 'divider'}]}
    """
    return {"blocks": list(blocks)}
