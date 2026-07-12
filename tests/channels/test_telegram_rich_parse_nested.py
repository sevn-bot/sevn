"""Regression tests for nested inline-span restore in the rich Markdown parser.

Covers the stashed-token bug where a nested inline-code span wrapped by another
span (e.g. bold ``**`serp`**`` or a link label ``[see `cfg`](…)``) was parsed
into an ``AstInlineText`` holding a bare ``\\x00`` placeholder instead of the
real ``AstInlineCode`` node, because each recursive frame used its own
placeholders dict. The fix shares one dict + nonce across the recursion.
"""

from __future__ import annotations

from sevn.channels.telegram_rich_parse import (
    AstInline,
    AstInlineCode,
    AstInlineLink,
    AstInlineStyled,
    AstInlineText,
    _parse_inline,
)


def _walk_texts(nodes: tuple[AstInline, ...]) -> list[str]:
    """Collect every ``text``/``url`` string in an inline AST subtree."""
    out: list[str] = []
    for node in nodes:
        if isinstance(node, (AstInlineText, AstInlineCode)):
            out.append(node.text)
        elif isinstance(node, AstInlineStyled):
            out.extend(_walk_texts(node.children))
        elif isinstance(node, AstInlineLink):
            out.append(node.url)
            out.extend(_walk_texts(node.label))
        else:
            out.append(getattr(node, "text", ""))
    return out


def test_bold_wrapping_inline_code_yields_code_child() -> None:
    nodes = _parse_inline("**`serp`**")
    assert len(nodes) == 1
    bold = nodes[0]
    assert isinstance(bold, AstInlineStyled)
    assert bold.kind == "bold"
    assert bold.children == (AstInlineCode(text="serp"),)
    # No placeholder leaked into any leaf.
    assert all("\x00" not in text for text in _walk_texts(nodes))


def test_link_label_with_inline_code_yields_code_child() -> None:
    nodes = _parse_inline("[see `cfg`](https://example.com)")
    assert len(nodes) == 1
    link = nodes[0]
    assert isinstance(link, AstInlineLink)
    assert link.url == "https://example.com"
    assert any(isinstance(child, AstInlineCode) and child.text == "cfg" for child in link.label)
    assert all("\x00" not in text for text in _walk_texts(nodes))


def test_incident_line_has_no_placeholder_leak() -> None:
    line = (
        'When `load_tool("web_search")` returns readiness `needs_key`, I should '
        "immediately switch to **`serp`**, not attempt `web_search`."
    )
    nodes = _parse_inline(line)
    texts = _walk_texts(nodes)
    assert all("\x00" not in text for text in texts)
    # Every inline-code span survived as real code text.
    assert "serp" in texts
    assert "web_search" in texts
