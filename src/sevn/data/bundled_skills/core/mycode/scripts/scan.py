#!/usr/bin/env python3
"""Bundled ``mycode`` skill — deterministic walk + write of MYCODE.md.

Module: sevn.data.bundled_skills.core.mycode.scripts.scan
Depends: argparse, json, pathlib, sys, sevn.code_understanding, sevn.config.defaults

Exports:
    main — CLI entry: scan ``--root``, optional ``--output`` and ``--ignore`` flags.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sevn.code_understanding import generate_mycode_markdown, write_mycode
from sevn.code_understanding.mycode_cache import scan_repo_cached
from sevn.config.defaults import DEFAULT_MYCODE_OUTPUT_RELATIVE


def _progress(message: str) -> None:
    """Write human-readable progress to stderr.

    Args:
        message (str): Status line for operators and skill runners.

    Returns:
        None

    Examples:
        >>> _progress("hello")
        hello
    """
    print(message, file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    """Run a deterministic MYCODE scan and write the markdown digest.

    Args:
        argv (list[str] | None, optional): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        int: ``0`` on success.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path as _P
        >>> root = _P(tempfile.mkdtemp())
        >>> _ = (root / "x.py").write_text("def hi():\\n    return 1\\n")
        >>> out = root / ".sevn" / "MYCODE.md"
        >>> main(["--root", str(root), "--output", str(out)])
        0
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="Repository root to scan.")
    parser.add_argument(
        "--output",
        default=None,
        help=f"Output path; defaults to <root>/{DEFAULT_MYCODE_OUTPUT_RELATIVE}.",
    )
    parser.add_argument(
        "--ignore",
        action="append",
        default=[],
        help="Glob fragments to skip; pass repeatedly.",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    output = (
        Path(args.output).resolve()
        if args.output is not None
        else root / DEFAULT_MYCODE_OUTPUT_RELATIVE
    )

    _progress(f"Scanning {root} …")
    digest = scan_repo_cached(root, args.ignore)
    _progress("Generating MYCODE markdown …")
    body = generate_mycode_markdown(digest, transport=None)
    write_mycode(output, body)
    print(json.dumps({"ok": True, "path": str(output)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
