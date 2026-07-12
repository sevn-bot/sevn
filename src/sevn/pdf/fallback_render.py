"""Pure-Python PDF fallback when WeasyPrint native libs are unavailable (Wave W6 / D4).

Module: sevn.pdf.fallback_render
Depends: fpdf2 (optional)

Exports:
    fpdf2_available — whether fpdf2 is importable.
    normalize_fallback_text — punctuation / glyph normalisation for fpdf2.
    render_pdf_fpdf2_fallback — render plain text / simple markdown to PDF bytes.

Examples:
    >>> fpdf2_available() or True  # doctest: +SKIP
    True
"""

from __future__ import annotations

import html as html_module
import importlib.util
import re
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from fpdf import FPDF

_HAS_FPDF2: Final[bool] = importlib.util.find_spec("fpdf") is not None

_TABLE_ROW_RE: Final[re.Pattern[str]] = re.compile(r"^\s*\|(.+)\|\s*$")
_TABLE_SEP_RE: Final[re.Pattern[str]] = re.compile(r"^\s*\|[-:\s|]+\|\s*$")

_FONT_FAMILY: Final[str] = "DejaVuSans"
_ASSETS_DIR: Final[Path] = Path(__file__).resolve().parent / "assets"
_FONT_REGULAR: Final[Path] = _ASSETS_DIR / "DejaVuSans.ttf"
_FONT_BOLD: Final[Path] = _ASSETS_DIR / "DejaVuSans-Bold.ttf"

_PUNCT_NORMALIZE: Final[dict[str, str]] = {
    "\u2014": "-",  # em dash
    "\u2013": "-",  # en dash
    "\u2018": "'",  # left single quote
    "\u2019": "'",  # right single quote
    "\u201c": '"',  # left double quote
    "\u201d": '"',  # right double quote
    "\u2026": "...",  # ellipsis
    "\u00a0": " ",  # non-breaking space
}


def fpdf2_available() -> bool:
    """Return whether ``fpdf2`` is installed.

    Returns:
        bool: ``True`` when ``from fpdf import FPDF`` succeeds.

    Examples:
        >>> isinstance(fpdf2_available(), bool)
        True
    """
    return _HAS_FPDF2


def _strip_html_tags(text: str) -> str:
    """Best-effort strip HTML tags for fallback rendering.

    Args:
        text (str): HTML or plain text.

    Returns:
        str: Plain text suitable for fpdf2.

    Examples:
        >>> _strip_html_tags("<p>Hi</p>")
        'Hi'
    """
    no_tags = re.sub(r"<[^>]+>", "", text)
    return html_module.unescape(no_tags).strip()


def _normalize_punctuation(text: str) -> str:
    """Map common Unicode punctuation to ASCII before fpdf2 render.

    Args:
        text (str): Input text.

    Returns:
        str: Punctuation-normalised text.

    Examples:
        >>> _normalize_punctuation("Hello \u2014 world")
        'Hello - world'
    """
    for src, dst in _PUNCT_NORMALIZE.items():
        text = text.replace(src, dst)
    return text


def _replace_unrenderable_glyphs(text: str) -> str:
    """Replace non-ASCII glyphs with ``?`` when a Unicode font is unavailable.

    Args:
        text (str): Input text.

    Returns:
        str: Text safe for Latin-1-only fpdf2 fonts.

    Examples:
        >>> _replace_unrenderable_glyphs("\u4e2d\u6587")
        '??'
    """
    return "".join(ch if ord(ch) < 128 else "?" for ch in text)


def normalize_fallback_text(text: str, *, aggressive: bool = False) -> str:
    """Normalise text for the fpdf2 fallback renderer.

    Args:
        text (str): Raw body text.
        aggressive (bool, optional): When ``True``, replace remaining non-ASCII
            glyphs with ``?``. Defaults to ``False``.

    Returns:
        str: Text ready for ``multi_cell``.

    Examples:
        >>> normalize_fallback_text("Smart \u201cquotes\u201d")
        'Smart "quotes"'
    """
    out = _normalize_punctuation(text)
    if aggressive:
        out = _replace_unrenderable_glyphs(out)
    return out


