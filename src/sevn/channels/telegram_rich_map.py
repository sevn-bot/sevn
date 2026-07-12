"""AST → Bot API ``InputRichMessage`` mapper (R2 core + R3 blocks, finding-2 map split).

Module: sevn.channels.telegram_rich_map
Depends: typing, collections.abc, sevn.channels.telegram_format,
    sevn.channels.telegram_markdown_regions, sevn.channels.telegram_rich_blocks,
    sevn.channels.telegram_rich_parse

Exports:
    inline_to_rich_json — map one inline AST node to Bot API ``RichText*`` JSON.
    inline_to_rich_text — inline AST → ``RichText`` JSON container.
    ast_to_input_rich_message — AST → ``InputRichMessage`` dict (R2 core + R3 blocks).

Examples:
    >>> from sevn.channels.telegram_rich_map import ast_to_input_rich_message
    >>> from sevn.channels.telegram_rich_parse import markdown_to_ast
    >>> ast_to_input_rich_message(markdown_to_ast("---"))["blocks"][0]["type"]
    'divider'
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sevn.channels.telegram_format import _split_table_rows
from sevn.channels.telegram_markdown_regions import parse_table_alignments
from sevn.channels.telegram_rich_blocks import (
    build_anchor,
    build_animation,
    build_audio,
    build_block_quotation,
    build_caption,
    build_collage,
    build_details,
    build_divider,
    build_footer,
    build_input_rich_message,
    build_list,
    build_list_item,
    build_math,
    build_paragraph,
    build_photo,
    build_preformatted,
    build_pull_quotation,
    build_section_heading,
    build_slideshow,
    build_table,
    build_table_cell,
    build_thinking,
    build_video,
    build_voice_note,
    resolve_media_source,
    rich_text,
    rich_text_plain,
)
from sevn.channels.telegram_rich_parse import (
    MAX_INLINE_DEPTH,
    AstAnchor,
    AstBlockquote,
    AstCollage,
    AstDetails,
    AstDivider,
    AstFooter,
    AstHeading,
    AstInline,
    AstInlineCode,
    AstInlineLink,
    AstInlineMath,
    AstInlineMention,
    AstInlineStyled,
    AstInlineText,
    AstList,
    AstMathBlock,
    AstMedia,
    AstParagraph,
    AstPreformatted,
    AstPullQuote,
    AstSlideshow,
    AstTable,
    AstThinking,
    _inlines_to_plain,
    _parse_details_html,
    _parse_inline,
)

MAX_RICH_BLOCKS = 256


def inline_to_rich_json(node: AstInline, *, depth: int = 0) -> dict[str, Any]:
    """Map one inline AST node to Bot API ``RichText*`` JSON.

    Args:
        node (AstInline): Inline AST node.
        depth (int, optional): Recursion guard. Defaults to ``0``.

    Returns:
        dict[str, Any]: Bot API inline entity dict.

    Raises:
        ValueError: When nesting exceeds :data:`MAX_INLINE_DEPTH` or node is unknown.

    Examples:
        >>> inline_to_rich_json(AstInlineText(text="a"))
        {'type': 'text', 'text': 'a'}
    """
    if depth > MAX_INLINE_DEPTH:
        raise ValueError("parse error: inline nesting too deep")
    if isinstance(node, AstInlineText):
        return {"type": "text", "text": node.text}
    if isinstance(node, AstInlineCode):
        return {"type": "code", "text": node.text}
    if isinstance(node, AstInlineMath):
        return {"type": "math_inline", "text": node.text}
    if isinstance(node, AstInlineMention):
        return {"type": "mention", "text": node.text}
    if isinstance(node, AstInlineLink):
        label_text = _inlines_to_plain(node.label)
        return {"type": "url", "text": label_text, "url": node.url}
    if isinstance(node, AstInlineStyled):
        nested = [inline_to_rich_json(child, depth=depth + 1) for child in node.children]
        return {"type": node.kind, "text": rich_text(nested)}
    raise ValueError(f"parse error: unknown inline node {type(node)!r}")


def inline_to_rich_text(inlines: Sequence[AstInline]) -> dict[str, Any]:
    """Convert inline AST nodes to a ``RichText`` JSON container.

    Args:
        inlines (Sequence[AstInline]): Inline AST nodes.

    Returns:
        dict[str, Any]: ``RichText`` JSON shape.

    Examples:
        >>> inline_to_rich_text(_parse_inline("*em*"))
        {'text': [{'type': 'italic', 'text': {'text': [{'type': 'text', 'text': 'em'}]}}]}
    """
    if not inlines:
        return rich_text([])
    return rich_text([inline_to_rich_json(node) for node in inlines])


def _table_block_to_rich(
    raw: str,
    *,
    caption: tuple[AstInline, ...] = (),
) -> dict[str, Any]:
    """Render a GFM pipe table AST node to ``RichBlockTable`` JSON.

    Args:
        raw (str): Raw pipe-table Markdown.
        caption (tuple[AstInline, ...], optional): Optional caption inlines.
            Defaults to ``()``.

    Returns:
        dict[str, Any]: ``RichBlockTable`` JSON.

    Examples:
        >>> _table_block_to_rich("| A |\\n| - |\\n| 1 |")["type"]
        'table'
    """
    rows = _split_table_rows(raw)
    aligns = parse_table_alignments(raw)
    rich_rows: list[list[dict[str, Any]]] = []
    for row in rows:
        rich_row: list[dict[str, Any]] = []
        for col_idx, cell in enumerate(row):
            align = aligns[col_idx] if col_idx < len(aligns) else None
            rich_row.append(
                build_table_cell(
                    inline_to_rich_text(_parse_inline(cell)),
                    align=align,
                ),
            )
        rich_rows.append(rich_row)
    caption_block = build_caption(inline_to_rich_text(caption)) if caption else None
    return build_table(rich_rows, caption=caption_block)


def _media_ast_to_rich(media: AstMedia) -> dict[str, Any]:
    """Convert ``AstMedia`` to a Bot API media ``RichBlock`` dict.

    Args:
        media (AstMedia): Media AST node.

    Returns:
        dict[str, Any]: ``RichBlockPhoto``/``Video``/… JSON.

    Examples:
        >>> _media_ast_to_rich(AstMedia(kind="photo", source="file_id:X"))["type"]
        'photo'
    """
    source = resolve_media_source(media.source)
    caption = build_caption(rich_text_plain(media.alt)) if media.alt else None
    builders = {
        "photo": build_photo,
        "video": build_video,
        "audio": build_audio,
        "voice": build_voice_note,
        "animation": build_animation,
    }
    return builders[media.kind](source, caption=caption)


def ast_to_input_rich_message(blocks: Sequence[Any]) -> dict[str, Any]:
    """Convert AST blocks to ``InputRichMessage`` JSON (R2 core + R3 extended blocks).

    Args:
        blocks (Sequence[Any]): Block-level AST from :func:`markdown_to_ast`.

    Returns:
        dict[str, Any]: ``InputRichMessage`` dict.

    Raises:
        ValueError: When block count exceeds :data:`MAX_RICH_BLOCKS`.

    Examples:
        >>> from sevn.channels.telegram_rich_parse import markdown_to_ast
        >>> ast_to_input_rich_message(markdown_to_ast("---"))["blocks"][0]["type"]
        'divider'
    """
    rich_blocks: list[dict[str, Any]] = []
    for block in blocks:
        if isinstance(block, AstParagraph):
            rich_blocks.append(build_paragraph(inline_to_rich_text(block.inlines)))
        elif isinstance(block, AstHeading):
            rich_blocks.append(
                build_section_heading(block.level, inline_to_rich_text(block.inlines)),
            )
        elif isinstance(block, AstDivider):
            rich_blocks.append(build_divider())
        elif isinstance(block, AstList):
            items = [
                build_list_item(
                    inline_to_rich_text(item.inlines),
                    checked=item.checked,
                )
                for item in block.items
            ]
            rich_blocks.append(build_list(block.style, items))
        elif isinstance(block, AstPreformatted):
            rich_blocks.append(
                build_preformatted(block.text, language=block.language),
            )
        elif isinstance(block, AstBlockquote):
            rich_blocks.append(build_block_quotation(inline_to_rich_text(block.inlines)))
        elif isinstance(block, AstTable):
            rich_blocks.append(
                _table_block_to_rich(block.raw, caption=block.caption),
            )
        elif isinstance(block, AstDetails):
            summary, body = _parse_details_html(block.raw)
            body_rich = ast_to_input_rich_message(body)["blocks"]
            rich_blocks.append(
                build_details(inline_to_rich_text(summary), body_rich),
            )
        elif isinstance(block, AstMathBlock):
            rich_blocks.append(build_math(block.text))
        elif isinstance(block, AstMedia):
            rich_blocks.append(_media_ast_to_rich(block))
        elif isinstance(block, AstSlideshow):
            rich_blocks.append(
                build_slideshow([_media_ast_to_rich(item) for item in block.items]),
            )
        elif isinstance(block, AstCollage):
            rich_blocks.append(
                build_collage([_media_ast_to_rich(item) for item in block.items]),
            )
        elif isinstance(block, AstPullQuote):
            rich_blocks.append(build_pull_quotation(inline_to_rich_text(block.inlines)))
        elif isinstance(block, AstFooter):
            rich_blocks.append(build_footer(inline_to_rich_text(block.inlines)))
        elif isinstance(block, AstAnchor):
            rich_blocks.append(build_anchor(block.anchor_id))
        elif isinstance(block, AstThinking):
            rich_blocks.append(build_thinking(inline_to_rich_text(block.inlines)))
    if len(rich_blocks) > MAX_RICH_BLOCKS:
        raise ValueError("parse error: too many rich blocks")
    return build_input_rich_message(rich_blocks)
