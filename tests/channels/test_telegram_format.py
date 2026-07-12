"""Tests for the outbound Markdown → Telegram converter (`specs/18` §formatting, plan W9).

Covers both ``HTML`` and ``MarkdownV2`` parse modes: tables render as aligned
preformatted blocks (never raw pipes), the full emphasis family + spoiler +
blockquote + expandable-blockquote + fenced code render as valid markup, and
literal characters are escaped safely per mode.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

if TYPE_CHECKING:
    import httpx

from sevn.channels.telegram import (
    TelegramAdapter,
    TelegramConfig,
    telegram_config_from_workspace,
)
from sevn.channels.telegram_format import (
    _convert_inline,
    markdown_tables_to_pre,
    to_telegram,
)
from sevn.config.workspace_config import (
    ChannelsWorkspaceSectionConfig,
    GatewayConfig,
    TelegramChannelConfig,
    WorkspaceConfig,
)

_MODES = ["HTML", "MarkdownV2"]

_TABLE = "| Category | Tools |\n|----------|-------|\n| Read | read, glob |\n| Write | write |\n"


@pytest.mark.parametrize("mode", _MODES)
def test_table_renders_aligned_not_raw_pipes(mode: str) -> None:
    out = to_telegram(_TABLE, mode)
    # No raw Markdown table pipes leak through in either mode.
    assert "| Category |" not in out
    assert "|----------|" not in out
    # Header/body cells survive, column-aligned, inside a monospace block.
    assert "Category" in out
    assert "read, glob" in out
    if mode == "HTML":
        assert "<pre>" in out
        assert "</pre>" in out
    else:
        assert out.count("```") >= 2


def test_markdown_tables_to_pre_aligns_columns() -> None:
    grid = markdown_tables_to_pre("| A | BB |\n|---|----|\n| 111 | 2 |\n")
    lines = grid.splitlines()
    # Header column 0 padded to width of "111".
    assert lines[0].startswith("A  ")
    assert lines[1].startswith("111")


@pytest.mark.parametrize(
    ("src", "html_frag", "mdv2_frag"),
    [
        ("**bold**", "<b>bold</b>", "*bold*"),
        ("_italic_", "<i>italic</i>", "_italic_"),
        ("__underline__", "<u>underline</u>", "__underline__"),
        ("~~strike~~", "<s>strike</s>", "~strike~"),
        ("||spoiler||", "<tg-spoiler>spoiler</tg-spoiler>", "||spoiler||"),
        ("`code`", "<code>code</code>", "`code`"),
    ],
)
def test_inline_emphasis_both_modes(src: str, html_frag: str, mdv2_frag: str) -> None:
    assert to_telegram(src, "HTML") == html_frag
    assert to_telegram(src, "MarkdownV2") == mdv2_frag


def test_blockquote_both_modes() -> None:
    assert to_telegram("> quoted", "HTML") == "<blockquote>quoted</blockquote>"
    assert to_telegram("> quoted", "MarkdownV2") == ">quoted"


def test_expandable_blockquote_both_modes() -> None:
    html_out = to_telegram("**>secret", "HTML")
    assert html_out == "<blockquote expandable>secret</blockquote>"
    mdv2_out = to_telegram("**>secret", "MarkdownV2")
    assert mdv2_out == ">secret||"


@pytest.mark.parametrize("mode", _MODES)
def test_code_block_keeps_language_fence(mode: str) -> None:
    out = to_telegram("```python\nx = 1\n```", mode)
    if mode == "HTML":
        assert '<pre><code class="language-python">' in out
        assert "x = 1" in out
    else:
        assert out == "```python\nx = 1\n```"


def test_html_escaping_safe() -> None:
    # Literal angle brackets / ampersand are entity-escaped, not left as markup.
    out = to_telegram("a < b & c > d", "HTML")
    assert out == "a &lt; b &amp; c &gt; d"
    # Inside code spans too.
    code_out = to_telegram("`a<b&c`", "HTML")
    assert code_out == "<code>a&lt;b&amp;c</code>"


def test_markdownv2_escaping_safe() -> None:
    # Reserved chars in literal text are backslash-escaped.
    out = to_telegram("price is 1.50 (USD)!", "MarkdownV2")
    assert out == r"price is 1\.50 \(USD\)\!"


@pytest.mark.parametrize("mode", _MODES)
def test_link_renders(mode: str) -> None:
    out = to_telegram("[site](https://example.com)", mode)
    if mode == "HTML":
        assert out == '<a href="https://example.com">site</a>'
    else:
        assert out == "[site](https://example.com)"


def test_unknown_mode_falls_back_to_html() -> None:
    assert to_telegram("**x**", "weird") == "<b>x</b>"


def test_code_span_not_reinterpreted_as_emphasis() -> None:
    # Asterisks inside inline code must stay literal, not become <b>.
    out = to_telegram("`a*b*c`", "HTML")
    assert out == "<code>a*b*c</code>"


def test_plain_text_passthrough_both_modes() -> None:
    assert to_telegram("hello world", "HTML") == "hello world"
    assert to_telegram("hello world", "MarkdownV2") == "hello world"


class _CaptureAdapter(TelegramAdapter):
    """Capture Bot API calls without network; records (method, body) tuples."""

    def __init__(self, parse_mode: str) -> None:
        super().__init__(
            config=TelegramConfig(bot_token="t", parse_mode=parse_mode),  # type: ignore[arg-type]
        )
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def _ensure_client(self) -> httpx.AsyncClient:
        # Non-None sentinel so client guards pass; _api is overridden, so the
        # sentinel is never used as a real client.
        return cast("httpx.AsyncClient", object())

    async def _api(self, method: str, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((method, dict(body)))
        return {"ok": True, "result": {"message_id": 123}}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", _MODES)
async def test_send_text_applies_converter_and_parse_mode(mode: str) -> None:
    adapter = _CaptureAdapter(mode)
    ids = await adapter._send_text(
        chat_id=5,
        chunks=["**hi** | a | b |"],
        thread_id=None,
        reply_to_int=None,
        disable_preview=True,
        reply_markup_first=None,
        edit_first=None,
    )
    assert ids == ["123"]
    method, body = adapter.calls[0]
    assert method == "sendMessage"
    assert body["parse_mode"] == mode
    assert body["text"] == to_telegram("**hi** | a | b |", mode)
    if mode == "HTML":
        assert "<b>hi</b>" in body["text"]
    else:
        assert "*hi*" in body["text"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", _MODES)
async def test_edit_message_text_applies_converter_and_parse_mode(mode: str) -> None:
    adapter = _CaptureAdapter(mode)
    ok = await adapter.edit_message_text(
        chat_id=5,
        message_id=9,
        text="**hi**",
    )
    assert ok is True
    method, body = adapter.calls[0]
    assert method == "editMessageText"
    assert body["parse_mode"] == mode
    assert body["text"] == to_telegram("**hi**", mode)


def _workspace_with_parse_mode(value: str | None) -> WorkspaceConfig:
    tg = TelegramChannelConfig()
    if value is not None:
        tg.parse_mode = value
    channels = ChannelsWorkspaceSectionConfig(telegram=tg)
    return WorkspaceConfig(
        schema_version=1,
        channels=channels,
        gateway=GatewayConfig(token="${SECRET:keychain:sevn.gateway.token}"),
    )


def test_config_defaults_parse_mode_html() -> None:
    cfg = telegram_config_from_workspace(_workspace_with_parse_mode(None), bot_token="t")
    assert cfg.parse_mode == "HTML"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HTML", "HTML"),
        ("html", "HTML"),
        ("MarkdownV2", "MarkdownV2"),
        ("markdownv2", "MarkdownV2"),
        ("garbage", "HTML"),
    ],
)
def test_config_resolves_parse_mode(raw: str, expected: str) -> None:
    cfg = telegram_config_from_workspace(_workspace_with_parse_mode(raw), bot_token="t")
    assert cfg.parse_mode == expected


@pytest.mark.parametrize("mode", _MODES)
def test_bold_wrapping_inline_code_restores_nested_span(mode: str) -> None:
    """Bold wrapping inline code (``**`serp`**``) must keep the code span.

    Regression for the stashed-token restore bug where a nested inline-code
    token wrapped by bold was never restored and leaked as a bare ``P0``.
    """
    out = _convert_inline("**`serp`**", mode)
    assert "\x00" not in out
    if mode == "HTML":
        assert out == "<b><code>serp</code></b>"
    else:
        assert out == "*`serp`*"


@pytest.mark.parametrize("mode", _MODES)
def test_incident_line_no_bare_placeholder_leak(mode: str) -> None:
    """The real incident line renders code spans, never bare ``P0``/``P2``."""
    line = (
        'When `load_tool("web_search")` returns readiness `needs_key`, I should '
        "immediately switch to **`serp`**, not attempt `web_search`."
    )
    out = _convert_inline(line, mode)
    assert "\x00" not in out
    assert "serp" in out
    assert "web_search" in out
    # No stashed placeholder leaked where a rendered code span belongs.
    assert "P0" not in out
    assert "P2" not in out


@pytest.mark.parametrize("mode", _MODES)
def test_bold_wrapping_link_with_inline_code(mode: str) -> None:
    """Bold wrapping a link whose label holds inline code restores every span."""
    out = _convert_inline("**bold [label with `code`](https://example.com) tail**", mode)
    assert "\x00" not in out
    assert "code" in out
    if mode == "HTML":
        assert out.startswith("<b>")
        assert out.endswith("</b>")
        assert "<code>code</code>" in out
        assert '<a href="https://example.com">' in out
