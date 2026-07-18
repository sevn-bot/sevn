#!/usr/bin/env python3
"""Bundled ``discogs-wantlist`` skill — edit wantlist notes or rating.

Module: sevn.data.bundled_skills.core.discogs-wantlist.scripts.edit_want
Depends: argparse, _discogs_common, _helpers

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from _discogs_common import write_ok  # noqa: E402
from _helpers import finish, run_write_script  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-id", required=True, type=int, help="Discogs release id")
    parser.add_argument("--notes", help="Updated private notes")
    parser.add_argument(
        "--notes-public",
        choices=("true", "false"),
        help="Whether notes are public (true/false)",
    )
    parser.add_argument("--rating", type=int, choices=range(1, 6), help="Rating 1-5")
    parser.add_argument("--confirm", action="store_true", help="Apply the mutation")
    return parser


def _would_do(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "action": "edit_want",
        "release_id": args.release_id,
    }
    if args.notes is not None:
        payload["notes"] = args.notes
    if args.notes_public is not None:
        payload["notes_public"] = args.notes_public == "true"
    if args.rating is not None:
        payload["rating"] = args.rating
    return payload


def _worker(args: argparse.Namespace, client: Any) -> tuple[int, dict[str, Any]]:
    wantlist = client.identity().wantlist
    notes_public = None
    if args.notes_public is not None:
        notes_public = args.notes_public == "true"
    wantlist.add(
        args.release_id,
        notes=args.notes,
        notes_public=notes_public,
        rating=args.rating,
    )
    payload = write_ok({"edited": _would_do(args)})
    return 0, payload


def main(argv: list[str] | None = None) -> tuple[int, dict[str, Any]]:
    """Run edit-want CLI.

    Args:
        argv (list[str] | None, optional): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        tuple[int, dict[str, Any]]: Exit code and parsed envelope dict.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    return finish(*run_write_script(_build_parser(), argv, _worker, would_do=_would_do))


if __name__ == "__main__":
    exit_code, _ = main()
    raise SystemExit(exit_code)
