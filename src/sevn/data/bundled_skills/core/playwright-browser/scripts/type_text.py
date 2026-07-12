#!/usr/bin/env python3
from __future__ import annotations

"""Bundled ``playwright-browser`` skill — type text via keyboard after focusing an element.

Module: sevn.data.bundled_skills.core.playwright-browser.scripts.type_text
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

from _interact import prepare_element
from _pw_session import add_tab_arg, browser_session
from _timing import add_human_arg, human_typing_delay_ms


async def main() -> int:
    p = argparse.ArgumentParser(description="Type text into a focused element.")
    add_tab_arg(p)
    add_human_arg(p)
    p.add_argument("selector", help="CSS selector")
    p.add_argument("text", help="Text to type")
    p.add_argument(
        "delay_ms",
        nargs="?",
        type=int,
        default=None,
        help="Fixed per-keystroke delay; omit with --human for random delay",
    )
    args = p.parse_args()
    delay = args.delay_ms
    if delay is None:
        delay = human_typing_delay_ms() if args.human else 0

    async with browser_session(tab_target_id=args.tab) as page:
        loc = await prepare_element(page, args.selector, human=args.human)
        await loc.click(timeout=30_000)
        await page.keyboard.type(args.text, delay=delay)
    from _output import emit_ok

    emit_ok(
        {
            "output": f"OK typed into {args.selector!r}",
            "delay_ms": delay,
            "human": args.human,
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
