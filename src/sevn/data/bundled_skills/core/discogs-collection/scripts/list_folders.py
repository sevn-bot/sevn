#!/usr/bin/env python3
"""Bundled ``discogs-collection`` skill — list collection folders.

Module: sevn.data.bundled_skills.core.discogs-collection.scripts.list_folders
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
from _helpers import finish, get_collection_folders, run_script, serialize_object  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description=__doc__)


def _worker(_args: argparse.Namespace, client: Any) -> tuple[int, dict[str, Any]]:
    user = client.identity()
    folders = [serialize_object(folder) for folder in get_collection_folders(user)]
    payload = write_ok({"folders": folders})
    return 0, payload


def main(argv: list[str] | None = None) -> tuple[int, dict[str, Any]]:
    """Run list-folders CLI.

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
