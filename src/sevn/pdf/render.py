"""Render HTML or markdown to PDF bytes for the bundled ``pdf`` skill.

Module: sevn.pdf.render
Depends: html, sevn.pdf.fallback_render, sevn.ui.openui.rasteriser

Exports:
    render_pdf_bytes — convert HTML or markdown input to PDF bytes (WeasyPrint + fpdf2 fallback).
"""

from __future__ import annotations

import html as html_module

from sevn.pdf.fallback_render import render_pdf_fpdf2_fallback
from sevn.ui.openui.rasteriser import rasterise_pdf_bytes


def _markdown_to_html(markdown: str) -> str:
    """Wrap markdown in a minimal HTML shell for WeasyPrint.

    Args:
        markdown (str): Plain markdown or text body.

    Returns:
        str: HTML fragment suitable for rasterisation.

    Examples:
        >>> "Hello" in _markdown_to_html("Hello")
        True
    """
    escaped = html_module.escape(markdown)
    return (
        '<div style="white-space: pre-wrap; font-family: sans-serif; '
        f'line-height: 1.4;">{escaped}</div>'
    )


def render_pdf_bytes(
    *,
    html: str | None = None,
    markdown: str | None = None,
) -> tuple[bool, bytes | str]:
    """Render HTML or markdown content to PDF bytes.

    Args:
        html (str | None, optional): HTML fragment or document body.
        markdown (str | None, optional): Markdown/plain text body.

    Returns:
        tuple[bool, bytes | str]: ``(True, pdf_bytes)`` on success or
        ``(False, error_message)`` when input is invalid or rasterisation fails.

    Examples:
        >>> ok, out = render_pdf_bytes(html="<p>Hi</p>")  # doctest: +SKIP
    """
    if html is not None and markdown is not None:
        return False, "pdf: provide exactly one of html or markdown"
    if html is None and markdown is None:
        return False, "pdf: html or markdown is required"
    body = html if html is not None else _markdown_to_html(markdown or "")
    if not body.strip():
        return False, "pdf: empty input"
    blob = rasterise_pdf_bytes(body)
    if blob:
        return True, blob

    fallback = render_pdf_fpdf2_fallback(html=html, markdown=markdown)
    if fallback:
        return True, fallback

    return False, (
        "pdf: WeasyPrint unavailable (missing native libs?) and fpdf2 fallback failed; "
        "run `sevn doctor` for install commands"
    )
