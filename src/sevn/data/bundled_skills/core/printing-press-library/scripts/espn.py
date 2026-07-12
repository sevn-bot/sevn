"""sevn wrapper for the Printing Press ESPN CLI (``espn-pp-cli``).

Module: sevn.data.bundled_skills.core.printing-press-library.scripts.espn
Depends: argparse, sys, _pp_cli, sevn.lcm.script_cli

Exports:
    main — CLI entry; runs ``espn-pp-cli [argv] --agent``; JSON envelope on stdout.

Examples:
    >>> from sevn.data.bundled_skills.core.printing_press_library.scripts.espn import main
    >>> callable(main)
    True
"""

from __future__ import annotations

import argparse
import sys

from _pp_cli import run_pp_cli
from sevn.lcm.script_cli import write_error, write_ok

_SLUG = "espn"


def main(argv: list[str] | None = None) -> int:
    """Run ``espn-pp-cli`` and emit a JSON skill envelope on stdout.

    Accepts a ``--query`` shorthand for a natural-language one-liner, or raw
    ``-- <subcommand> [args]`` passthrough when more control is needed.

    Args:
        argv (list[str] | None): Override ``sys.argv[1:]`` in tests. Defaults to
            ``None`` (uses ``sys.argv``).

    Returns:
        int: ``0`` on success, ``1`` on error.

    Examples:
        >>> main(["--help"]) in (0, 1)
        True
    """
    parser = argparse.ArgumentParser(
        prog="espn",
        description="Live ESPN sports scores, standings, news (espn-pp-cli).",
        add_help=True,
    )
    parser.add_argument(
        "--query",
        default=None,
        help="Natural-language query forwarded as positional arg to espn-pp-cli.",
    )
    parser.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        help="Raw argv forwarded to espn-pp-cli after optional --.",
    )

    parsed, _ = parser.parse_known_args(argv if argv is not None else sys.argv[1:])
    cli_args: list[str] = []
    if parsed.args:
        cli_args = [a for a in parsed.args if a != "--"]
    elif parsed.query:
        cli_args = [parsed.query]

    result = run_pp_cli(_SLUG, cli_args)
    if result.get("ok"):
        write_ok(result["data"])
        return 0
    write_error(code=result.get("code", "CLI_ERROR"), error=result.get("error", "unknown error"))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
