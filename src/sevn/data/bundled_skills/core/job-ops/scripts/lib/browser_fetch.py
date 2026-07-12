"""Own-CDP page fetch for browser-gated ``job-ops`` boards.

Module: job-ops/scripts/lib/browser_fetch.py

Navigates the sevn CDP browser engine to a URL and returns the rendered HTML so
Cloudflare/anti-bot boards can be scraped from a logged-in/headed operator session.
When a challenge wall is detected the caller returns ``challenge_required``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from .settings import content_root_from_env, session_id_from_env

_MAX_HTML_CHARS = 500_000
_NAV_TIMEOUT = 45.0


async def _fetch_html_async(url: str, *, content_root: Path, session_id: str) -> str:
    """Navigate to ``url`` in the CDP engine and return rendered HTML."""
    from sevn.browser.lifecycle import get_or_create_session
    from sevn.browser.page import Page

    session = await get_or_create_session(content_root, session_id)
    tab = await session.open_tab("about:blank")
    target_id = str(tab["target_id"])
    try:
        cdp_session = await session.session_for(target_id)
        page = Page(cdp_session)
        await page.goto(url, wait_until="load", timeout=_NAV_TIMEOUT)
        return await page.extract_html(max_chars=_MAX_HTML_CHARS)
    finally:
        await session.close_tab(target_id)


def fetch_html(
    url: str,
    *,
    content_root: Path | None = None,
    session_id: str | None = None,
) -> str:
    """Fetch rendered HTML for ``url`` via the own-CDP browser (sync wrapper).

    Args:
        url (str): Destination URL.
        content_root (Path | None): Content root; defaults to env resolution.
        session_id (str | None): Gateway session id; defaults to env resolution.

    Returns:
        str: Rendered page HTML.
    """
    root = content_root if content_root is not None else content_root_from_env()
    sid = session_id if session_id is not None else session_id_from_env()
    return asyncio.run(_fetch_html_async(url, content_root=root, session_id=sid))
