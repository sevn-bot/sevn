#!/usr/bin/env python3
"""Bundled ``roam_code`` skill — allowlisted ``roam`` query runner.

Module: sevn.data.bundled_skills.core.roam_code.scripts.query
Depends: argparse, sevn.code_understanding.roam_runner, sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sevn.code_understanding.roam_runner import run_roam_query
from sevn.lcm.script_cli import workspace_from_env, write_error, write_ok


def main(argv: list[str] | None = None) -> int:
    """Run ``roam understand`` or ``roam retrieve`` and return capped stdout.

    Args:
        argv (list[str] | None, optional): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        int: ``0`` on success, ``1`` on failure envelope.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path as _P
        >>> ws = _P(tempfile.mkdtemp())
        >>> import os
        >>> os.environ["SEVN_WORKSPACE"] = str(ws)
        >>> main(["--query", "where is auth?"])
        1
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        default=None,
        help="Repository root; defaults to SEVN_WORKSPACE.",
    )
    parser.add_argument(
        "--query",
        default=None,
        help="Natural-language query; omit for roam understand briefing.",
    )
    args = parser.parse_args(argv)

    root = Path(args.path).resolve() if args.path else workspace_from_env()
    ok, text = run_roam_query(root, args.query)
    if not ok:
        write_error(code="MCP_UNAVAILABLE", error=text)
        return 1

    write_ok({"text": text, "root": str(root), "query": args.query})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
