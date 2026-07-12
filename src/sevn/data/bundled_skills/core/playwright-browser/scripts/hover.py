#!/usr/bin/env python3
from __future__ import annotations

"""Bundled ``playwright-browser`` skill — Bundled ``playwright-browser`` skill script..

Module: sevn.data.bundled_skills.core.playwright-browser.scripts.hover
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

import asyncio
import sys

from _pw_session import browser_session


async def main() -> int:
    if len(sys.argv) < 2:
        from _output import emit_error

        emit_error("VALIDATION", "Usage: hover.py <css_selector>")
        return 2
    sel = sys.argv[1]
    async with browser_session() as page:
        await page.hover(sel, timeout=30_000)
        from _output import emit_ok

        emit_ok({"output": f"OK hover {sel!r}"})
        return 0


def _entry() -> int:
    from _output import main_guard

    @main_guard
    def _run() -> int:
        return asyncio.run(main())

    return _run()


if __name__ == "__main__":
    raise SystemExit(_entry())
