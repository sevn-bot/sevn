#!/usr/bin/env python3
"""Bundled ``pdf`` skill — pdfplumber text/table/metadata extraction.

Module: sevn.data.bundled_skills.core.pdf.scripts.pdf_read
Depends: argparse, sevn.lcm.script_cli, sevn.pdf

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse

from sevn.lcm.script_cli import workspace_from_env, write_error, write_ok
from sevn.pdf import read_pdf, resolve_path_under_workspace


def main(argv: list[str] | None = None) -> int:
    """Extract PDF text, tables, and metadata with pdfplumber.

    Args:
        argv (list[str] | None, optional): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        int: ``0`` on success, ``1`` on validation or parse failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True, help="Workspace-relative PDF path.")
    parser.add_argument(
        "--no-tables",
        action="store_true",
        help="Skip table extraction.",
    )
    args = parser.parse_args(argv)

    workspace = workspace_from_env()
    try:
        pdf_path = resolve_path_under_workspace(workspace, args.path)
    except ValueError as exc:
        write_error(code="VALIDATION_ERROR", error=str(exc))
        return 1

    ok, payload = read_pdf(pdf_path, include_tables=not args.no_tables)
    if not ok:
        code = "DEPENDENCY_MISSING" if "not installed" in str(payload) else "PARSE_FAILED"
        write_error(code=code, error=str(payload))
        return 1

    write_ok(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
