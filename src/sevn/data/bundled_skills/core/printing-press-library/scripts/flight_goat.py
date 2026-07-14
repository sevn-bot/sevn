"""sevn wrapper for the Printing Press Flight Goat CLI (``flight-goat-pp-cli``).

Module: sevn.data.bundled_skills.core.printing-press-library.scripts.flight_goat
Depends: argparse, sys, _pp_cli, sevn.lcm.script_cli

Exports:
    main — CLI entry; runs ``flight-goat-pp-cli [argv] --agent``; JSON envelope on stdout.

Examples:
    >>> from sevn.data.bundled_skills.core.printing_press_library.scripts.flight_goat import main
    >>> callable(main)
    True
"""

from __future__ import annotations

import argparse
import shlex
import sys

from _pp_cli import run_pp_cli
from sevn.lcm.script_cli import write_error, write_ok

_SLUG = "flight_goat"


def main(argv: list[str] | None = None) -> int:
    """Run ``flight-goat-pp-cli`` and emit a JSON skill envelope on stdout.

    Accepts a ``--query`` shorthand or raw ``-- <subcommand> [args]`` passthrough.

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
        prog="flight_goat",
        description="Flight search via Google Flights and Kayak (flight-goat-pp-cli).",
        add_help=True,
    )
    parser.add_argument(
        "--query",
        default=None,
        help=(
            "A flight-goat-pp-cli subcommand line (e.g. 'which \"cheap flights NYC to "
            "LON\"'), tokenised on whitespace with quotes respected. Not free-text — see "
            "references/flight_goat.md."
        ),
    )
    parser.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        help="Raw argv forwarded to flight-goat-pp-cli after optional --.",
    )

    parsed, _ = parser.parse_known_args(argv if argv is not None else sys.argv[1:])
    cli_args: list[str] = []
    if parsed.args:
        cli_args = [a for a in parsed.args if a != "--"]
    elif parsed.query:
        # Tokenise the subcommand line (quotes respected) so multi-word queries reach the
        # CLI as separate argv, not one bogus subcommand token.
        try:
            cli_args = shlex.split(parsed.query)
        except ValueError:
            cli_args = parsed.query.split()

    result = run_pp_cli(_SLUG, cli_args)
    if result.get("ok"):
        write_ok(result["data"])
        return 0
    write_error(code=result.get("code", "CLI_ERROR"), error=result.get("error", "unknown error"))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
