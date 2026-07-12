#!/usr/bin/env python3
from __future__ import annotations

"""Bundled ``playwright-browser`` skill — close the session browser.

Module: sevn.data.bundled_skills.core.playwright-browser.scripts.close_browser
Depends: sevn.skills.browser_session, _pw_session

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

import argparse
import sys
from pathlib import Path

_bootstrap_dir = Path(__file__).resolve().parent / "_lib"
if str(_bootstrap_dir) not in sys.path:
    sys.path.insert(0, str(_bootstrap_dir))
import _bootstrap  # noqa: F401

from _pw_session import content_root_from_env, session_id_from_env
from sevn.skills.browser_session import close_browser_session


def main(argv: list[str] | None = None) -> int:
    """Close the sevn-managed browser for this conversation session.

    When the session uses operator ``SEVN_CDP_URL`` attach-only mode, returns
    ``EXTERNAL_CDP`` unless ``--force`` is passed (dangerous — may kill operator Chrome).

    Args:
        argv (list[str] | None, optional): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        int: ``0`` on success, ``1`` when close is refused or fails.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    from _output import emit_error, emit_ok

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Kill browser even when attached to external/operator CDP (dangerous).",
    )
    args = parser.parse_args(argv)

    result = close_browser_session(
        content_root_from_env(),
        session_id_from_env(),
        force=args.force,
    )
    body = {"code": result.code, "message": result.message}
    if result.ok:
        emit_ok(body)
        return 0
    emit_error(result.code, result.message)
    return 1


def _entry() -> int:
    from _output import main_guard

    @main_guard
    def _run() -> int:
        return main()

    return _run()


if __name__ == "__main__":
    raise SystemExit(_entry())
