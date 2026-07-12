"""Tests for Markdown → InputRichMessage renderer core (R2.1-R2.5)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sevn.channels.telegram_rich import (
    MAX_RICH_MESSAGE_JSON_BYTES,
    _parse_inline,
    ast_to_input_rich_message,
    inline_to_rich_json,
    inline_to_rich_text,
    markdown_to_ast,
    render_markdown_to_rich_message,
    serialize_input_rich_message,
    validate_rich_message_shape,
)
from sevn.channels.telegram_rich_blocks import (
    build_block_quotation,
    build_divider,
    build_input_rich_message,
    build_list,
    build_list_item,
    build_paragraph,
    build_preformatted,
    build_section_heading,
    rich_text_plain,
)

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "telegram_rich"


def _load(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


def _block_types(msg: dict[str, Any]) -> list[str]:
    return [block["type"] for block in msg["blocks"]]


def test_markdown_to_ast_heading_and_paragraph() -> None:
    blocks = markdown_to_ast("# Heading one\n\nParagraph with **bold**.")
    assert blocks[0].level == 1  # type: ignore[attr-defined]
    para = blocks[1]
    assert any(
        getattr(node, "kind", None) == "bold"
        for node in para.inlines  # type: ignore[attr-defined]
    )


def test_inline_emphasis_round_trip() -> None:
    nodes = _parse_inline("**bold** and *italic* and __underline__")
    rich = inline_to_rich_text(nodes)
    kinds = [node["type"] for node in rich["text"]]
    assert kinds == ["bold", "text", "italic", "text", "underline"]


def test_inline_link_and_code_and_spoiler() -> None:
    nodes = _parse_inline("[site](https://ex.example) and `code` and ||secret||")
    rich = inline_to_rich_text(nodes)
    types = {node["type"] for node in rich["text"]}
    assert types == {"url", "text", "code", "spoiler"}


def test_inline_math_and_mention() -> None:
    nodes = _parse_inline("$E=mc^2$ @telegram_user")
    rich_nodes = [inline_to_rich_json(n) for n in nodes]
    assert {"type": "math_inline", "text": "E=mc^2"} in rich_nodes
    assert {"type": "mention", "text": "@telegram_user"} in rich_nodes


def test_build_core_blocks_doctest_shapes() -> None:
    assert build_divider() == {"type": "divider"}
    assert build_preformatted("x=1", language="py") == {
        "type": "pre",
        "language": "py",
        "text": "x=1",
    }
    para = build_paragraph(rich_text_plain("p"))
    assert para["type"] == "paragraph"
    assert "text" in para
    quote = build_block_quotation(rich_text_plain("q"))
    assert quote["type"] == "blockquote"
    heading = build_section_heading(2, rich_text_plain("H"))
    assert heading["level"] == 2
    lst = build_list(
        "task",
        [build_list_item(rich_text_plain("t"), checked=False)],
    )
    assert lst["style"] == "task"
    assert lst["items"][0]["checked"] is False


def test_mixed_blocks_fixture_core_block_sequence() -> None:
    source = _load("mixed_blocks.md")
    msg = render_markdown_to_rich_message(source)
    types = _block_types(msg)
    assert types[:5] == ["heading", "paragraph", "list", "pre", "blockquote"]


def test_list_unordered_and_task() -> None:
    unordered = render_markdown_to_rich_message("- one\n- two")
    assert unordered["blocks"][0]["style"] == "unordered"
    task = render_markdown_to_rich_message("- [ ] open\n- [x] done")
    block = task["blocks"][0]
    assert block["style"] == "task"
    assert block["items"][0]["checked"] is False
    assert block["items"][1]["checked"] is True


def test_blockquote_block() -> None:
    msg = render_markdown_to_rich_message("> quoted line")
    block = msg["blocks"][0]
    assert block["type"] == "blockquote"
    assert block["text"]["text"][0]["text"] == "quoted line"


def test_divider_block() -> None:
    msg = render_markdown_to_rich_message("---")
    assert msg["blocks"] == [{"type": "divider"}]


def test_code_fence_block() -> None:
    msg = render_markdown_to_rich_message('```python\nprint("hi")\n```')
    block = msg["blocks"][0]
    assert block["type"] == "pre"
    assert block["language"] == "python"
    assert 'print("hi")' in block["text"]


def test_serialize_compact_json() -> None:
    payload = serialize_input_rich_message(build_input_rich_message([build_divider()]))
    assert payload == '{"blocks":[{"type":"divider"}]}'


def test_validate_rich_message_shape_rejects_bad_block() -> None:
    with pytest.raises(ValueError, match="unknown block type"):
        validate_rich_message_shape({"blocks": [{"type": "nope"}]})


def test_serialize_size_guard() -> None:
    huge = {
        "blocks": [
            {"type": "paragraph", "text": {"text": [{"type": "text", "text": "x" * 200_000}]}}
        ]
    }
    with pytest.raises(ValueError, match="exceeds size limit"):
        serialize_input_rich_message(huge)


def test_w0_skeleton_field_shapes() -> None:
    """R2.4: serializer output matches W0.6 nested RichText/RichBlock shapes."""
    skeleton = json.loads(_load("expected_table_skeleton.json"))
    cell = skeleton["blocks"][0]["rows"][0][0]
    assert cell["text"]["text"][0] == {"type": "text", "text": "Name"}
    assert cell["align"] == "left"
    # Core renderer produces the same leaf + container shapes.
    msg = render_markdown_to_rich_message("cell")
    leaf = msg["blocks"][0]["text"]["text"][0]
    assert leaf == {"type": "text", "text": "cell"}


def test_ast_to_input_rich_message_empty() -> None:
    msg = ast_to_input_rich_message(())
    assert msg == {"blocks": []}


def test_table_fixture_renders_rich_block_table() -> None:
    table_md = _load("table_simple.md")
    msg = render_markdown_to_rich_message(table_md)
    assert len(msg["blocks"]) == 1
    block = msg["blocks"][0]
    assert block["type"] == "table"
    assert block["rows"][0][1]["align"] == "center"
    assert block["caption"]["text"]["text"][0]["text"] == "Table caption: quarterly totals."


def test_max_json_bytes_constant() -> None:
    assert MAX_RICH_MESSAGE_JSON_BYTES == 64 * 1024


def test_smoke_post_split_telegram_markdown_regions_import() -> None:
    """W2: shared markdown region parser importable after extraction."""
    import importlib

    importlib.import_module("sevn.channels.telegram_markdown_regions")
