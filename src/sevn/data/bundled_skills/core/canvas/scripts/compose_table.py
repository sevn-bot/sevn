#!/usr/bin/env python3
"""Bundled ``canvas`` skill — compose a table layout for ``openui_render``.

Module: sevn.data.bundled_skills.core.canvas.scripts.compose_table
Depends: argparse, sevn.lcm.script_cli, sevn.ui.openui.canvas_compose

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse

from sevn.lcm.script_cli import write_error, write_ok
from sevn.ui.openui.canvas_compose import (
    build_openui_payload,
    compose_table_html,
    parse_json_list,
    table_fallback_text,
)


def main() -> int:
    """Run table compose CLI.

    Returns:
        int: ``0`` on success; ``1`` on validation failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--columns", required=True, help="JSON array of column headers")
    parser.add_argument("--rows", required=True, help="JSON array of row arrays")
    parser.add_argument("--output", choices=("live", "screenshot", "pdf"), default="live")
    args = parser.parse_args()
    try:
        columns_raw = parse_json_list(args.columns)
        rows_raw = parse_json_list(args.rows)
        columns = [str(col) for col in columns_raw]
        rows = [[str(cell) for cell in row] for row in rows_raw]
    except (ValueError, TypeError) as exc:
        write_error(code="VALIDATION_ERROR", error=str(exc))
        return 1
    html_fragment = compose_table_html(args.title, columns, rows)
    fallback = table_fallback_text(args.title, columns, rows)
    payload = build_openui_payload(
        html_fragment=html_fragment,
        fallback_text=fallback,
        title=args.title,
        output=args.output,
    )
    write_ok(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
