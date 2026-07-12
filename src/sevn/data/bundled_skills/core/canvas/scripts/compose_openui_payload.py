#!/usr/bin/env python3
"""Bundled ``canvas`` skill — wrap HTML for native ``openui_render``.

Module: sevn.data.bundled_skills.core.canvas.scripts.compose_openui_payload
Depends: argparse, pathlib, sevn.lcm.script_cli, sevn.ui.openui.canvas_compose

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sevn.lcm.script_cli import write_error, write_ok
from sevn.ui.openui.canvas_compose import build_openui_payload


def _read_html(*, inline: str | None, path: str | None) -> str:
    """Resolve HTML from inline text or a workspace-relative file.

    Args:
        inline (str | None): Inline HTML fragment.
        path (str | None): File path when inline is absent.

    Returns:
        str: HTML body text.

    Raises:
        ValueError: When neither or both sources are provided.

    Examples:
        >>> _read_html(inline="<p>x</p>", path=None)
        '<p>x</p>'
    """
    if inline and path:
        msg = "provide only one of --html or --html-file"
        raise ValueError(msg)
    if inline:
        return inline
    if path:
        return Path(path).read_text(encoding="utf-8")
    msg = "one of --html or --html-file is required"
    raise ValueError(msg)


def main() -> int:
    """Run OpenUI payload wrapper CLI.

    Returns:
        int: ``0`` on success; ``1`` on validation failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", default=None)
    parser.add_argument("--html-file", default=None)
    parser.add_argument("--fallback-text", required=True)
    parser.add_argument("--title", default=None)
    parser.add_argument("--output", choices=("live", "screenshot", "pdf"), default="live")
    args = parser.parse_args()
    try:
        html_fragment = _read_html(inline=args.html, path=args.html_file)
    except (ValueError, OSError) as exc:
        write_error(code="VALIDATION_ERROR", error=str(exc))
        return 1
    payload = build_openui_payload(
        html_fragment=html_fragment,
        fallback_text=args.fallback_text,
        title=args.title,
        output=args.output,
    )
    write_ok(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
