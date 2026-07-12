#!/usr/bin/env python3
from __future__ import annotations

"""Bundled ``playwright-browser`` skill — heuristic cookie/consent banner dismissal.

Module: sevn.data.bundled_skills.core.playwright-browser.scripts.dismiss_cookies
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

import argparse
import asyncio
from typing import cast

from _page_intel import try_dismiss_cookie_banners
from _pw_session import add_tab_arg, browser_session, wait_for_page_ready


async def main() -> int:
    p = argparse.ArgumentParser()
    add_tab_arg(p)
    args = p.parse_args()

    async with browser_session(tab_target_id=args.tab) as page:
        await wait_for_page_ready(page, dismiss_cookies=False)
        steps = await try_dismiss_cookie_banners(page)
    from _output import emit_ok

    emit_ok({"steps": steps, "dismissed": any(s.startswith("clicked:") for s in steps)})
    return 0


def _entry() -> int:
    from _output import main_guard

    @main_guard  # type: ignore[untyped-decorator]
    def _run() -> int:
        return asyncio.run(main())

    return cast("int", _run())


if __name__ == "__main__":
    raise SystemExit(_entry())
