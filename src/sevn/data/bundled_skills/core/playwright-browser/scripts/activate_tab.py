#!/usr/bin/env python3
from __future__ import annotations

"""Bundled ``playwright-browser`` skill — activate (focus) a browser tab.

Module: sevn.data.bundled_skills.core.playwright-browser.scripts.activate_tab
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
from sevn.skills.browser_session import activate_tab


async def main() -> int:
    """Focus a tab by ``target_id`` and persist it as the registry active tab.

    Returns:
        int: ``0`` on success, ``1`` on tab error, ``2`` on validation error.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(main)
        True
    """
    from _output import emit_error, emit_ok

    if len(sys.argv) < 2:
        emit_error("VALIDATION", "Usage: activate_tab.py <target_id>")
        return 2
    target_id = sys.argv[1].strip()
    if not target_id:
        emit_error("VALIDATION", "target_id is required")
        return 2
    content_root = content_root_from_env()
    session_id = session_id_from_env()
    try:
        async with tab_session() as view:
            tab = await activate_tab(
                view,
                target_id,
                content_root=content_root,
                session_id=session_id,
            )
    except RuntimeError as exc:
        emit_error("TAB_NOT_FOUND", str(exc))
        return 1
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
