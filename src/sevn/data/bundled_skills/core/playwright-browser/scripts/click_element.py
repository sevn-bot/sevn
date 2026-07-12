#!/usr/bin/env python3
from __future__ import annotations

"""Click a DOM element by CSS selector (Playwright ``page.click``).

Module: sevn.data.bundled_skills.core.playwright-browser.scripts.click_element
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

from _interact import human_click
from _pw_session import add_tab_arg, browser_session
from _timing import add_human_arg


async def main() -> int:
    p = argparse.ArgumentParser(description="Click an element by CSS selector.")
    add_tab_arg(p)
    add_human_arg(p)
    p.add_argument("selector", help="CSS selector")
    args = p.parse_args()

    async with browser_session(tab_target_id=args.tab) as page:
        await human_click(page, args.selector, human=args.human)
    from _output import emit_ok

    emit_ok({"output": f"OK clicked selector={args.selector!r}", "human": args.human})
    return 0


def _entry() -> int:
    from _output import main_guard

    @main_guard  # type: ignore[untyped-decorator]
    def _run() -> int:
        return asyncio.run(main())

    return cast("int", _run())


if __name__ == "__main__":
    raise SystemExit(_entry())
