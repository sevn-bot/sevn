r"""Outbound Markdown → Telegram converter (`specs/18` §formatting, plan W9).

Module: sevn.channels.telegram_format
Depends: html, re

Telegram's ``sendMessage``/``editMessageText`` accept either ``HTML`` or
``MarkdownV2`` ``parse_mode``. Neither understands GitHub-flavoured
Markdown: a ``| col | col |`` pipe table renders as literal pipes and
``**bold**`` shows the asterisks. The legacy pipeline
(:mod:`sevn.channels.markdown_safe`) is *escape-only* — it backslash-escapes
every reserved character, so intentional emphasis is also escaped and nothing
renders rich.

This module is the net-new outbound converter. :func:`to_telegram` takes the
agent's Markdown reply and the configured ``parse_mode`` and returns a string
already in the target markup, with:

- pipe tables rendered as an aligned ``<pre>`` / fenced code block (monospace
  keeps columns aligned on every client);
- fenced code blocks preserved with their language hint;
- inline code, bold, italic, underline, strikethrough, spoiler, links and
  blockquotes (incl. expandable ``**>`` blockquotes) translated to the target
  markup;
- every remaining literal character escaped correctly for the mode (HTML
  entity-escape vs MarkdownV2 reserved-char backslash-escape).

The two emphasis syntaxes Telegram diverges on:

- **underline** — HTML ``<u>``; MarkdownV2 ``__text__``. Markdown source uses
  ``__text__`` for underline here (CommonMark would call it bold, but Telegram
  treats ``__`` as underline, so we map source ``__`` → underline).
- **spoiler** — HTML ``<tg-spoiler>``; MarkdownV2 ``||text||``. Markdown source
  uses ``||text||``.

Exports:
    to_telegram — Convert a Markdown reply to the target Telegram parse_mode.
    markdown_tables_to_pre — Render pipe tables as aligned monospace blocks.

Examples:
    >>> to_telegram("**hi**", "HTML")
    '<b>hi</b>'
    >>> to_telegram("**hi**", "MarkdownV2")
    '*hi*'
"""

from __future__ import annotations

import html
import re
import uuid
from collections.abc import Callable

# MarkdownV2 reserved characters that must be backslash-escaped inside ordinary
# text (Telegram Bot API §formatting-options). Inside ``pre``/``code`` only
# `` ` `` and ``\`` are special, handled separately.
_MDV2_TEXT_RESERVED = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")

# A fenced code block: ```lang\n...\n``` (lang optional). Non-greedy body.
_FENCE_RE = re.compile(r"```([^\n`]*)\n(.*?)```", re.DOTALL)

# A run of consecutive Markdown pipe-table rows (header + separator + body).
# A table needs a separator row of dashes/colons between pipes.
_TABLE_BLOCK_RE = re.compile(
    r"(?m)^[ \t]*\|.*\|[ \t]*\n[ \t]*\|[ \t]*:?-{1,}.*\|[ \t]*\n(?:[ \t]*\|.*\|[ \t]*\n?)*",
)

# Inline spans, evaluated against text that has had code/fences carved out.
# Order matters: longer/Greedier delimiters (``**``, ``__``, ``~~``, ``||``)
# before single-char ones.
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_UNDERLINE_RE = re.compile(r"__(.+?)__")
_STRIKE_RE = re.compile(r"~~(.+?)~~")
_SPOILER_RE = re.compile(r"\|\|(.+?)\|\|")
_ITALIC_STAR_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_ITALIC_USCORE_RE = re.compile(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)")
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")


def _split_table_rows(block: str) -> list[list[str]]:
    r"""Parse a Markdown pipe-table block into a grid of trimmed cells.

    The separator row (``|---|:--:|``) is dropped; remaining rows are split on
    unescaped pipes and trimmed. Leading/trailing empty cells from the outer
    pipes are removed.

    Args:
        block (str): The raw multi-line pipe-table block (header + separator
            + body rows).

    Returns:
        list[list[str]]: Rows of cell strings, separator row excluded.

    Examples:
        >>> _split_table_rows("| A | B |\n| - | - |\n| 1 | 2 |\n")
        [['A', 'B'], ['1', '2']]
        >>> _split_table_rows("| x |\n|---|\n")
        [['x']]
    """
    rows: list[list[str]] = []
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Separator row: only pipes, dashes, colons, spaces.
        if re.fullmatch(r"\|?[ \t:|-]+\|?", stripped) and "-" in stripped:
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        rows.append(cells)
    return rows