def _bundled_fonts_available() -> bool:
    """Return whether bundled DejaVu TTF assets are present on disk.

    Returns:
        bool: ``True`` when regular and bold fonts exist.

    Examples:
        >>> isinstance(_bundled_fonts_available(), bool)
        True
    """
    return _FONT_REGULAR.is_file() and _FONT_BOLD.is_file()


def _register_unicode_fonts(pdf: FPDF) -> str:
    """Register bundled DejaVu fonts on an ``FPDF`` instance.

    Args:
        pdf (object): ``fpdf.FPDF`` instance.

    Returns:
        str: Font family name to pass to ``set_font``.

    Examples:
        >>> _register_unicode_fonts.__name__
        '_register_unicode_fonts'
    """
    if _bundled_fonts_available():
        pdf.add_font(_FONT_FAMILY, "", str(_FONT_REGULAR))
        pdf.add_font(_FONT_FAMILY, "B", str(_FONT_BOLD))
        return _FONT_FAMILY
    return "Helvetica"


def _markdown_lines(markdown: str) -> list[tuple[str, str]]:
    """Parse markdown into fpdf2 render segments (heading, table, text).

    Args:
        markdown (str): Markdown or plain text body.

    Returns:
        list[tuple[str, str]]: ``(kind, payload)`` segments where ``kind`` is
        ``heading``, ``table``, or ``text``.

    Examples:
        >>> segs = _markdown_lines("# Title\\n\\nBody")
        >>> segs[0][0]
        'heading'
    """
    segments: list[tuple[str, str]] = []
    lines = markdown.splitlines()
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        stripped = line.strip()
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            title = stripped[level:].strip()
            if title:
                segments.append(("heading", title))
            idx += 1
            continue
        if (
            _TABLE_ROW_RE.match(line)
            and idx + 1 < len(lines)
            and _TABLE_SEP_RE.match(lines[idx + 1])
        ):
            table_lines = [line]
            idx += 2
            while idx < len(lines) and _TABLE_ROW_RE.match(lines[idx]):
                table_lines.append(lines[idx])
                idx += 1
            segments.append(("table", "\n".join(table_lines)))
            continue
        if stripped:
            text_buf = [stripped]
            idx += 1
            while (
                idx < len(lines) and lines[idx].strip() and not lines[idx].strip().startswith("#")
            ):
                if _TABLE_ROW_RE.match(lines[idx]):
                    break
                text_buf.append(lines[idx].strip())
                idx += 1
            segments.append(("text", "\n".join(text_buf)))
            continue
        idx += 1
    return segments


def _parse_table(table_blob: str) -> list[list[str]]:
    """Parse a markdown pipe table into rows of cell strings.

    Args:
        table_blob (str): Markdown table lines including header and separator.

    Returns:
        list[list[str]]: Rows of cell values.

    Examples:
        >>> rows = _parse_table("| A | B |\\n|---|---|\\n| 1 | 2 |")
        >>> rows[0] == ["A", "B"]
        True
    """
    rows: list[list[str]] = []
    for line in table_blob.splitlines():
        if _TABLE_SEP_RE.match(line):
            continue
        match = _TABLE_ROW_RE.match(line)
        if not match:
            continue
        cells = [cell.strip() for cell in match.group(1).split("|")]
        rows.append(cells)
    return rows


