#!/usr/bin/env python3
from __future__ import annotations

"""Bundled ``playwright-browser`` skill — select an option on a HTML select element.

Module: sevn.data.bundled_skills.core.playwright-browser.scripts.select_option
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
from _timing import add_human_arg


async def main() -> int:
    ap = argparse.ArgumentParser()
    add_tab_arg(ap)
    add_human_arg(ap)
    ap.add_argument("selector", help="CSS selector for <select>")
    ap.add_argument("value", help="Option value, label text, or index")
    ap.add_argument("--by", choices=("value", "label", "index"), default="value")
    args = ap.parse_args()

    async with browser_session(tab_target_id=args.tab) as page:
        await prepare_element(page, args.selector, human=args.human)
        loc = page.locator(args.selector).first
        if args.by == "value":
            await loc.select_option(value=args.value, timeout=30_000)
        elif args.by == "label":
            await loc.select_option(label=args.value, timeout=30_000)
        else:
            await loc.select_option(index=int(args.value), timeout=30_000)
    from _output import emit_ok

    emit_ok(
        {
            "output": f"OK selected {args.by}={args.value!r} on {args.selector!r}",
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
