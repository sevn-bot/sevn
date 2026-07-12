#!/usr/bin/env python3
"""Bundled ``lume`` skill — list VMs via ``lume ls``.

Module: sevn.data.bundled_skills.core.lume.scripts.ls
Depends: argparse, sys, sevn.lcm.script_cli, sevn.skills.errors

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
import sys

from sevn.lcm.script_cli import write_error, write_ok
from sevn.skills.errors import SkillExecutionError

from ._common import cli_output_payload, ensure_lume_ready, run_lume_cli


def main(argv: list[str] | None = None) -> int:
    """Run ``lume ls`` to list local VMs.

    Args:
        argv (list[str] | None, optional): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        int: ``0`` on success; ``1`` on validation or runtime failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="text",
        help="Output format passed to lume ls.",
    )
    args = parser.parse_args(argv)

    try:
        cfg = ensure_lume_ready()
        proc = run_lume_cli(cfg, ["ls", "--format", args.format], timeout=120)
    except SkillExecutionError as exc:
        write_error(code=exc.code, error=str(exc))
        return 1

    write_ok({"format": args.format, **cli_output_payload(proc)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