def _render_fpdf2_body(
    pdf: FPDF,
    *,
    html: str | None,
    markdown: str | None,
    body: str,
    font_family: str,
) -> None:
    """Render normalised body content onto an initialised ``FPDF`` page.

    Args:
        pdf (FPDF): ``fpdf.FPDF`` with one page added.
        html (str | None): Original HTML input when not using markdown mode.
        markdown (str | None): Original markdown input when set.
        body (str): Normalised plain-text body for HTML mode.
        font_family (str): Registered font family name.

    Examples:
        >>> _render_fpdf2_body.__name__
        '_render_fpdf2_body'
    """
    if markdown is not None:
        for kind, payload in _markdown_lines(markdown):
            if kind == "heading":
                pdf.set_font(font_family, style="B", size=14)
                pdf.multi_cell(0, 8, payload)
                pdf.set_font(font_family, size=11)
                pdf.ln(2)
            elif kind == "table":
                rows = _parse_table(payload)
                if rows:
                    col_count = max(len(r) for r in rows)
                    width = pdf.w / max(col_count, 1) - 10
                    pdf.set_font(font_family, size=10)
                    for row_idx, row in enumerate(rows):
                        for _col_idx, cell in enumerate(row):
                            x = pdf.get_x()
                            pdf.multi_cell(width, 6, cell, border=1)
                            pdf.set_xy(x + width, pdf.get_y() - 6)
                        pdf.ln(6)
                        if row_idx == 0:
                            pdf.set_font(font_family, style="B", size=10)
                        else:
                            pdf.set_font(font_family, size=10)
                    pdf.ln(4)
            else:
                pdf.multi_cell(0, 6, payload)
                pdf.ln(2)
    else:
        pdf.multi_cell(0, 6, body)


def render_pdf_fpdf2_fallback(
    *,
    html: str | None = None,
    markdown: str | None = None,
) -> bytes | None:
    """Render a minimal PDF using fpdf2 when WeasyPrint is unavailable.

    Args:
        html (str | None, optional): HTML fragment (tags stripped).
        markdown (str | None, optional): Markdown/plain text (headings + simple tables).

    Returns:
        bytes | None: PDF bytes on success; ``None`` when fpdf2 is missing or render fails.

    Examples:
        >>> out = render_pdf_fpdf2_fallback(markdown="Hello")  # doctest: +SKIP
    """
    if not _HAS_FPDF2:
        return None
    if html is not None and markdown is not None:
        return None
    if html is None and markdown is None:
        return None

    from fpdf import FPDF

    raw_body = _strip_html_tags(html) if html is not None else (markdown or "")
    if not raw_body.strip():
        return None

    try:
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        font_family = _register_unicode_fonts(pdf)
        pdf.set_font(font_family, size=11)

        if markdown is not None:
            normalized_md = normalize_fallback_text(markdown)
            _render_fpdf2_body(
                pdf,
                html=None,
                markdown=normalized_md,
                body="",
                font_family=font_family,
            )
        else:
            normalized_body = normalize_fallback_text(raw_body)
            _render_fpdf2_body(
                pdf,
                html=html,
                markdown=None,
                body=normalized_body,
                font_family=font_family,
            )

        out = pdf.output()
    except Exception:
        try:
            pdf = FPDF()
            pdf.set_auto_page_break(auto=True, margin=15)
            pdf.add_page()
            font_family = _register_unicode_fonts(pdf)
            pdf.set_font(font_family, size=11)
            if markdown is not None:
                aggressive_md = normalize_fallback_text(markdown, aggressive=True)
                _render_fpdf2_body(
                    pdf,
                    html=None,
                    markdown=aggressive_md,
                    body="",
                    font_family=font_family,
                )
            else:
                aggressive_body = normalize_fallback_text(raw_body, aggressive=True)
                _render_fpdf2_body(
                    pdf,
                    html=html,
                    markdown=None,
                    body=aggressive_body,
                    font_family=font_family,
                )
            out = pdf.output()
        except Exception:
            return None

    return bytes(out) if isinstance(out, (bytes, bytearray)) else out.encode("latin-1")


__all__ = [
    "fpdf2_available",
    "normalize_fallback_text",
    "render_pdf_fpdf2_fallback",
]
