#!/usr/bin/env python3
from __future__ import annotations

"""Bundled ``playwright-browser`` skill — Bundled ``playwright-browser`` skill script..

Module: sevn.data.bundled_skills.core.playwright-browser.scripts.capture
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
from typing import cast

from _pw_session import (
    browser_session,
    content_root_from_env,
    extract_tab_target_id,
    session_id_from_env,
    wait_for_page_ready,
    workspace_root,
)
from sevn.skills.browser_session import try_persist_active_page


async def main() -> int:
    tab_id, cli_args = extract_tab_target_id(sys.argv[1:])
    args = [a for a in cli_args if a not in ("--full-page", "-f")]
    full_page = "--full-page" in sys.argv or "-f" in sys.argv
    if len(args) < 1:
        print(
            "Usage: capture.py <url> [relative/output.png] [--full-page]",
            file=sys.stderr,
        )
        sys.exit(2)
    url = args[0].strip()
    out_arg = args[1].strip() if len(args) > 1 else ""

    ws = workspace_root()
    if not out_arg:
        rel = f"screenshots/pw-{int(time.time() * 1000)}.png"
    else:
        rel = out_arg.lstrip("/")
    from sevn.pdf import resolve_path_under_workspace

    try:
        dest = resolve_path_under_workspace(ws, rel, artifact=True)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)
    rel = dest.relative_to(ws.resolve()).as_posix()
    dest.parent.mkdir(parents=True, exist_ok=True)

    async with browser_session(tab_target_id=tab_id) as page:
        await page.goto(url, wait_until="load", timeout=60_000)
        await wait_for_page_ready(page)
        try:
            await page.bring_to_front()
        except Exception:
            pass
        data = await page.screenshot(full_page=full_page, type="png")
        dest.write_bytes(data)
        await try_persist_active_page(
            page,
            content_root=content_root_from_env(),
            session_id=session_id_from_env(),
        )
    from _output import emit_ok

    emit_ok(
        {"output": f"Screenshot saved: {rel} ({len(data)} bytes). Use send_file with path={rel!r}"}
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
