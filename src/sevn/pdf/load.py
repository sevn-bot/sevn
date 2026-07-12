"""openparse-backed structured PDF loading for the bundled ``pdf`` skill.

Module: sevn.pdf.load
Depends: pathlib, optional openparse

Exports:
    openparse_available — probe for openparse import.
    load_pdf — parse and chunk a PDF into structured nodes.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 — runtime file checks in load_pdf
from typing import Any

OPENPARSE_INSTALL_HINT = (
    "pdf_load: openparse not installed (install optional extra: uv pip install 'sevn[pdf]')"
)


def openparse_available() -> bool:
    """Return whether ``openparse`` is importable.

    Returns:
        bool: True when the optional dependency is present.

    Examples:
        >>> isinstance(openparse_available(), bool)
        True
    """
    try:
        import openparse  # noqa: F401
    except ImportError:
        return False
    return True


def _node_to_dict(node: object) -> dict[str, object]:
    """Serialise one openparse node to a JSON-friendly dict.

    Args:
        node (object): Parsed document node from openparse.

    Returns:
        dict[str, object]: Minimal node payload for agent consumption.

    Examples:
        >>> _node_to_dict({"text": "x"})
        {'variant': 'dict', 'text': 'x'}
    """
    if isinstance(node, dict):
        return {"variant": "dict", **node}
    text = getattr(node, "text", None)
    if text is None:
        text = str(node)
    variant = getattr(node, "variant", None) or type(node).__name__
    payload: dict[str, object] = {"text": str(text), "variant": str(variant)}
    for key in ("bbox", "page", "page_number", "metadata"):
        value = getattr(node, key, None)
        if value is not None:
            payload[key] = value
    return payload


def load_pdf(path: Path) -> tuple[bool, dict[str, Any] | str]:
    """Parse and chunk a PDF with openparse.

    Args:
        path (Path): Existing PDF file path.

    Returns:
        tuple[bool, dict[str, Any] | str]: ``(True, payload)`` with node list on success or
        ``(False, error_message)`` when openparse is missing or parsing fails.

    Examples:
        >>> ok, err = load_pdf(Path("/nonexistent/file.pdf"))
        >>> ok or isinstance(err, str)
        True
    """
    if not openparse_available():
        return False, OPENPARSE_INSTALL_HINT
    if not path.is_file():
        return False, f"pdf_load: file not found: {path}"
    try:
        import openparse
    except ImportError:
        return False, OPENPARSE_INSTALL_HINT

    try:
        parser = openparse.DocumentParser()
        parsed = parser.parse(str(path))
        nodes = [_node_to_dict(node) for node in parsed.nodes]
        return True, {
            "path": str(path),
            "node_count": len(nodes),
            "nodes": nodes,
        }
    except Exception as exc:
        return False, f"pdf_load: {exc}"


__all__ = ["OPENPARSE_INSTALL_HINT", "load_pdf", "openparse_available"]
