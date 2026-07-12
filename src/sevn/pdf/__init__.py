"""PDF render, read, and structured load helpers for bundled ``pdf`` skill scripts.

Module: sevn.pdf
Depends: sevn.pdf.render, sevn.pdf.read, sevn.pdf.load, sevn.pdf.paths

Exports:
    resolve_path_under_workspace — workspace-relative path guard.
    render_pdf_bytes — HTML or markdown → PDF bytes via WeasyPrint.
    pdfplumber_available — whether ``pdfplumber`` optional extra is installed.
    read_pdf — extract text, tables, and metadata with pdfplumber.
    openparse_available — whether ``openparse`` optional extra is installed.
    load_pdf — parse and chunk a PDF with openparse.
"""

from __future__ import annotations

from sevn.pdf.load import load_pdf, openparse_available
from sevn.pdf.paths import resolve_path_under_workspace
from sevn.pdf.read import pdfplumber_available, read_pdf
from sevn.pdf.render import render_pdf_bytes

__all__ = [
    "load_pdf",
    "openparse_available",
    "pdfplumber_available",
    "read_pdf",
    "render_pdf_bytes",
    "resolve_path_under_workspace",
]
