#!/usr/bin/env python3
from __future__ import annotations

"""Bundled ``playwright-browser`` skill — Bundled ``playwright-browser`` skill script..

Module: sevn.data.bundled_skills.core.playwright-browser.scripts.screenshot
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
import time

from _pw_session import browser_session, extract_tab_target_id, wait_for_page_ready, workspace_root


async def main() -> int:
    ws = workspace_root()
    tab_id, args = extract_tab_target_id(sys.argv[1:])
    out_arg = args[0].strip() if args else ""
    full_page = "--full-page" in sys.argv or "-f" in sys.argv
    if out_arg in ("--full-page", "-f"):
        out_arg = ""
    if not out_arg:
        rel = f"screenshots/pw-{int(time.time() * 1000)}.png"
    else:
        rel = out_arg.lstrip("/")
    from sevn.pdf import resolve_path_under_workspace

    try:
        dest = resolve_path_under_workspace(ws, rel, artifact=True)
    except ValueError as exc:
        from _output import emit_error

        emit_error("VALIDATION", str(exc))
        return 2
    rel = dest.relative_to(ws.resolve()).as_posix()
    dest.parent.mkdir(parents=True, exist_ok=True)

    async with browser_session(tab_target_id=tab_id) as page:
        try:
            await page.bring_to_front()
        except Exception:
            pass
        await wait_for_page_ready(page)
        data = await page.screenshot(full_page=full_page, type="png")
        dest.write_bytes(data)
    from _output import emit_ok

    emit_ok({"path": rel, "bytes": len(data), "message": f"Screenshot saved: {rel}"})
    return 0


def _entry() -> int:
    from _output import main_guard

    @main_guard
    def _run() -> int:
        return asyncio.run(main())

    return _run()


if __name__ == "__main__":
    raise SystemExit(_entry())
