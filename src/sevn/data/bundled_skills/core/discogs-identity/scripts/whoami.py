#!/usr/bin/env python3
"""Bundled ``discogs-identity`` skill — auth smoke-test via ``Client.identity()``.

Module: sevn.data.bundled_skills.core.discogs-identity.scripts.whoami
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
from _helpers import finish, run_script  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description=__doc__)


def _worker(_args: argparse.Namespace, client: Any) -> tuple[int, dict[str, Any]]:
    user = client.identity()
    username = getattr(user, "username", None)
    if not username:
        raise ValueError("Discogs identity returned no username")
    payload = write_ok({"username": str(username)})
    return 0, payload


def main(argv: list[str] | None = None) -> tuple[int, dict[str, Any]]:
    """Run whoami CLI.

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