def markdown_tables_to_pre(text: str) -> str:
    r"""Replace Markdown pipe tables with aligned monospace ``<pre>`` blocks.

    Each detected table is rendered as a fixed-width grid (columns padded to
    the widest cell) wrapped in a sentinel ``\x00PRE...\x00`` token so later
    emphasis passes leave it untouched; the caller substitutes the real
    ``<pre>``/```` ``` ```` wrapper per parse_mode. Non-table text is returned
    verbatim.

    Args:
        text (str): Markdown text that may contain pipe tables.

    Returns:
        str: ``text`` with each table block replaced by an aligned monospace
        grid (still plain text; no markup wrapper applied yet).

    Examples:
        >>> out = markdown_tables_to_pre("| A | BB |\n|---|----|\n| 1 | 2 |\n")
        >>> "A  BB" in out
        True
        >>> markdown_tables_to_pre("no table here")
        'no table here'
    """

    def _render(match: re.Match[str]) -> str:
        rows = _split_table_rows(match.group(0))
        if not rows:
            return match.group(0)
        ncols = max(len(r) for r in rows)
        norm = [r + [""] * (ncols - len(r)) for r in rows]
        widths = [max(len(r[c]) for r in norm) for c in range(ncols)]
        lines = [
            "  ".join(cell.ljust(widths[c]) for c, cell in enumerate(row)).rstrip() for row in norm
        ]
        return "\n".join(lines)

    return _TABLE_BLOCK_RE.sub(_render, text)


def _escape_html_text(text: str) -> str:
    """HTML-entity-escape literal text for Telegram ``parse_mode=HTML``.

    Telegram's HTML parser only requires ``<``, ``>`` and ``&`` to be escaped
    in text nodes (quotes are fine outside attribute values).

    Args:
        text (str): Literal (non-markup) text.

    Returns:
        str: Text with ``&``, ``<`` and ``>`` replaced by entities.

    Examples:
        >>> _escape_html_text("a < b & c > d")
        'a &lt; b &amp; c &gt; d'
        >>> _escape_html_text("plain")
        'plain'
    """
    return html.escape(text, quote=False)


def _escape_mdv2_text(text: str) -> str:
    r"""Backslash-escape MarkdownV2 reserved chars in literal text.

    Args:
        text (str): Literal (non-markup) text.

    Returns:
        str: Text with every reserved MarkdownV2 char backslash-escaped.

    Examples:
        >>> _escape_mdv2_text("a.b")
        'a\\.b'
        >>> _escape_mdv2_text("plain")
        'plain'
    """
    return _MDV2_TEXT_RESERVED.sub(r"\\\1", text)


def _escape_mdv2_code(text: str) -> str:
    r"""Escape text destined for a MarkdownV2 ``code``/``pre`` span.

    Inside code, only the backtick and backslash are special.

    Args:
        text (str): Raw code content.

    Returns:
        str: Code content with ``\`` and `` ` `` backslash-escaped.

    Examples:
        >>> _escape_mdv2_code("a`b")
        'a\\`b'
        >>> _escape_mdv2_code("x")
        'x'
    """
    return text.replace("\\", "\\\\").replace("`", "\\`")


