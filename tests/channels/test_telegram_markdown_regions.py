"""Golden region-boundary tests for shared Markdown carving (finding-5/6, W2).

Rich and viewer consumers must agree on slideshow/collage/table/image spans before
``telegram_markdown_regions`` extraction lands in W2.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pytest

from sevn.channels import telegram_rich as rich_mod
from sevn.gateway import webapp_viewer as viewer_mod

RegionKind = Literal["slideshow", "collage", "table", "image_line"]

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "telegram_rich"


@dataclass(frozen=True, slots=True)
class MarkdownRegion:
    """One carved Markdown region with document-order span."""

    kind: RegionKind
    start: int
    end: int


def _table_span(text: str) -> MarkdownRegion | None:
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
    if table_start is None or table_end is None:
        return None
    return MarkdownRegion("table", table_start, table_end)


def _block_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for pattern in (rich_mod._SLIDESHOW_BLOCK_RE, rich_mod._COLLAGE_BLOCK_RE):
        spans.extend((match.start(), match.end()) for match in pattern.finditer(text))
    return spans


def _inside_block(position: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= position < end for start, end in spans)


def _rich_regions(text: str) -> tuple[MarkdownRegion, ...]:
    regions: list[MarkdownRegion] = []
    block_spans = _block_spans(text)
    for match in rich_mod._SLIDESHOW_BLOCK_RE.finditer(text):
        regions.append(MarkdownRegion("slideshow", match.start(), match.end()))
    for match in rich_mod._COLLAGE_BLOCK_RE.finditer(text):
        regions.append(MarkdownRegion("collage", match.start(), match.end()))
    table = _table_span(text)
    if table is not None:
        regions.append(table)
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if rich_mod._MEDIA_IMAGE_LINE_RE.match(stripped) and not _inside_block(offset, block_spans):
            regions.append(MarkdownRegion("image_line", offset, offset + len(line.rstrip("\n"))))
        offset += len(line)
    return tuple(sorted(regions, key=lambda r: (r.start, r.kind)))


def _viewer_regions(text: str) -> tuple[MarkdownRegion, ...]:
    regions: list[MarkdownRegion] = []
    block_spans = _block_spans(text)
    for match in viewer_mod._SLIDESHOW_BLOCK_RE.finditer(text):
        regions.append(MarkdownRegion("slideshow", match.start(), match.end()))
    for match in viewer_mod._COLLAGE_BLOCK_RE.finditer(text):
        regions.append(MarkdownRegion("collage", match.start(), match.end()))
    table = _table_span(text)
    if table is not None and viewer_mod._parse_markdown_table(text) is not None:
        regions.append(table)
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if viewer_mod._MEDIA_IMAGE_RE.fullmatch(stripped) and not _inside_block(
            offset, block_spans
        ):
            regions.append(MarkdownRegion("image_line", offset, offset + len(stripped)))
        offset += len(line)
    return tuple(sorted(regions, key=lambda r: (r.start, r.kind)))


def _load(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("fixture_name", "expected_kinds"),
    [
        ("slideshow.md", ("slideshow",)),
        ("collage.md", ("collage",)),
        ("table_aligned.md", ("table",)),
        ("table_simple.md", ("table",)),
        ("media_photo.md", ("image_line",)),
        ("mixed_blocks.md", ("table",)),
    ],
)
def test_rich_and_viewer_region_boundaries_match_fixtures(
    fixture_name: str,
    expected_kinds: tuple[str, ...],
) -> None:
    """Rich and viewer parsers must carve identical spans (finding-5/6)."""
    markdown = _load(fixture_name)
    rich = _rich_regions(markdown)
    viewer = _viewer_regions(markdown)
    assert rich == viewer
    assert tuple(r.kind for r in rich) == expected_kinds


@pytest.mark.parametrize(
    ("separator", "expected"),
    [
        ("|------|:--:|:--:|", ["left", "center", "center"]),
        ("|:---|---:|---|", ["left", "right", "left"]),
        ("| --- |", ["left"]),
    ],
)
def test_table_alignment_parsing_golden(separator: str, expected: list[str]) -> None:
    """``_parse_table_alignments`` / ``_TABLE_SEPARATOR_RE`` golden rows (finding-5)."""
    raw = f"| Name | Q1 | Q2 |\n{separator}\n| a | 1 | 2 |"
    assert rich_mod._TABLE_SEPARATOR_RE.fullmatch(separator.strip())
    assert rich_mod._parse_table_alignments(raw) == expected


def test_slideshow_regex_inner_content_golden() -> None:
    """Slideshow block inner region matches image lines (finding-5/6)."""
    body = _load("slideshow.md")
    rich_match = rich_mod._SLIDESHOW_BLOCK_RE.search(body)
    viewer_match = viewer_mod._SLIDESHOW_BLOCK_RE.search(body)
    assert rich_match is not None
    assert viewer_match is not None
    assert rich_match.group(1) == viewer_match.group(1)
    inner = rich_match.group(1)
    image_lines = [
        line.strip()
        for line in inner.splitlines()
        if rich_mod._MEDIA_IMAGE_LINE_RE.match(line.strip())
    ]
    assert len(image_lines) == 2


def test_shared_markdown_regions_module_matches_consumers() -> None:
    """W2: shared module spans must match rich + viewer consumers."""
    mod = importlib.import_module("sevn.channels.telegram_markdown_regions")
    markdown = _load("mixed_blocks.md")
    shared_fn = getattr(mod, "find_markdown_regions", None)
    assert callable(shared_fn)
    shared = tuple(
        MarkdownRegion(r["kind"], r["start"], r["end"])  # type: ignore[index]
        for r in shared_fn(markdown)
    )
    assert shared == _rich_regions(markdown) == _viewer_regions(markdown)


def test_smoke_telegram_markdown_regions_public_surface() -> None:
    """W2: collection-safe import of post-split markdown region parser."""
    mod = importlib.import_module("sevn.channels.telegram_markdown_regions")
    exports = getattr(mod, "__all__", ())
    for name in (
        "SLIDESHOW_BLOCK_RE",
        "COLLAGE_BLOCK_RE",
        "MEDIA_IMAGE_LINE_RE",
        "TABLE_SEPARATOR_RE",
        "parse_table_alignments",
        "find_markdown_regions",
    ):
        assert hasattr(mod, name), f"missing export {name!r} in {exports!r}"
