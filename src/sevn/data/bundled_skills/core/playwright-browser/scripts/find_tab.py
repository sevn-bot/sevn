#!/usr/bin/env python3
from __future__ import annotations

"""Bundled ``playwright-browser`` skill — find an open tab by URL or title substring.

Module: sevn.data.bundled_skills.core.playwright-browser.scripts.find_tab
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

import argparse

from _pw_session import content_root_from_env, session_id_from_env, tab_session
from sevn.skills.browser_session import activate_tab, list_tabs, read_registry


async def main() -> int:
    """Find tabs matching URL/title filters; optionally activate a unique match.

    Returns:
        int: ``0`` on success, ``2`` on validation error.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(main)
        True
    """
    p = argparse.ArgumentParser(description="Find open tabs by URL or title substring.")
    p.add_argument("--url", default="", help="Case-insensitive URL substring")
    p.add_argument("--title", default="", help="Case-insensitive title substring")
    p.add_argument(
        "--activate",
        action="store_true",
        help="When exactly one tab matches, focus it and set active_target_id.",
    )
    args = p.parse_args()
    if not args.url.strip() and not args.title.strip():
        from _output import emit_error

        emit_error("VALIDATION", "Provide --url and/or --title substring")
        return 2

    url_needle = args.url.strip().lower()
    title_needle = args.title.strip().lower()
    content_root = content_root_from_env()
    session_id = session_id_from_env()
    row = read_registry(content_root, session_id)
    active_target_id = row.active_target_id if row else None

    async with tab_session() as view:
        payload = await list_tabs(view, active_target_id=active_target_id)
        tabs_raw = payload.get("tabs")
        tabs = tabs_raw if isinstance(tabs_raw, list) else []
        matches: list[dict[str, object]] = []
        for tab in tabs:
            if not isinstance(tab, dict):
                continue
            url = str(tab.get("url") or "").lower()
            title = str(tab.get("title") or "").lower()
            if url_needle and url_needle not in url:
                continue
            if title_needle and title_needle not in title:
                continue
            matches.append(tab)
        activated: dict[str, object] | None = None
        if args.activate and len(matches) == 1:
            target_id = str(matches[0].get("target_id") or "")
            if target_id:
                activated = await activate_tab(
                    view,
                    target_id,
                    content_root=content_root,
                    session_id=session_id,
                )

    from _output import emit_ok

    emit_ok(
        {
            "matches": matches,
            "count": len(matches),
            "activated": activated,
            "hint": (
                "Reuse an existing tab with activate_tab when count=1; "
                "otherwise new_tab.py or goto.py on the active tab."
            ),
        },
    )
    return 0


def _entry() -> int:
    from _output import main_guard

    @main_guard  # type: ignore[untyped-decorator]
    def _run() -> int:
        return asyncio.run(main())

    return cast("int", _run())


if __name__ == "__main__":
    raise SystemExit(_entry())
