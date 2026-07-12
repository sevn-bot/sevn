#!/usr/bin/env python3
from __future__ import annotations

"""Bundled ``playwright-browser`` skill — Bundled ``playwright-browser`` skill script..

Module: sevn.data.bundled_skills.core.playwright-browser.scripts.goto
Depends: sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

import sys
from pathlib import Path

_bootstrap_dir = Path(__file__).resolve().parent / "_lib"
if str(_bootstrap_dir) not in sys.path:
    sys.path.insert(0, str(_bootstrap_dir))
import _bootstrap  # noqa: F401

import asyncio
import sys
from typing import cast

from _pw_session import (
    browser_session,
    content_root_from_env,
    extract_tab_target_id,
    session_id_from_env,
    wait_for_page_ready,
)
from _timing import human_pause
from sevn.skills.browser_session import try_persist_active_page


async def main() -> int:
    tab_id, args = extract_tab_target_id(sys.argv[1:])
    human = False
    if "--human" in args:
        human = True
        args = [a for a in args if a != "--human"]
    if len(args) < 1:
        from _output import emit_error

        emit_error("VALIDATION", "Usage: goto.py [--tab <target_id>] <url>")
        return 2
    url = args[0].strip()
    async with browser_session(tab_target_id=tab_id) as page:
        await page.goto(url, wait_until="load", timeout=60_000)
        await wait_for_page_ready(page)
        if human:
            await human_pause(page)
        title = await page.title()
        target_id = await try_persist_active_page(
            page,
            content_root=content_root_from_env(),
            session_id=session_id_from_env(),
        )
        from _output import emit_ok

        emit_ok(
            {
                "message": "navigated",
                "url": url,
                "title": title,
                "target_id": target_id,
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
