#!/usr/bin/env python3
from __future__ import annotations

"""Bundled ``playwright-browser`` skill — scroll the page window or an element.

Module: sevn.data.bundled_skills.core.playwright-browser.scripts.scroll
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
from typing import cast

from _pw_session import browser_session, extract_tab_target_id
from _timing import human_pause


async def main() -> int:
    tab_id, argv = extract_tab_target_id(sys.argv[1:])
    if "--human" in argv:
        human = True
        argv = [a for a in argv if a != "--human"]
    else:
        human = False
    if len(argv) < 1:
        print(
            "Usage: scroll.py [--tab <id>] [--human] page <pixels_y|bottom> [--x pixels_x]\n"
            "       scroll.py [--tab <id>] [--human] <css_selector> <pixels_y>",
            file=sys.stderr,
        )
        return 2

    x_extra = 0
    if "--x" in argv:
        i = argv.index("--x")
        try:
            x_extra = int(argv[i + 1])
        except (IndexError, ValueError):
            print("Bad --x value", file=sys.stderr)
            return 2
        argv = argv[:i] + argv[i + 2 :]

    async with browser_session(tab_target_id=tab_id) as page:
        if human:
            await human_pause(page)
        if argv[0].lower() == "page":
            if len(argv) < 2:
                return 2
            if argv[1].lower() == "bottom":
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                mode = "page_bottom"
                detail: dict[str, object] = {"mode": mode}
            else:
                dy = int(argv[1])
                dx = x_extra
                await page.evaluate(f"window.scrollBy({dx}, {dy})")
                detail = {"mode": "page", "dy": dy, "dx": dx}
        else:
            if len(argv) < 2:
                return 2
            sel = argv[0]
            dy = int(argv[1])
            await page.locator(sel).first.evaluate(
                f"el => {{ el.scrollTop += {dy}; }}",
            )
            detail = {"mode": "element", "selector": sel, "dy": dy}
        if human:
            await human_pause(page, min_ms=150, max_ms=400)
    from _output import emit_ok

    emit_ok({**detail, "human": human})
    return 0


def _entry() -> int:
    from _output import main_guard

    @main_guard  # type: ignore[untyped-decorator]
    def _run() -> int:
        return asyncio.run(main())

    return cast("int", _run())


if __name__ == "__main__":
    raise SystemExit(_entry())
