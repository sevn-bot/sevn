#!/usr/bin/env python3
"""Bundled ``lume`` skill — pull a VM image via ``lume pull``.

Module: sevn.data.bundled_skills.core.lume.scripts.pull
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
    """Run ``lume pull`` for the requested image.

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
        "--image",
        required=True,
        help="Image to pull (format: name:tag).",
    )
    parser.add_argument(
        "--vm-name",
        default=None,
        help="Optional VM name (defaults to image name without tag).",
    )
    args = parser.parse_args(argv)

    try:
        cfg = ensure_lume_ready()
        cli_args = ["pull", args.image]
        if args.vm_name:
            cli_args.append(args.vm_name)
        proc = run_lume_cli(cfg, cli_args, timeout=7200)
    except SkillExecutionError as exc:
        write_error(code=exc.code, error=str(exc))
        return 1

    write_ok({"image": args.image, "vm_name": args.vm_name, **cli_output_payload(proc)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
