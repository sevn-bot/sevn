#!/usr/bin/env python3
"""Bundled ``pdf`` skill — render markdown or HTML to a workspace PDF.

Module: sevn.data.bundled_skills.core.pdf.scripts.pdf
Depends: argparse, sevn.lcm.script_cli, sevn.pdf

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
from pathlib import Path  # noqa: TC003 — runtime path reads in bundled script

from sevn.lcm.script_cli import workspace_from_env, write_error, write_ok
from sevn.pdf import render_pdf_bytes, resolve_path_under_workspace


def _read_input_file(path: Path) -> str:
    """Read UTF-8 text from ``path``.

    Args:
        path (Path): Existing file path.

    Returns:
        str: File contents.

    Raises:
        ValueError: When the file is missing.

    Examples:
        >>> import tempfile
        >>> p = Path(tempfile.mkdtemp()) / "x.txt"
        >>> _ = p.write_text("hi", encoding="utf-8")
        >>> _read_input_file(p)
        'hi'
    """
    if not path.is_file():
        msg = f"pdf: input file not found: {path}"
        raise ValueError(msg)
    return path.read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Render markdown or HTML to a PDF under the workspace.

    Args:
        argv (list[str] | None, optional): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        int: ``0`` on success, ``1`` on validation or render failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="Workspace-relative output PDF path.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--html", help="Inline HTML fragment or document body.")
    group.add_argument("--html-file", help="Path to HTML input file under workspace.")
    group.add_argument("--markdown", help="Inline markdown/plain text body.")
    group.add_argument("--markdown-file", help="Path to markdown input file under workspace.")
    args = parser.parse_args(argv)

    workspace = workspace_from_env()
    try:
        out_path = resolve_path_under_workspace(workspace, args.out, artifact=True)
    except ValueError as exc:
        write_error(code="VALIDATION_ERROR", error=str(exc))
        return 1

    html: str | None = None
    markdown: str | None = None
    try:
        if args.html is not None:
            html = args.html
        elif args.html_file is not None:
            html = _read_input_file(resolve_path_under_workspace(workspace, args.html_file))
        elif args.markdown is not None:
            markdown = args.markdown
        elif args.markdown_file is not None:
            markdown = _read_input_file(
                resolve_path_under_workspace(workspace, args.markdown_file),
            )
    except ValueError as exc:
        write_error(code="VALIDATION_ERROR", error=str(exc))
        return 1

    ok, result = render_pdf_bytes(html=html, markdown=markdown)
    if not ok or not isinstance(result, bytes):
        write_error(code="RENDER_FAILED", error=str(result))
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(result)
    write_ok(
        {
            "output_path": str(out_path.relative_to(workspace)),
            "bytes": len(result),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
