#!/usr/bin/env python3
"""Bundled ``code_graph_rag`` skill — allowlisted ``cgr`` subcommand runner.

Module: sevn.data.bundled_skills.core.code_graph_rag.scripts.cgr_cli
Depends: argparse, asyncio, sevn.code_understanding.cgr_adapter, sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
import asyncio

from sevn.code_understanding.cgr_adapter import CGR_ALLOWED_SUBCOMMANDS, build_cgr_argv
from sevn.code_understanding.cgr_runner import run_cgr_subprocess
from sevn.lcm.script_cli import write_error, write_ok


def main(argv: list[str] | None = None) -> int:
    """Run one allowlisted ``cgr`` subcommand and return capped stdout.

    Args:
        argv (list[str] | None, optional): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        int: ``0`` on success, ``1`` on failure envelope.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "subcommand",
        choices=sorted(CGR_ALLOWED_SUBCOMMANDS),
        help="Allowlisted cgr subcommand.",
    )
    args = parser.parse_args(argv)

    try:
        _ = build_cgr_argv(args.subcommand)
    except ValueError as exc:
        write_error(code="VALIDATION_ERROR", error=str(exc))
        return 1

    try:
        code, stdout, stderr = asyncio.run(run_cgr_subprocess(args.subcommand))
    except FileNotFoundError as exc:
        write_error(code="DEPENDENCY_MISSING", error=str(exc))
        return 1
    if code != 0:
        write_error(
            code="RUN_FAILED",
            error=stderr.decode("utf-8", errors="replace")
            or f"cgr {args.subcommand} exited {code}",
        )
        return 1

    write_ok(
        {
            "subcommand": args.subcommand,
            "stdout": stdout.decode("utf-8", errors="replace")[:8192],
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
