#!/usr/bin/env python3
from __future__ import annotations

"""Bundled ``playwright-browser`` skill — return page or element HTML (capped).

Module: sevn.data.bundled_skills.core.playwright-browser.scripts.get_html
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

from _pw_session import add_tab_arg, browser_session, wait_for_page_ready


async def main() -> int:
    p = argparse.ArgumentParser(description="Dump HTML from active page.")
    p.add_argument("--selector", "-s", default="", help="CSS selector for element inner HTML")
    p.add_argument("--max-chars", "-n", type=int, default=200_000, help="Truncate after N chars")
    add_tab_arg(p)
    args = p.parse_args()

    async with browser_session(tab_target_id=args.tab) as page:
        await wait_for_page_ready(page)
        if args.selector.strip():
            loc = page.locator(args.selector).first
            html = await loc.inner_html(timeout=30_000)
        else:
            html = await page.content()
        truncated = len(html) > args.max_chars
        if truncated:
            print(
                f"(truncated from {len(html)} to {args.max_chars} chars)\n",
                file=sys.stderr,
            )
            html = html[: args.max_chars]
    from _output import emit_ok

    emit_ok(
        {
            "html": html,
            "chars": len(html),
            "truncated": truncated,
            "selector": args.selector.strip() or None,
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
