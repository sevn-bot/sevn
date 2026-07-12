"""pdfplumber-backed PDF extraction for the bundled ``pdf`` skill.

Module: sevn.pdf.read
Depends: pathlib, optional pdfplumber

Exports:
    pdfplumber_available — probe for pdfplumber import.
    read_pdf — extract text, tables, and metadata from a PDF file.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 — runtime file checks in read_pdf
from typing import Any

PDFPLUMBER_INSTALL_HINT = (
    "pdf_read: pdfplumber not installed (install optional extra: uv pip install 'sevn[pdf]')"
)


def pdfplumber_available() -> bool:
    """Return whether ``pdfplumber`` is importable.

    Returns:
        bool: True when the optional dependency is present.

    Examples:
        >>> isinstance(pdfplumber_available(), bool)
        True
    """
    try:
        import pdfplumber  # noqa: F401
    except ImportError:
        return False
    return True


def read_pdf(path: Path, *, include_tables: bool = True) -> tuple[bool, dict[str, Any] | str]:
    """Extract text, optional tables, and metadata from a PDF.

    Args:
        path (Path): Existing PDF file path.
        include_tables (bool, optional): When True, include table rows per page. Defaults to True.

    Returns:
        tuple[bool, dict[str, Any] | str]: ``(True, payload)`` on success or
        ``(False, error_message)`` when pdfplumber is missing or parsing fails.

    Examples:
        >>> ok, err = read_pdf(Path("/nonexistent/file.pdf"))
        >>> ok or isinstance(err, str)
        True
    """
    if not pdfplumber_available():
        return False, PDFPLUMBER_INSTALL_HINT
    if not path.is_file():
        return False, f"pdf_read: file not found: {path}"
    try:
        import pdfplumber
    except ImportError:
        return False, PDFPLUMBER_INSTALL_HINT

    try:
        with pdfplumber.open(path) as pdf:
            metadata = dict(pdf.metadata or {})
            pages: list[dict[str, object]] = []
            tables: list[dict[str, object]] = []
            for index, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                pages.append({"page": index, "text": text})
                if include_tables:
                    for table in page.extract_tables() or []:
                        tables.append({"page": index, "rows": table})
            payload: dict[str, Any] = {
                "path": str(path),
                "page_count": len(pdf.pages),
                "metadata": metadata,
                "pages": pages,
                "text": "\n\n".join(str(p["text"]) for p in pages),
            }
            if include_tables:
                payload["tables"] = tables
            return True, payload
    except Exception as exc:
        return False, f"pdf_read: {exc}"


__all__ = ["PDFPLUMBER_INSTALL_HINT", "pdfplumber_available", "read_pdf"]