def _convert_inline(text: str, parse_mode: str) -> str:
    r"""Translate inline Markdown spans + escape the literal remainder.

    Inline code is carved out first (its contents are escaped for the mode but
    never treated as emphasis), then links, then the emphasis family, then the
    surviving literal text is escaped. Operates on a single logical line/run
    that contains no fenced code or tables (those are handled upstream).

    Args:
        text (str): A run of inline Markdown with no fences/tables.
        parse_mode (str): ``"HTML"`` or ``"MarkdownV2"``.

    Returns:
        str: The run rendered in the target parse_mode.

    Examples:
        >>> _convert_inline("a **b** c", "HTML")
        'a <b>b</b> c'
        >>> _convert_inline("a `x` b", "MarkdownV2")
        'a `x` b'
    """
    html_mode = parse_mode == "HTML"
    placeholders: dict[str, str] = {}
    # Per-call nonce so a failed restore can never render as plausible text
    # (e.g. "P0") and crafted input can't collide with a real token. Hex has no
    # regex metacharacters and no char escaped by either mode's literal-escape,
    # so the token survives being passed through a nested _convert_inline call.
    nonce = uuid.uuid4().hex[:12]

    def _stash(rendered: str) -> str:
        token = f"\x00P{nonce}:{len(placeholders)}\x00"
        placeholders[token] = rendered
        return token

    # Inline code first — contents must not be re-interpreted as emphasis.
    def _code(m: re.Match[str]) -> str:
        body = m.group(1)
        if html_mode:
            return _stash(f"<code>{_escape_html_text(body)}</code>")
        return _stash(f"`{_escape_mdv2_code(body)}`")

    text = _INLINE_CODE_RE.sub(_code, text)

    # Links: [label](url). Label may contain emphasis; render it recursively.
    def _link(m: re.Match[str]) -> str:
        label, url = m.group(1), m.group(2)
        if html_mode:
            inner = _convert_inline(label, parse_mode)
            return _stash(f'<a href="{html.escape(url, quote=True)}">{inner}</a>')
        inner = _convert_inline(label, parse_mode)
        safe_url = url.replace("\\", "\\\\").replace(")", "\\)")
        return _stash(f"[{inner}]({safe_url})")

    text = _LINK_RE.sub(_link, text)

    def _wrap(
        open_h: str, close_h: str, open_m: str, close_m: str
    ) -> Callable[[re.Match[str]], str]:
        def _repl(m: re.Match[str]) -> str:
            inner = _convert_inline(m.group(1), parse_mode)
            if html_mode:
                return _stash(f"{open_h}{inner}{close_h}")
            return _stash(f"{open_m}{inner}{close_m}")

        return _repl

    text = _BOLD_RE.sub(_wrap("<b>", "</b>", "*", "*"), text)
    text = _UNDERLINE_RE.sub(_wrap("<u>", "</u>", "__", "__"), text)
    text = _STRIKE_RE.sub(_wrap("<s>", "</s>", "~", "~"), text)
    text = _SPOILER_RE.sub(_wrap("<tg-spoiler>", "</tg-spoiler>", "||", "||"), text)
    text = _ITALIC_STAR_RE.sub(_wrap("<i>", "</i>", "_", "_"), text)
    text = _ITALIC_USCORE_RE.sub(_wrap("<i>", "</i>", "_", "_"), text)

    # Escape the literal remainder, then restore rendered placeholders.
    escape = _escape_html_text if html_mode else _escape_mdv2_text
    parts = re.split(rf"(\x00P{nonce}:\d+\x00)", text)
    rebuilt = "".join(p if p in placeholders else escape(p) for p in parts)
    # Restore in reverse insertion order: a stashed value can only contain
    # tokens created strictly earlier (lower index), because nested spans like
    # ``**`code`**`` put earlier tokens inside a later token's value. Reverse
    # order therefore substitutes the outer token before the inner one it
    # references, which is provably complete.
    for token, rendered in reversed(placeholders.items()):
        rebuilt = rebuilt.replace(token, rendered)
    return rebuilt


def _render_pre(body: str, lang: str, parse_mode: str) -> str:
    r"""Wrap a preformatted block (table grid / code fence) for the mode.

    Args:
        body (str): Raw preformatted content (already aligned for tables).
        lang (str): Language hint for code fences (empty for tables).
        parse_mode (str): ``"HTML"`` or ``"MarkdownV2"``.

    Returns:
        str: A Telegram ``pre``/``code`` block in the target markup.

    Examples:
        >>> _render_pre("a < b", "", "HTML")
        '<pre>a &lt; b</pre>'
        >>> _render_pre("code", "py", "MarkdownV2")
        '```py\ncode\n```'
    """
    if parse_mode == "HTML":
        esc = _escape_html_text(body)
        if lang:
            return f'<pre><code class="language-{html.escape(lang, quote=True)}">{esc}</code></pre>'
        return f"<pre>{esc}</pre>"
    esc = _escape_mdv2_code(body)
    return f"```{lang}\n{esc}\n```"


