"""WeasyPrint rasteriser (`specs/29-openui.md` §4.4).
Module: sevn.ui.openui.rasteriser
Depends: optional weasyprint
Exports:
    rasterise_png_bytes — HTML fragment → PNG bytes.
    rasterise_pdf_bytes — HTML fragment → PDF bytes.
"""

from __future__ import annotations

import contextlib
import io
from typing import Any, cast

from loguru import logger


def _import_weasyprint_html() -> Any:
    """Import WeasyPrint's ``HTML`` class with stdout muted.

    WeasyPrint prints a multi-line "could not import some external libraries"
    banner to **stdout** when its native libs (pango/cairo/gobject) are missing.
    Skill scripts contract on stdout being a single JSON envelope, so an unmuted
    import corrupts that contract — a successful fpdf2 fallback render was still
    reported to the agent as an unparseable failure (P3,
    ``plan/live-session-pdf-render-grounding-failures-plan.md``). Mirror the
    redirect already used by ``sevn.pdf.doctor_check.probe_weasyprint_render``.

    Returns:
        Any: The ``weasyprint.HTML`` class.

    Raises:
        ImportError: When the ``weasyprint`` package is not installed.
        OSError: When WeasyPrint's native libraries cannot be loaded.

    Examples:
        >>> _import_weasyprint_html.__name__
        '_import_weasyprint_html'
    """
    with contextlib.redirect_stdout(io.StringIO()):
        from weasyprint import HTML
    return HTML


def _html_document(inner_html: str, *, title: str = "OpenUI") -> str:
    """Wrap a body fragment in a minimal HTML5 document shell.
    Args:
        inner_html (str): Sanitised markup for ``<body>``.
        title (str): Document ``<title>`` text.
    Returns:
        str: Full HTML document string.
    Examples:
        >>> "<body>" in _html_document("<span>z</span>") and "z" in _html_document("<span>z</span>")
        True
    """
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title></head>
<body>{inner_html}</body></html>"""


def rasterise_png_bytes(inner_html: str, *, base_url: str | None = None) -> bytes:
    """Rasterise sanitised HTML to PNG using WeasyPrint.
    Args:
        inner_html (str): Sanitised body fragment.
        base_url (str | None): Optional URL base for relative resolution.
    Returns:
        bytes: PNG image bytes (may be empty on failure).
    Examples:
        >>> rasterise_png_bytes.__name__
        'rasterise_png_bytes'
    """
    try:
        HTML = _import_weasyprint_html()
    except (ImportError, OSError):
        logger.warning("weasyprint unavailable; rasterise_png_bytes returns empty")
        return b""
    try:
        doc = HTML(string=_html_document(inner_html), base_url=base_url or None)
        png_bytes: bytes | Any = cast("Any", doc).write_png()
        return bytes(png_bytes) if png_bytes else b""
    except Exception:
        logger.exception("weasyprint PNG rasterise failed")
        return b""


def rasterise_pdf_bytes(inner_html: str, *, base_url: str | None = None) -> bytes:
    """Rasterise sanitised HTML to PDF using WeasyPrint.
    Args:
        inner_html (str): Sanitised body fragment.
        base_url (str | None): Optional URL base for relative resolution.
    Returns:
        bytes: PDF bytes (may be empty on failure).
    Examples:
        >>> rasterise_pdf_bytes.__name__
        'rasterise_pdf_bytes'
    """
    try:
        HTML = _import_weasyprint_html()
    except (ImportError, OSError):
        logger.warning("weasyprint unavailable; rasterise_pdf_bytes returns empty")
        return b""
    try:
        doc = HTML(string=_html_document(inner_html), base_url=base_url or None)
        pdf_bytes: bytes | Any = doc.write_pdf()
        return bytes(pdf_bytes) if pdf_bytes else b""
    except Exception:
        logger.exception("weasyprint PDF rasterise failed")
        return b""


__all__ = ["rasterise_pdf_bytes", "rasterise_png_bytes"]
