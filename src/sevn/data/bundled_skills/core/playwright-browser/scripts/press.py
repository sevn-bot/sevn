#!/usr/bin/env python3
from __future__ import annotations

"""Bundled ``playwright-browser`` skill — Bundled ``playwright-browser`` skill script..

Module: sevn.data.bundled_skills.core.playwright-browser.scripts.press
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

from _pw_session import browser_session


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("keys", nargs="+", help='Key names e.g. Enter Control+c Tab "ArrowDown"')
    ap.add_argument("--selector", "-s", default="", help="Focus this element before pressing")
    args = ap.parse_args()

    async with browser_session() as page:
        if args.selector.strip():
            await page.focus(args.selector, timeout=30_000)
        for k in args.keys:
            await page.keyboard.press(k)
        from _output import emit_ok

        emit_ok({"output": f"OK pressed keys={args.keys!r}"})
        return 0


def _entry() -> int:
    from _output import main_guard

    @main_guard
    def _run() -> int:
        return asyncio.run(main())

    return _run()


if __name__ == "__main__":
    raise SystemExit(_entry())
