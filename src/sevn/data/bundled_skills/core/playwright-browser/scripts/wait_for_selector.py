#!/usr/bin/env python3
from __future__ import annotations

"""Bundled ``playwright-browser`` skill — Bundled ``playwright-browser`` skill script..

Module: sevn.data.bundled_skills.core.playwright-browser.scripts.wait_for_selector
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
    ap.add_argument("selector", help="CSS selector")
    ap.add_argument(
        "--state",
        choices=("attached", "detached", "visible", "hidden"),
        default="visible",
    )
    ap.add_argument("--timeout", type=int, default=30_000, help="ms")
    args = ap.parse_args()

    async with browser_session() as page:
        await page.locator(args.selector).first.wait_for(state=args.state, timeout=args.timeout)
        from _output import emit_ok

        emit_ok({"output": f"OK selector={args.selector!r} state={args.state}"})
        return 0


def _entry() -> int:
    from _output import main_guard

    @main_guard
    def _run() -> int:
        return asyncio.run(main())

    return _run()


if __name__ == "__main__":
    raise SystemExit(_entry())
