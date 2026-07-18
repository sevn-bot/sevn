#!/usr/bin/env python3
"""Bundled ``discogs-collection`` skill — search the authed user's collection.

Module: sevn.data.bundled_skills.core.discogs-collection.scripts.search_collection
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
from _helpers import finish, get_collection_folder, run_script, serialize_object  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder-id", required=True, type=int, help="Collection folder id")
    parser.add_argument("--release-id", type=int, help="Filter by Discogs release id")
    parser.add_argument("--query", help="Free-text filter on release title")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--per-page", type=int, default=50)
    return parser


def _worker(args: argparse.Namespace, client: Any) -> tuple[int, dict[str, Any]]:
    user = client.identity()
    if args.release_id is not None:
        items_ref = user.collection_items(args.release_id)
    else:
        folder = get_collection_folder(user, args.folder_id)
        items_ref = folder.releases
    items_ref.per_page = args.per_page
    page_ref = getattr(items_ref, "page", None)
    if callable(page_ref):
        page_items = page_ref(args.page)
    else:
        page_items = list(items_ref)
    items = [serialize_object(item) for item in page_items]
    if args.query:
        query = args.query.casefold()
        items = [
            item
            for item in items
            if query in str(item.get("title", "")).casefold()
            or query in str((item.get("release") or {}).get("title", "")).casefold()
        ]
    paging = paginate(items_ref)
    paging["page"] = args.page
    paging["per_page"] = args.per_page
    payload = write_ok(
        {"folder_id": args.folder_id, "items": items},
        paging=paging,
    )
    return 0, payload


def main(argv: list[str] | None = None) -> tuple[int, dict[str, Any]]:
    """Run collection search CLI.

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
