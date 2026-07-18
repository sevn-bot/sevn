#!/usr/bin/env python3
"""Bundled ``discogs-marketplace`` skill — edit a marketplace listing.

Module: sevn.data.bundled_skills.core.discogs-marketplace.scripts.edit_listing
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
from _helpers import finish, run_write_script, serialize_object  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listing-id", required=True, type=int, help="Discogs listing id")
    parser.add_argument("--price", help="New listing price")
    parser.add_argument("--condition", help="Media condition enum name")
    parser.add_argument("--status", help="Listing status enum name")
    parser.add_argument("--sleeve-condition", help="Sleeve condition enum name")
    parser.add_argument("--comments")
    parser.add_argument("--confirm", action="store_true", help="Apply the mutation")
    return parser


def _would_do(args: argparse.Namespace) -> dict[str, Any]:
    changes: dict[str, Any] = {"action": "edit_listing", "listing_id": args.listing_id}
    for field, arg_name in (
        ("price", "price"),
        ("condition", "condition"),
        ("status", "status"),
        ("sleeve_condition", "sleeve_condition"),
        ("comments", "comments"),
    ):
        value = getattr(args, arg_name, None)
        if value is not None:
            changes[field] = value
    return changes


def _worker(args: argparse.Namespace, client: Any) -> tuple[int, dict[str, Any]]:
    listing = client.listing(args.listing_id)
    if args.price is not None:
        listing.price = args.price
    if args.condition is not None:
        listing.condition = args.condition
    if args.status is not None:
        listing.status = args.status
    if args.sleeve_condition is not None:
        listing.sleeve_condition = args.sleeve_condition
    if args.comments is not None:
        listing.comments = args.comments
    listing.save()
    payload = write_ok({"listing": serialize_object(listing), "updated": _would_do(args)})
    return 0, payload


def main(argv: list[str] | None = None) -> tuple[int, dict[str, Any]]:
    """Run edit-listing CLI.

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
