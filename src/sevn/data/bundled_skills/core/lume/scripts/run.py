#!/usr/bin/env python3
"""Bundled ``lume`` skill — start a VM via ``lume run``.

Module: sevn.data.bundled_skills.core.lume.scripts.run
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
    """Run ``lume run`` for the named image or VM.

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
        "--name",
        required=True,
        help="VM or image name to run (format: name or name:tag).",
    )
    parser.add_argument(
        "--no-display",
        action="store_true",
        help="Pass --no-display to lume run (skip VNC client).",
    )
    args = parser.parse_args(argv)

    try:
        cfg = ensure_lume_ready()
        cli_args = ["run", args.name]
        if args.no_display:
            cli_args.append("--no-display")
        proc = run_lume_cli(cfg, cli_args)
    except SkillExecutionError as exc:
        write_error(code=exc.code, error=str(exc))
        return 1

    write_ok({"name": args.name, **cli_output_payload(proc)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
