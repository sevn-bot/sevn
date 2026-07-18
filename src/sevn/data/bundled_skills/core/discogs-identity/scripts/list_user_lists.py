#!/usr/bin/env python3
"""Bundled ``discogs-identity`` skill — list a user's public lists.

Module: sevn.data.bundled_skills.core.discogs-identity.scripts.list_user_lists
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
from _helpers import finish, paginated_items, run_script, serialize_object  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", required=True, help="Discogs username")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--per-page", type=int, default=50)
    return parser


def _worker(args: argparse.Namespace, client: Any) -> tuple[int, dict[str, Any]]:
    user = client.user(args.username)
    lists = user.lists
    page_items = paginated_items(lists, page=args.page, per_page=args.per_page)
    items = [serialize_object(item) for item in page_items]
    paging = paginate(lists)
    paging["page"] = args.page
    paging["per_page"] = args.per_page
    payload = write_ok({"username": args.username, "lists": items}, paging=paging)
    return 0, payload


def main(argv: list[str] | None = None) -> tuple[int, dict[str, Any]]:
    """Run list-user-lists CLI.

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
