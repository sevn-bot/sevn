#!/usr/bin/env python3
"""Thin wrappers for common X facade ops (search / timeline / session)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import x_ops as x_ops_cli  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    """CLI entry — forwards to ``x_ops.py`` with a fixed default op group helper.

    Args:
        argv (list[str] | None): Optional argv override.

    Returns:
        int: Process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "op",
        nargs="?",
        default="home_timeline_collect",
        help="Facade op (default home_timeline_collect)",
    )
    parser.add_argument("--task", default=None)
    parser.add_argument("--medium", default=None)
    parser.add_argument("--site", default="x")
    parser.add_argument("--dry-run", "-n", action="store_true")
    ns, _unknown = parser.parse_known_args(list(sys.argv[1:] if argv is None else argv))
    forwarded: list[str] = [ns.op]
    if ns.task:
        forwarded.extend(["--task", ns.task])
    if ns.medium:
        forwarded.extend(["--medium", ns.medium])
    if ns.site:
        forwarded.extend(["--site", ns.site])
    if ns.dry_run:
        forwarded.append("--dry-run")
    return int(x_ops_cli.main(forwarded))


if __name__ == "__main__":
    raise SystemExit(main())