def to_telegram(markdown: str, parse_mode: str) -> str:
    r"""Convert a Markdown reply to Telegram markup for ``parse_mode``.

    Pipeline: carve out fenced code blocks, render pipe tables as aligned
    monospace ``pre`` blocks, then walk the remaining text line by line —
    blockquotes (``>``/``**>`` expandable) become Telegram blockquotes and
    everything else has its inline spans translated and literals escaped. The
    result is safe to send with the matching ``parse_mode`` and never contains
    raw Markdown tables or unescaped reserved characters.

    Args:
        markdown (str): The agent's reply in (GitHub-flavoured) Markdown.
        parse_mode (str): ``"HTML"`` or ``"MarkdownV2"``. Any other value is
            treated as ``"HTML"``.

    Returns:
        str: ``markdown`` rendered in the target Telegram parse_mode.

    Examples:
        Bold maps to the mode's emphasis markup.

        >>> to_telegram("**bold**", "HTML")
        '<b>bold</b>'
        >>> to_telegram("**bold**", "MarkdownV2")
        '*bold*'

        A pipe table becomes an aligned monospace block, not raw pipes.

        >>> out = to_telegram("| A | B |\n|---|---|\n| 1 | 2 |\n", "HTML")
        >>> "<pre>" in out and "|" not in out
        True

        HTML special chars in literal text are entity-escaped.

        >>> to_telegram("a < b & c", "HTML")
        'a &lt; b &amp; c'

        A fenced code block keeps its language hint.

        >>> to_telegram("```py\nx=1\n```", "MarkdownV2")
        '```py\nx=1\n```'
    """
    mode = "MarkdownV2" if parse_mode == "MarkdownV2" else "HTML"
    # Per-call nonce hardens fence/table tokens against collision with crafted
    # input (consistency with _convert_inline; no ordering bug exists here).
    nonce = uuid.uuid4().hex[:12]

    # 1) Carve out fenced code blocks so their contents survive untouched.
    fences: dict[str, str] = {}

    def _stash_fence(m: re.Match[str]) -> str:
        lang = m.group(1).strip()
        body = m.group(2).rstrip("\n")
        token = f"\x00F{nonce}:{len(fences)}\x00"
        fences[token] = _render_pre(body, lang, mode)
        return token

    work = _FENCE_RE.sub(_stash_fence, markdown)

    # 2) Tables → aligned monospace, stashed as pre blocks.
    tables: dict[str, str] = {}

    def _stash_table(m: re.Match[str]) -> str:
        grid = markdown_tables_to_pre(m.group(0))
        token = f"\x00T{nonce}:{len(tables)}\x00"
        tables[token] = _render_pre(grid, "", mode)
        return token

    work = _TABLE_BLOCK_RE.sub(_stash_table, work)

    # 3) Walk remaining lines: blockquotes vs inline runs.
    out_lines: list[str] = []
    for raw_line in work.split("\n"):
        # Pass through stash tokens (whole-line fence/table placeholders).
        if raw_line in fences or raw_line in tables:
            out_lines.append(raw_line)
            continue
        expandable = bool(re.match(r"^\s*\*\*>", raw_line))
        quote = re.match(r"^\s*(?:\*\*)?>\s?(.*)$", raw_line)
        if quote is not None:
            inner = _convert_inline(quote.group(1), mode)
            if mode == "HTML":
                tag = "<blockquote expandable>" if expandable else "<blockquote>"
                out_lines.append(f"{tag}{inner}</blockquote>")
            else:
                # MarkdownV2 blockquote: each line prefixed with ``>``; the
                # expandable variant appends ``||`` after the block (here a
                # single line, so inline).
                out_lines.append(f">{inner}" + ("||" if expandable else ""))
            continue
        out_lines.append(_convert_inline(raw_line, mode))

    rendered = "\n".join(out_lines)

    # 4) Restore stashed fences and tables.
    for token, value in {**fences, **tables}.items():
        rendered = rendered.replace(token, value)
    return rendered


__all__ = [
    "markdown_tables_to_pre",
    "to_telegram",
]
