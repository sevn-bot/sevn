#!/usr/bin/env python3
"""Bundled ``openwiki`` skill — read-only wiki presence and metadata check.

Module: sevn.data.bundled_skills.core.openwiki.scripts.status
Depends: argparse, pathlib, sevn.code_understanding.openwiki_runner, sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sevn.code_understanding.openwiki_runner import (
    content_root_from_env,
    openwiki_status,
    resolve_openwiki_root,
)
from sevn.lcm.script_cli import write_ok


def main(argv: list[str] | None = None) -> int:
    """Report whether ``openwiki/`` exists under the resolved repository root.

    Args:
        argv (list[str] | None, optional): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        int: ``0`` on success.

    Examples:
        >>> import io, contextlib, tempfile
        >>> from pathlib import Path as _P
        >>> ws = _P(tempfile.mkdtemp())
        >>> buf = io.StringIO()
        >>> with contextlib.redirect_stdout(buf):
        ...     rc = main(["--root", str(ws)])
        >>> rc
        0
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root; defaults to workspace source_code/ mirror when present.",
    )
    args = parser.parse_args(argv)

    workspace = content_root_from_env()
    root = Path(args.root).resolve() if args.root else resolve_openwiki_root(workspace)
    write_ok(openwiki_status(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
