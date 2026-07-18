#!/usr/bin/env python3
"""Bundled ``discogs-marketplace`` skill — search the authed user's inventory.

Module: sevn.data.bundled_skills.core.discogs-marketplace.scripts.search_inventory
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

from _discogs_common import paginate, write_ok  # noqa: E402
from _helpers import finish, run_script, serialize_object  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", help="Ignored; kept for uniform CLI testing")
    parser.add_argument("--status", help="Listing status filter")
    parser.add_argument("--min-price", type=float, help="Minimum listing price")
    parser.add_argument("--max-price", type=float, help="Maximum listing price")
    parser.add_argument("--query", help="Free-text filter on release title")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--per-page", type=int, default=50)
    return parser


def _worker(args: argparse.Namespace, client: Any) -> tuple[int, dict[str, Any]]:
    inventory = client.identity().inventory
    inventory.per_page = args.per_page
    filtered = inventory
    if args.status:
        filtered = filtered.filter(status=args.status)
    if args.min_price is not None:
        filtered = filtered.filter(min_price=args.min_price)
    if args.max_price is not None:
        filtered = filtered.filter(max_price=args.max_price)
    page_ref = getattr(filtered, "page", None)
    if callable(page_ref):
        page_items = page_ref(args.page)
    else:
        page_items = list(filtered)
    items = [serialize_object(item) for item in page_items]
    if args.query:
        query = args.query.casefold()
        items = [
            item
            for item in items
            if query in str(item.get("title", "")).casefold()
            or query in str(item.get("name", "")).casefold()
        ]
    paging = paginate(inventory)
    paging["page"] = args.page
    paging["per_page"] = args.per_page
    payload = write_ok({"listings": items}, paging=paging)
    return 0, payload


def main(argv: list[str] | None = None) -> tuple[int, dict[str, Any]]:
    """Run inventory search CLI.

    Args:
        argv (list[str] | None, optional): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        tuple[int, dict[str, Any]]: Exit code and parsed envelope dict.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    return finish(*run_script(_build_parser(), argv, _worker))


if __name__ == "__main__":
    exit_code, _ = main()
    raise SystemExit(exit_code)
