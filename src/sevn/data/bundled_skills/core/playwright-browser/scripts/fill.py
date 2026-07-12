#!/usr/bin/env python3
from __future__ import annotations

"""Bundled ``playwright-browser`` skill — fill an input or textarea.

Module: sevn.data.bundled_skills.core.playwright-browser.scripts.fill
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

from _interact import human_fill
from _pw_session import add_tab_arg, browser_session
from _timing import add_human_arg


async def main() -> int:
    p = argparse.ArgumentParser(description="Fill an input or textarea.")
    add_tab_arg(p)
    add_human_arg(p)
    p.add_argument("selector", help="CSS selector")
    p.add_argument("text", help="Value to enter")
    p.add_argument(
        "press_enter",
        nargs="?",
        default="no",
        help="yes|no — press Enter after fill",
    )
    args = p.parse_args()
    press_enter = args.press_enter.strip().lower() in ("yes", "true", "1", "y")

    async with browser_session(tab_target_id=args.tab) as page:
        await human_fill(page, args.selector, args.text, human=args.human)
        if press_enter:
            await page.press(args.selector, "Enter")
    from _output import emit_ok

    emit_ok({"output": f"OK filled {args.selector!r}", "human": args.human})
    return 0


def _entry() -> int:
    from _output import main_guard

    @main_guard  # type: ignore[untyped-decorator]
    def _run() -> int:
        return asyncio.run(main())

    return cast("int", _run())


if __name__ == "__main__":
    raise SystemExit(_entry())
