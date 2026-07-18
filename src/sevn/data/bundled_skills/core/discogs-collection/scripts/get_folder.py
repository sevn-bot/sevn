#!/usr/bin/env python3
"""Bundled ``discogs-collection`` skill — list releases in a collection folder.

Module: sevn.data.bundled_skills.core.discogs-collection.scripts.get_folder
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
from _helpers import (  # noqa: E402
    finish,
    get_collection_folder,
    run_script,
    serialize_object,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder-id", required=True, type=int, help="Collection folder id")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--per-page", type=int, default=50)
    return parser


def _worker(args: argparse.Namespace, client: Any) -> tuple[int, dict[str, Any]]:
    user = client.identity()
    folder = get_collection_folder(user, args.folder_id)
    releases = folder.releases
    releases.per_page = args.per_page
    page_ref = getattr(releases, "page", None)
    if callable(page_ref):
        page_items = page_ref(args.page)
    else:
        page_items = list(releases)
    items = [serialize_object(item) for item in page_items]
    paging = paginate(releases)
    paging["page"] = args.page
    paging["per_page"] = args.per_page
    payload = write_ok({"folder_id": args.folder_id, "releases": items}, paging=paging)
    return 0, payload


def main(argv: list[str] | None = None) -> tuple[int, dict[str, Any]]:
    """Run get-folder CLI.

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
