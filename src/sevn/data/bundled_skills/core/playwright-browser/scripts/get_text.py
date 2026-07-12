#!/usr/bin/env python3
from __future__ import annotations

"""Bundled ``playwright-browser`` skill — Bundled ``playwright-browser`` skill script..

Module: sevn.data.bundled_skills.core.playwright-browser.scripts.get_text
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
import sys

from _pw_session import add_tab_arg, browser_session


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("selector", help="CSS selector")
    ap.add_argument(
        "--attr", default="", help="If set, return this attribute instead of inner_text"
    )
    add_tab_arg(ap)
    args = ap.parse_args()

    async with browser_session(tab_target_id=args.tab) as page:
        loc = page.locator(args.selector).first
        if args.attr.strip():
            val = await loc.get_attribute(args.attr.strip())
        else:
            val = await loc.inner_text(timeout=30_000)
        sys.stdout.write((val or "") + "\n")


def _entry() -> int:
    from _output import main_guard

    @main_guard
    def _run() -> int:
        return asyncio.run(main())

    return _run()


if __name__ == "__main__":
    raise SystemExit(_entry())
