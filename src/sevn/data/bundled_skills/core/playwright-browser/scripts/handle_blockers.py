#!/usr/bin/env python3
from __future__ import annotations

"""Bundled ``playwright-browser`` skill — Bundled ``playwright-browser`` skill script..

Module: sevn.data.bundled_skills.core.playwright-browser.scripts.handle_blockers
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
import json

from _page_intel import obstacle_signals, try_click_recaptcha_checkbox, try_dismiss_cookie_banners
from _pw_session import browser_session, wait_for_page_ready


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-cookies", action="store_true")
    ap.add_argument("--skip-recaptcha", action="store_true")
    args = ap.parse_args()

    async with browser_session() as page:
        cookie_log: list[str] = []
        if not args.skip_cookies:
            await wait_for_page_ready(page)
            cookie_log = await try_dismiss_cookie_banners(page)
            await wait_for_page_ready(page, dismiss_cookies=False)
        else:
            await wait_for_page_ready(page, dismiss_cookies=False)

        recaptcha_ok: bool | None = None
        recaptcha_msg = ""
        if not args.skip_recaptcha:
            recaptcha_ok, recaptcha_msg = await try_click_recaptcha_checkbox(page)
            await page.wait_for_timeout(500)

        state = await obstacle_signals(page)
        state["cookie_attempt_log"] = cookie_log
        state["recaptcha_checkbox_attempt"] = (
            None if args.skip_recaptcha else {"ok": recaptcha_ok, "detail": recaptcha_msg}
        )
        from _output import emit_ok

        emit_ok(state)
        return 0


def _entry() -> int:
    from _output import main_guard

    @main_guard
    def _run() -> int:
        return asyncio.run(main())

    return _run()


if __name__ == "__main__":
    raise SystemExit(_entry())
