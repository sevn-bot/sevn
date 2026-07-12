#!/usr/bin/env python3
from __future__ import annotations

"""Bundled ``playwright-browser`` skill — list open browser tabs.

Module: sevn.data.bundled_skills.core.playwright-browser.scripts.list_tabs
Depends: sevn.skills.browser_session, _pw_session

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

import asyncio
import sys
from pathlib import Path
from typing import cast

_bootstrap_dir = Path(__file__).resolve().parent / "_lib"
if str(_bootstrap_dir) not in sys.path:
    sys.path.insert(0, str(_bootstrap_dir))
import _bootstrap  # noqa: F401

from _pw_session import content_root_from_env, session_id_from_env, tab_session
from sevn.skills.browser_session import list_tabs, read_registry


async def main() -> int:
    """Emit JSON list of open tabs with target_id, url, title, and active flag.

    Returns:
        int: ``0`` on success.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(main)
        True
    """
    from _output import emit_ok

    content_root = content_root_from_env()
    session_id = session_id_from_env()
    row = read_registry(content_root, session_id)
    active_target_id = row.active_target_id if row else None
    async with tab_session() as view:
        payload = await list_tabs(view, active_target_id=active_target_id)
    emit_ok(payload)
    return 0


def _entry() -> int:
    from _output import main_guard

    @main_guard  # type: ignore[untyped-decorator]
    def _run() -> int:
        return asyncio.run(main())

    return cast("int", _run())


if __name__ == "__main__":
    raise SystemExit(_entry())
