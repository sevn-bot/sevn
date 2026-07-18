#!/usr/bin/env python3
"""Bundled ``discogs-marketplace`` skill — create a marketplace listing.

Module: sevn.data.bundled_skills.core.discogs-marketplace.scripts.create_listing
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
    parser.add_argument("--condition", required=True, help="Media condition enum name")
    parser.add_argument("--price", required=True, help="Listing price")
    parser.add_argument("--status", default="For Sale", help="Listing status enum name")
    parser.add_argument("--sleeve-condition", help="Sleeve condition enum name")
    parser.add_argument("--comments")
    parser.add_argument("--confirm", action="store_true", help="Apply the mutation")
    return parser


def _would_do(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "action": "create_listing",
        "release_id": args.release_id,
        "condition": args.condition,
        "price": args.price,
        "status": args.status,
    }
    if args.sleeve_condition:
        payload["sleeve_condition"] = args.sleeve_condition
    if args.comments:
        payload["comments"] = args.comments
    return payload


def _worker(args: argparse.Namespace, client: Any) -> tuple[int, dict[str, Any]]:
    inventory = client.identity().inventory
    inventory.add_listing(
        args.release_id,
        args.condition,
        args.price,
        args.status,
        sleeve_condition=args.sleeve_condition,
        comments=args.comments,
    )
    payload = write_ok({"created": _would_do(args)})
    return 0, payload


def main(argv: list[str] | None = None) -> tuple[int, dict[str, Any]]:
    """Run create-listing CLI.

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
