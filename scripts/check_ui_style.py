#!/usr/bin/env python3
"""Fail when operator UI CSS drifts from the sevn.bot design system contract.

Module: scripts.check_ui_style
Depends: pathlib, re, sys

Exports:
    main — CLI entry; scans surface CSS/HTML and packaged tokens.

Examples:
    >>> main() in (0, 1)
    True
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SURFACE_CSS = [
    ROOT / "src/sevn/ui/spa/dashboard/style.css",
    ROOT / "src/sevn/ui/webapp/style.css",
    ROOT / "src/sevn/onboarding/web_wizard/style.css",
]

SURFACE_HTML = [
    ROOT / "src/sevn/onboarding/web_wizard/index.html",
    ROOT / "src/sevn/ui/spa/dashboard/index.html",
    ROOT / "src/sevn/ui/webapp/index.html",
]

FORBIDDEN_VAR = re.compile(
    r"^\s*--(bg|panel|text|muted|line|accent|fg)\s*:",
    re.MULTILINE,
)

FORBIDDEN_HEX = re.compile(r"#[0-9a-fA-F]{3,8}")


def _check_surface_css(path: Path) -> list[str]:
    """Reject parallel palette vars and raw hex in a surface CSS file.

    Args:
        path (Path): CSS file path.

    Returns:
        list[str]: Violation messages (empty when OK).

    Examples:
        >>> import tempfile
        >>> p = Path(tempfile.mkdtemp()) / "s.css"
        >>> _ = p.write_text(":root { color: var(--sevn-fg); }\\n", encoding="utf-8")
        >>> _check_surface_css(p)
        []
    """
    errors: list[str] = []
    if not path.is_file():
        return errors
    text = path.read_text(encoding="utf-8")
    for match in FORBIDDEN_VAR.finditer(text):
        errors.append(f"{path}: parallel palette {match.group(0).strip()}")
    for match in FORBIDDEN_HEX.finditer(text):
        errors.append(f"{path}: raw hex {match.group(0)} (use --sevn-* tokens)")
    return errors


def _check_html(path: Path) -> list[str]:
    """Require shared ``index.css`` link in operator HTML surfaces.

    Args:
        path (Path): HTML file path.

    Returns:
        list[str]: Violation messages (empty when OK).

    Examples:
        >>> import tempfile
        >>> p = Path(tempfile.mkdtemp()) / "i.html"
        >>> _ = p.write_text("<link href='/style/index.css'>", encoding="utf-8")
        >>> _check_html(p)
        []
    """
    errors: list[str] = []
    if not path.is_file():
        return errors
    text = path.read_text(encoding="utf-8")
    if "/style/index.css" not in text and "style/index.css" not in text:
        errors.append(f"{path}: missing link to shared index.css (/style/ or style/)")
    return errors


def _check_packaged_style() -> list[str]:
    """Verify packaged ``src/sevn/ui/style/index.css`` exists and imports tokens.

    Returns:
        list[str]: Violation messages (empty when OK).

    Examples:
        >>> isinstance(_check_packaged_style(), list)
        True
    """
    errors: list[str] = []
    index = ROOT / "src/sevn/ui/style/index.css"
    if not index.is_file():
        errors.append("run `make styles-build` — missing src/sevn/ui/style/index.css")
        return errors
    body = index.read_text(encoding="utf-8")
    if "@import './tokens/colors.css'" not in body:
        errors.append(f"{index}: expected token import")
    return errors


def main() -> int:
    """Run UI style checks and print errors.

    Returns:
        int: Exit code (0 ok, 1 failures).

    Examples:
        >>> isinstance(main(), int)
        True
    """
    errors: list[str] = []
    for path in SURFACE_CSS:
        errors.extend(_check_surface_css(path))
    for path in SURFACE_HTML:
        errors.extend(_check_html(path))
    errors.extend(_check_packaged_style())
    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
