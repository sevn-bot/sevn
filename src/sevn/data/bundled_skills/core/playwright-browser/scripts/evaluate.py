#!/usr/bin/env python3
from __future__ import annotations

"""Bundled ``playwright-browser`` skill — evaluate JavaScript in the page context.

Module: sevn.data.bundled_skills.core.playwright-browser.scripts.evaluate
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
from typing import cast

from _pw_session import browser_session, extract_tab_target_id


async def main() -> int:
    tab_id, args = extract_tab_target_id(sys.argv[1:])
    if not args:
        print('Usage: evaluate.py [--tab <target_id>] "<js_expression>"', file=sys.stderr)
        return 2
    expr = " ".join(args).strip()
    if not expr:
        return 2
    wrapped = f"(() => {{ return ({expr}); }})()"

    async with browser_session(tab_target_id=tab_id) as page:
        result = await page.evaluate(wrapped)
    from _output import emit_ok

    if isinstance(result, (dict, list, bool, int, float)) or result is None:
        emit_ok({"result": result})
    else:
        emit_ok({"result": str(result)})
    return 0


def _entry() -> int:
    from _output import main_guard

    @main_guard  # type: ignore[untyped-decorator]
    def _run() -> int:
        return asyncio.run(main())

    return cast("int", _run())


if __name__ == "__main__":
    raise SystemExit(_entry())
