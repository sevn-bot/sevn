#!/usr/bin/env python3
"""Bundled ``discogs-collection`` skill — add a release to a collection folder.

Module: sevn.data.bundled_skills.core.discogs-collection.scripts.add_release
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
from _helpers import finish, get_collection_folder, run_write_script  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder-id", required=True, type=int, help="Collection folder id")
    parser.add_argument("--release-id", required=True, type=int, help="Discogs release id")
    parser.add_argument("--confirm", action="store_true", help="Apply the mutation")
    return parser


def _would_do(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "action": "add_release",
        "folder_id": args.folder_id,
        "release_id": args.release_id,
    }


def _worker(args: argparse.Namespace, client: Any) -> tuple[int, dict[str, Any]]:
    user = client.identity()
    folder = get_collection_folder(user, args.folder_id)
    folder.add_release(args.release_id)
    payload = write_ok({"added": _would_do(args)})
    return 0, payload


def main(argv: list[str] | None = None) -> tuple[int, dict[str, Any]]:
    """Run add-release CLI.

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
