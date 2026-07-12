"""Tests for ``_outbound_stream_hygiene`` — strips unparsed tool-call XML.

Covers transcript-review item #4: provider-leaked ``<invoke>`` / ``<parameter>`` /
``</…:tool_call>`` fragments must be removed before being shown to the user, while content
inside fenced code blocks is preserved so the agent can intentionally render the fragments.
"""

from __future__ import annotations

from sevn.gateway.channel_router import _outbound_stream_hygiene


def test_strips_invoke_block() -> None:
    """An ``<invoke>...</invoke>`` block is removed; surrounding text survives."""
    text = "before <invoke name='log_query'>x</invoke> after"
    out, dropped = _outbound_stream_hygiene(text)
    assert "<invoke" not in out
    assert "before " in out
    assert " after" in out
    assert dropped > 0


def test_strips_parameter_block() -> None:
    """A standalone ``<parameter>`` block is stripped."""
    text = "ok <parameter name='pattern'>foo</parameter> done"
    out, _ = _outbound_stream_hygiene(text)
    assert "<parameter" not in out
    assert "</parameter>" not in out


def test_strips_namespaced_tool_call_close_tag() -> None:
    """Any ``</<provider>:tool_call>`` close-tag is stripped (model-agnostic)."""
    for tag in ("</minimax:tool_call>", "</anthropic:tool_call>", "</xyz_99:tool_call>"):
        out, _ = _outbound_stream_hygiene(f"hello {tag} world")
        assert "tool_call>" not in out
        assert "hello " in out
        assert " world" in out


def test_minimax_transcript_leak_is_cleaned() -> None:
    """The exact leak shape from the 2026-05-25 transcript is sanitised."""
    text = (
        '<invoke name="log_query"><parameter name="pattern">tool_call|838|'
        "round_budget|escalat</parameter></invoke></minimax:tool_call>"
    )
    out, dropped = _outbound_stream_hygiene(text)
    assert out.strip() == ""
    assert dropped == len(text)


def test_fenced_code_block_preserves_tool_call_xml() -> None:
    """The agent can render the leak inside ``` ... ``` for copy/inspection."""
    text = "```\n<invoke name='x'>y</invoke>\n```"
    out, _ = _outbound_stream_hygiene(text)
    assert "<invoke" in out
    assert "</invoke>" in out


def test_inline_code_block_preserves_short_fragment() -> None:
    """Inline backtick spans also count as code (single-line)."""
    text = "see `</minimax:tool_call>` for the leak"
    out, _ = _outbound_stream_hygiene(text)
    assert "</minimax:tool_call>" in out


def test_think_tag_still_stripped() -> None:
    """Pre-existing ``<think>`` strip remains in place."""
    out, dropped = _outbound_stream_hygiene("<think>plan</think>visible")
    assert out == "visible"
    assert dropped > 0


def test_plain_text_is_unchanged() -> None:
    """Plain text passes through untouched."""
    text = "Hello, this is plain output with no XML."
    out, dropped = _outbound_stream_hygiene(text)
    assert out == text
    assert dropped == 0
