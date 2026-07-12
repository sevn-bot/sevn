#!/usr/bin/env python3
from __future__ import annotations

"""Bundled ``playwright-browser`` skill — session browser status.

Module: sevn.data.bundled_skills.core.playwright-browser.scripts.session_status
Depends: sevn.skills.browser_session, _pw_session

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

from _pw_session import cdp_reachable, content_root_from_env, pick_work_page, session_id_from_env
from sevn.skills.browser_session import session_status_payload


async def _best_effort_active_url(cdp_url: str) -> str | None:
    """Return the active tab URL when CDP attach succeeds (best-effort).

    Args:
        cdp_url (str): CDP base URL.

    Returns:
        str | None: Current page URL, or ``None`` when attach fails.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_best_effort_active_url)
        True
    """
    if not cdp_reachable(cdp_url):
        return None
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(cdp_url)
            page = await pick_work_page(browser)
            return page.url
    except Exception:
        return None


async def main() -> int:
    """Emit session-scoped browser profile, CDP, registry, and active URL metadata.

    Returns:
        int: ``0`` on success.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(main)
        True
    """
    from _output import emit_ok

    content_root = content_root_from_env()
    session_id = session_id_from_env()
    payload = session_status_payload(
        content_root=content_root,
        session_id=session_id,
        cfg=None,
        skill_name="playwright-browser",
    )
    cdp_url = str(payload.get("cdp_url", ""))
    payload["url"] = await _best_effort_active_url(cdp_url)
    registry = payload.get("registry")
    if isinstance(registry, dict):
        payload["pid"] = registry.get("pid")
        payload["headless"] = registry.get("headless")
        payload["spawned_by_sevn"] = registry.get("spawned_by_sevn")
    else:
        payload["pid"] = None
        payload["headless"] = payload.get("headless_default")
        payload["spawned_by_sevn"] = None
    emit_ok(payload)
    return 0


def _entry() -> int:
    from _output import main_guard

    @main_guard
    def _run() -> int:
        return asyncio.run(main())

    return _run()


if __name__ == "__main__":
    raise SystemExit(_entry())
