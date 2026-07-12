#!/usr/bin/env python3
from __future__ import annotations

"""Bundled ``playwright-browser`` skill — restart the session browser.

Module: sevn.data.bundled_skills.core.playwright-browser.scripts.restart_browser
Depends: sevn.skills.browser_session, _pw_session

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

import argparse
import sys
from dataclasses import asdict
from pathlib import Path

_bootstrap_dir = Path(__file__).resolve().parent / "_lib"
if str(_bootstrap_dir) not in sys.path:
    sys.path.insert(0, str(_bootstrap_dir))
import _bootstrap  # noqa: F401

import asyncio

from _pw_session import content_root_from_env, session_id_from_env
from sevn.skills.browser_session import restart_browser_session


async def main(argv: list[str] | None = None) -> int:
    """Close and respawn the session browser; cookies persist in the profile dir.

    Args:
        argv (list[str] | None, optional): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        int: ``0`` on success, ``1`` on failure.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(main)
        True
    """
    from _output import emit_ok

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force-close external/operator CDP before restart (dangerous).",
    )
    args = parser.parse_args(argv)

    row = await restart_browser_session(
        content_root_from_env(),
        session_id_from_env(),
        cfg=None,
        force_close=args.force,
    )
    emit_ok(
        {
            "message": "browser restarted",
            "profile_dir": row.profile_dir,
            "cdp_url": row.cdp_url,
            "cdp_port": row.cdp_port,
            "pid": row.pid,
            "headless": row.headless,
            "spawned_by_sevn": row.spawned_by_sevn,
            "registry": asdict(row),
        },
    )
    return 0


def _entry() -> int:
    from _output import main_guard

    @main_guard
    def _run() -> int:
        return asyncio.run(main())

    return _run()


if __name__ == "__main__":
    raise SystemExit(_entry())
