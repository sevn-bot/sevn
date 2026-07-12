#!/usr/bin/env python3
from __future__ import annotations

"""Bundled ``playwright-browser`` skill — open a new browser tab.

Module: sevn.data.bundled_skills.core.playwright-browser.scripts.new_tab
Depends: sevn.skills.browser_session, _pw_session

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

import asyncio
import sys
from pathlib import Path

_bootstrap_dir = Path(__file__).resolve().parent / "_lib"
if str(_bootstrap_dir) not in sys.path:
    sys.path.insert(0, str(_bootstrap_dir))
import _bootstrap  # noqa: F401

from _pw_session import content_root_from_env, session_id_from_env, tab_session
from sevn.skills.browser_session import open_tab


async def main() -> int:
    """Open a URL in a new tab and activate it by default.

    Returns:
        int: ``0`` on success, ``2`` on validation error.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(main)
        True
    """
    from _output import emit_error, emit_ok

    if len(sys.argv) < 2:
        emit_error("VALIDATION", "Usage: new_tab.py <url>")
        return 2
    url = sys.argv[1].strip()
    if not url:
        emit_error("VALIDATION", "url is required")
        return 2
    content_root = content_root_from_env()
    session_id = session_id_from_env()
    async with tab_session() as view:
        tab = await open_tab(
            view,
            url,
            activate=True,
            content_root=content_root,
            session_id=session_id,
        )
    emit_ok(tab)
    return 0


def _entry() -> int:
    from _output import main_guard

    @main_guard
    def _run() -> int:
        return asyncio.run(main())

    return _run()


if __name__ == "__main__":
    raise SystemExit(_entry())
