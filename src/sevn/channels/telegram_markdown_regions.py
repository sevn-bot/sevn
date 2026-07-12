"""Shared Markdown region carving for Telegram rich send and Mini App viewer (finding-5/6).

Module: sevn.channels.telegram_markdown_regions
Depends: re, typing, sevn.channels.telegram_rich_blocks

Exports:
    MarkdownRegionDict — carved region span descriptor.
    parse_table_alignments — column alignments from a pipe-table block.
    parse_markdown_table — viewer table headers/rows dict.
    find_markdown_regions — document-order slideshow/collage/table/image spans.
"""

from __future__ import annotations

import re
from typing import Any, Literal, TypedDict

from sevn.channels.telegram_rich_blocks import TableAlign

RegionKind = Literal["slideshow", "collage", "table", "image_line"]

SLIDESHOW_BLOCK_RE = re.compile(
    r"<!--\s*sevn:slideshow\s*-->(.*?)<!--\s*/sevn:slideshow\s*-->",
    re.DOTALL | re.IGNORECASE,
)
COLLAGE_BLOCK_RE = re.compile(
    r"<!--\s*sevn:collage\s*-->(.*?)<!--\s*/sevn:collage\s*-->",
    re.DOTALL | re.IGNORECASE,
)
MEDIA_IMAGE_LINE_RE = re.compile(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$")
MEDIA_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
TABLE_SEPARATOR_RE = re.compile(r"^\|?[ \t:|-]+\|?$")


class MarkdownRegionDict(TypedDict):
    """One carved Markdown region with document-order span."""

    kind: RegionKind
    start: int
    end: int


def parse_table_alignments(raw: str) -> list[TableAlign]:
    """Extract column alignments from a GFM table separator row.

    Args:
        raw (str): Raw pipe-table block.

    Returns:
        list[TableAlign]: Alignment per column (defaults to ``left``).

    Examples:
        >>> parse_table_alignments("| Name | Q1 |\\n|------|:--:|:--:|\\n| a | 1 | 2 |")
        ['left', 'center', 'center']
    """
    for line in raw.splitlines():
        stripped = line.strip()
        if TABLE_SEPARATOR_RE.fullmatch(stripped) and "-" in stripped:
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            aligns: list[TableAlign] = []
            for cell in cells:
                left = cell.startswith(":")
                right = cell.endswith(":")
                if left and right:
                    aligns.append("center")
                elif right:
                    aligns.append("right")
                else:
                    aligns.append("left")
            return aligns
    return []


def parse_markdown_table(text: str) -> dict[str, Any] | None:
    """Parse a GFM pipe table into viewer ``table`` view_data.

    Args:
        text (str): Markdown source text.

    Returns:
        dict[str, Any] | None: ``{"headers", "rows"}`` or ``None`` when no table.

    Examples:
        >>> parse_markdown_table("| H |\\n| - |\\n| 1 |")["headers"]
        ['H']
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("|")]
    if len(lines) < 2:
        return None
    header_cells = [c.strip() for c in lines[0].strip("|").split("|")]
    body_lines = lines[1:]
    if body_lines and TABLE_SEPARATOR_RE.match(body_lines[0]):
        body_lines = body_lines[1:]
    rows: list[list[str]] = []
    for line in body_lines:
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells:
            rows.append(cells)
    if not header_cells or not rows:
        return None
    return {"headers": header_cells, "rows": rows}


def find_markdown_regions(text: str) -> list[MarkdownRegionDict]:
    """Return slideshow/collage/table/image-line spans in document order.

    Args:
        text (str): Raw assistant Markdown.

    Returns:
        list[MarkdownRegionDict]: Sorted region descriptors for rich + viewer consumers.

    Examples:
        >>> find_markdown_regions("![x](https://a.test/x.png)")[0]["kind"]
        'image_line'
    """
    regions: list[MarkdownRegionDict] = []
    block_spans: list[tuple[int, int]] = []
    for pattern in (SLIDESHOW_BLOCK_RE, COLLAGE_BLOCK_RE):
        block_spans.extend((match.start(), match.end()) for match in pattern.finditer(text))
    for match in SLIDESHOW_BLOCK_RE.finditer(text):
        regions.append({"kind": "slideshow", "start": match.start(), "end": match.end()})
    for match in COLLAGE_BLOCK_RE.finditer(text):
        regions.append({"kind": "collage", "start": match.start(), "end": match.end()})
    lines = text.splitlines(keepends=True)
    offset = 0
    table_start: int | None = None
    table_end: int | None = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|"):
            if table_start is None:
                table_start = offset
            table_end = offset + len(line)
        elif table_start is not None:
            break
        offset += len(line)
    if table_start is not None and table_end is not None:
        regions.append({"kind": "table", "start": table_start, "end": table_end})
    offset = 0
    for line in lines:
        stripped = line.strip()
        inside_block = any(start <= offset < end for start, end in block_spans)
        if MEDIA_IMAGE_LINE_RE.match(stripped) and not inside_block:
            regions.append(
                {
                    "kind": "image_line",
                    "start": offset,
                    "end": offset + len(line.rstrip("\n")),
                },
            )
        offset += len(line)
    return sorted(regions, key=lambda r: (r["start"], r["kind"]))


__all__ = [
    "COLLAGE_BLOCK_RE",
    "MEDIA_IMAGE_LINE_RE",
    "MEDIA_IMAGE_RE",
    "SLIDESHOW_BLOCK_RE",
    "TABLE_SEPARATOR_RE",
    "MarkdownRegionDict",
    "RegionKind",
    "find_markdown_regions",
    "parse_markdown_table",
    "parse_table_alignments",
]
