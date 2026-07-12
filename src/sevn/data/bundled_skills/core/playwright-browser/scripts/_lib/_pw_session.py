from __future__ import annotations

"""Shared helper for bundled ``playwright-browser`` scripts (_pw_session).

Module: sevn.data.bundled_skills.core.playwright-browser.scripts._lib._pw_session
Depends: sevn.lcm.script_cli, sevn.skills.browser_session

Exports:
    add_tab_arg — register optional ``--tab`` on an ``ArgumentParser``.
    browser_autoclose_enabled — read ``SEVN_BROWSER_AUTOCLOSE`` (default keep-alive).
    browser_session — async context manager delegating to :func:`browser_page`.
    cdp_port — parse TCP port from a CDP base URL.
    cdp_reachable — probe ``/json/version`` on a CDP endpoint.
    content_root_from_env — resolve ``SEVN_CONTENT_ROOT`` (or workspace fallback).
    default_cdp_url — read ``SEVN_CDP_URL`` with localhost legacy default.
    extract_tab_target_id — remove ``--tab <target_id>`` from a CLI argv list.
    pick_work_page — choose a tab for interaction scripts.
    resolve_chrome_executable — locate system Chrome/Chromium binary.
    session_id_from_env — read ``SEVN_SESSION_ID`` with ``default`` fallback.
    tab_session — async context manager for tab CRUD scripts.
    wait_for_page_ready — post-navigation load + best-effort network idle.
    workspace_root — resolve shadow workspace from ``SEVN_WORKSPACE``.
"""

import argparse
import contextlib
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from sevn.skills.browser_session import (
    TabSessionView,
    browser_autoclose_enabled,
    browser_page as _browser_page,
    cdp_port_from_url,
    cdp_reachable,
    connected_tab_session as _connected_tab_session,
    default_cdp_url as _default_cdp_url,
    pick_work_page,
    resolve_chrome_executable,
    wait_for_page_ready as _core_wait_for_page_ready,
)

_CONTENT_ROOT_ENV = "SEVN_CONTENT_ROOT"
_SESSION_ID_ENV = "SEVN_SESSION_ID"
_WORKSPACE_ENV = "SEVN_WORKSPACE"


def default_cdp_url() -> str:
    """Return ``SEVN_CDP_URL`` when set, otherwise the legacy localhost default.

    Returns:
        str: CDP base URL for attach probes.

    Examples:
        >>> default_cdp_url().startswith("http")
        True
    """
    url = _default_cdp_url()
    return url.rstrip("/") if url else "http://127.0.0.1:9222"


def cdp_port(url: str) -> int:
    """Parse the TCP port embedded in a CDP URL.

    Args:
        url (str): CDP base URL.

    Returns:
        int: Explicit port or default ``9222``.

    Examples:
        >>> cdp_port("http://127.0.0.1:9333")
        9333
    """
    return cdp_port_from_url(url)


def workspace_root() -> Path:
    """Return the materialised shadow workspace path from ``SEVN_WORKSPACE``.

    Returns:
        Path: Absolute shadow workspace directory.

    Raises:
        RuntimeError: When ``SEVN_WORKSPACE`` is unset.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(workspace_root)
        True
    """
    raw = os.environ.get(_WORKSPACE_ENV, "").strip()
    if not raw:
        msg = "SEVN_WORKSPACE is not set (gateway should inject it for skill runs)."
        raise RuntimeError(msg)
    return Path(raw).expanduser().resolve()


