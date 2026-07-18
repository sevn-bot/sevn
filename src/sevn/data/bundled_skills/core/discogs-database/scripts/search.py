#!/usr/bin/env python3
"""Bundled ``discogs-database`` skill — search the public Discogs catalog.

Module: sevn.data.bundled_skills.core.discogs-database.scripts.search
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

_FILTER_FIELDS = (
    "type",
    "genre",
    "style",
    "year",
    "country",
    "format",
    "label",
    "artist",
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True, help="Search query string")
    for field in _FILTER_FIELDS:
        parser.add_argument(f"--{field.replace('_', '-')}")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--per-page", type=int, default=50)
    return parser


def _worker(args: argparse.Namespace, client: Any) -> tuple[int, dict[str, Any]]:
    search_kwargs: dict[str, Any] = {
        "page": args.page,
        "per_page": args.per_page,
    }
    for field in _FILTER_FIELDS:
        value = getattr(args, field, None)
        if value:
            search_kwargs[field] = value
    results = client.search(args.query, **search_kwargs)
    results.per_page = args.per_page
    page_ref = getattr(results, "page", None)
    if callable(page_ref):
        page_items = page_ref(args.page)
    else:
        page_items = list(results)
    items = [serialize_object(item) for item in page_items]
    paging = paginate(results)
    paging["page"] = args.page
    paging["per_page"] = args.per_page
    payload = write_ok(
        {"query": args.query, "results": items},
        paging=paging,
    )
    return 0, payload


def main(argv: list[str] | None = None) -> tuple[int, dict[str, Any]]:
    """Run catalog search CLI.

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
