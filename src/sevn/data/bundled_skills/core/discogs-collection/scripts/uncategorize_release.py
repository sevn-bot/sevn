#!/usr/bin/env python3
"""Bundled ``discogs-collection`` skill — move a collection item to Uncategorized.

Module: sevn.data.bundled_skills.core.discogs-collection.scripts.uncategorize_release
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
from _helpers import collection_instance, finish, get_collection_folder, run_write_script  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder-id", required=True, type=int, help="Source collection folder id")
    parser.add_argument("--instance-id", required=True, type=int, help="Collection instance id")
    parser.add_argument("--release-id", type=int, help="Discogs release id (optional)")
    parser.add_argument("--confirm", action="store_true", help="Apply the mutation")
    return parser


def _would_do(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "action": "uncategorize_release",
        "folder_id": args.folder_id,
        "instance_id": args.instance_id,
    }
    if args.release_id is not None:
        payload["release_id"] = args.release_id
    return payload


def _worker(args: argparse.Namespace, client: Any) -> tuple[int, dict[str, Any]]:
    user = client.identity()
    folder = get_collection_folder(user, args.folder_id)
    instance = collection_instance(
        client,
        instance_id=args.instance_id,
        release_id=args.release_id,
    )
    folder.uncategorize_release(instance)
    payload = write_ok({"uncategorized": _would_do(args)})
    return 0, payload


def main(argv: list[str] | None = None) -> tuple[int, dict[str, Any]]:
    """Run uncategorize-release CLI.

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