def content_root_from_env() -> Path:
    """Resolve workspace content root for browser session state (D1).

    Returns:
        Path: ``SEVN_CONTENT_ROOT`` when injected, else ``SEVN_WORKSPACE`` fallback.

    Raises:
        RuntimeError: When neither env var is set.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(content_root_from_env)
        True
    """
    raw = os.environ.get(_CONTENT_ROOT_ENV, "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return workspace_root()


def session_id_from_env() -> str:
    """Return gateway ``SEVN_SESSION_ID`` or ``default`` when unset.

    Returns:
        str: Session id for profile/registry scoping.

    Examples:
        >>> session_id_from_env()  # doctest: +SKIP
        'default'
    """
    return os.environ.get(_SESSION_ID_ENV, "").strip() or "default"


def extract_tab_target_id(argv: list[str]) -> tuple[str | None, list[str]]:
    """Remove optional ``--tab <target_id>`` from argv (D14).

    Args:
        argv (list[str]): CLI arguments (typically ``sys.argv[1:]``).

    Returns:
        tuple[str | None, list[str]]: Tab target id and cleaned argv.

    Examples:
        >>> extract_tab_target_id(["--tab", "page-1", "https://example.com"])
        ('page-1', ['https://example.com'])
        >>> extract_tab_target_id(["https://example.com"])
        (None, ['https://example.com'])
    """
    cleaned: list[str] = []
    tab_id: str | None = None
    index = 0
    while index < len(argv):
        if argv[index] == "--tab" and index + 1 < len(argv):
            tab_id = argv[index + 1].strip() or None
            index += 2
        else:
            cleaned.append(argv[index])
            index += 1
    return tab_id, cleaned


async def wait_for_page_ready(
    page: Any,
    *,
    network_idle_ms: float = 15_000.0,
    dismiss_cookies: bool = True,
) -> None:
    """Wait for load/network idle, then best-effort cookie/consent acceptance."""
    await _core_wait_for_page_ready(page, network_idle_ms=network_idle_ms)
    if not dismiss_cookies:
        return
    from _page_intel import try_dismiss_cookie_banners

    cookie_log = await try_dismiss_cookie_banners(page)
    if any(entry.startswith("clicked:") for entry in cookie_log):
        with contextlib.suppress(Exception):
            await _core_wait_for_page_ready(page, network_idle_ms=3_000.0)


def add_tab_arg(parser: argparse.ArgumentParser) -> None:
    """Register optional ``--tab`` targeting on an interaction script parser (D14).

    Args:
        parser (argparse.ArgumentParser): Parser to extend.

    Returns:
        None

    Examples:
        >>> p = argparse.ArgumentParser()
        >>> add_tab_arg(p)
        >>> any(action.dest == "tab" for action in p._actions)
        True
    """
    parser.add_argument(
        "--tab",
        default=None,
        help="Target tab id from list_tabs (default: registry active tab).",
    )


@asynccontextmanager
async def tab_session(*, headless_fallback: bool = True) -> AsyncIterator[TabSessionView]:
    """Yield a :class:`TabSessionView` for tab list/open/close/activate scripts (D14).

    Args:
        headless_fallback (bool): Allow Playwright headless fallback when Chrome absent.

    Yields:
        TabSessionView: Session browser surface.

    Returns:
        AsyncIterator[TabSessionView]: Async context manager over the tab view.

    Examples:
        >>> import inspect
        >>> inspect.isasyncgenfunction(tab_session.__wrapped__)
        True
    """
    content_root = content_root_from_env()
    session_id = session_id_from_env()
    async with _connected_tab_session(
        content_root=content_root,
        session_id=session_id,
        cfg=None,
        headless_fallback=headless_fallback,
    ) as view:
        yield view


@asynccontextmanager
async def browser_session(
    *,
    headless_fallback: bool = True,
    tab_target_id: str | None = None,
) -> AsyncIterator[Any]:
    """Yield a Playwright ``Page`` via :func:`sevn.skills.browser_session.browser_page`.

    Reads ``SEVN_CONTENT_ROOT`` (or ``SEVN_WORKSPACE``) and ``SEVN_SESSION_ID`` from
    the subprocess environment. Never calls ``Browser.close()`` on CDP attach — remote
    Chrome must survive for the next skill script in the same conversation turn chain.

    Args:
        headless_fallback (bool): Allow Playwright headless fallback when Chrome absent.
        tab_target_id (str | None): Explicit ``--tab`` target id override (D14).

    Yields:
        Any: Playwright ``Page``.

    Returns:
        AsyncIterator[Any]: Async context manager over the active page.

    Examples:
        >>> import inspect
        >>> inspect.isasyncgenfunction(browser_session.__wrapped__)
        True
    """
    content_root = content_root_from_env()
    session_id = session_id_from_env()
    async with _browser_page(
        content_root=content_root,
        session_id=session_id,
        cfg=None,
        headless_fallback=headless_fallback,
        tab_target_id=tab_target_id,
    ) as page:
        yield page
