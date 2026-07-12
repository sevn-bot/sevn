"""LinkedIn Voyager recipe — staff/company/connection scraping over the CDP engine.

StaffSpy upstream: https://github.com/cullenwatson/StaffSpy (MIT) @ 0a8a8d73.

Module: sevn.browser.recipes.linkedin
Depends: asyncio, pathlib, typing, loguru, sevn.browser.auth, sevn.browser.recipes.base,
    sevn.browser.recipes.linkedin_scraper, sevn.browser.recipes.linkedin_models

Exports:
    LinkedInRecipe — high-level LinkedIn scrape operations for tool + skill scripts.
    linkedin_write_allowed — per-recipe write kill-switch helper.
    dry_run_requested — plan-only mode helper for bundled scripts.
    run_linkedin_op — async entry for bundled ``linkedin-use`` scripts.
    run_linkedin_op_sync — sync wrapper for bundled ``linkedin-use`` scripts.

Examples:
    >>> from sevn.browser.recipes.linkedin import linkedin_write_allowed
    >>> linkedin_write_allowed()
    False
"""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING, Any, Final

from loguru import logger

from sevn.browser.auth import login_state
from sevn.browser.recipes.base import (
    RecipeError,
    human_required,
    require_write_allowed,
    validate_egress,
)
from sevn.browser.recipes.linkedin_models import parse_company_data, staff_rows_to_dicts
from sevn.browser.recipes.linkedin_scraper import (
    LINKEDIN_EGRESS,
    GeoUrnNotFound,
    LinkedInVoyagerScraper,
    RateLimitedError,
    VoyagerClient,
    VoyagerStaleError,
)

if TYPE_CHECKING:
    from pathlib import Path

    from sevn.browser.element import Dom
    from sevn.browser.page import Page

_LINKEDIN_FEED: Final[str] = "https://www.linkedin.com/feed/"
_DRY_RUN_ENV: Final[str] = "SEVN_LINKEDIN_USE_DRY_RUN"


def linkedin_write_allowed(*, browser_tools: dict[str, Any] | None = None) -> bool:
    """Return whether LinkedIn write ops are enabled (``tools.browser.linkedin.allow_write``).

    Args:
        browser_tools (dict[str, Any] | None): Resolved ``tools.browser`` config.

    Returns:
        bool: ``True`` only when ``linkedin.allow_write`` is explicitly true.

    Examples:
        >>> linkedin_write_allowed()
        False
        >>> linkedin_write_allowed(browser_tools={"linkedin": {"allow_write": True}})
        True
    """
    if not browser_tools:
        return False
    section = browser_tools.get("linkedin")
    return bool(isinstance(section, dict) and section.get("allow_write") is True)


def dry_run_requested(*, cli_flag: bool = False) -> bool:
    """Return whether linkedin-use scripts should emit plan-only JSON.

    Args:
        cli_flag (bool): Explicit ``--dry-run`` flag from a script.

    Returns:
        bool: ``True`` when the flag is set or ``SEVN_LINKEDIN_USE_DRY_RUN`` is truthy.

    Examples:
        >>> dry_run_requested(cli_flag=True)
        True
    """
    if cli_flag:
        return True
    return os.environ.get(_DRY_RUN_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


class LinkedInRecipe:
    """LinkedIn Voyager scrape recipe over a logged-in CDP page."""

    def __init__(
        self,
        page: Page,
        dom: Dom,
        *,
        browser_tools: dict[str, Any] | None = None,
    ) -> None:
        """Bind page/dom and optional ``tools.browser`` config.

        Args:
            page (Page): Logged-in LinkedIn CDP page.
            dom (Dom): Element finder for the page.
            browser_tools (dict[str, Any] | None): Resolved ``tools.browser`` config.

        Examples:
            >>> LinkedInRecipe.__name__
            'LinkedInRecipe'
        """
        self._page = page
        self._dom = dom
        self._browser_tools = browser_tools
        self._client = VoyagerClient(page)
        self._scraper = LinkedInVoyagerScraper(self._client)

    async def _ensure_logged_in(self) -> dict[str, Any]:
        """Navigate to LinkedIn feed and verify login state.

        Returns:
            dict[str, Any]: Login-state payload when logged in.

        Raises:
            RecipeError: When human verification is required or the session is logged out.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LinkedInRecipe._ensure_logged_in)
            True
        """
        _ = self._dom
        validate_egress(_LINKEDIN_FEED, allowlist=LINKEDIN_EGRESS)
        await self._page.goto(_LINKEDIN_FEED, wait_until="load")
        state = await login_state(self._page, "linkedin")
        if state.get("state") == "human_required":
            payload = human_required(
                "Complete LinkedIn verification (2FA, QR, or CAPTCHA) in the browser.",
                url=await self._page.url(),
            )
            raise RecipeError(str(payload.get("reason")))
        if not state.get("logged_in"):
            msg = "LinkedIn session is not logged in (LOGIN_REQUIRED)"
            raise RecipeError(msg)
        return state

    async def run(
        self,
        op: str,
        *,
        company: str = "",
        search_term: str = "",
        location: str = "",
        max_results: int = 1000,
        extra_profile_data: bool = False,
        user_ids: list[str] | None = None,
        company_names: list[str] | None = None,
        block: bool = False,
        connect: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Dispatch a LinkedIn recipe operation.

        Args:
            op (str): Operation name (``staff``, ``users``, ``companies``, ``connections``).
            company (str): Company name for ``staff``.
            search_term (str): Keyword filter for ``staff``.
            location (str): Location filter for ``staff``.
            max_results (int): Cap on scraped rows.
            extra_profile_data (bool): Enrich profiles with full profileView data.
            user_ids (list[str] | None): Public id slugs for ``users``.
            company_names (list[str] | None): Company names for ``companies``.
            block (bool): Block matched members (write op).
            connect (bool): Send connection requests (write op).
            dry_run (bool): Reserved plan-only flag (ignored here; handled by callers).

        Returns:
            dict[str, Any]: Operation result payload (``op``, ``count``, ``rows`` ...).

        Raises:
            RecipeError: On unknown op or login failure.
            RateLimitedError: When the session is on 429 cooldown.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LinkedInRecipe.run)
            True
        """
        _ = dry_run
        operation = op.strip().lower()
        if self._client.on_block:
            raise RateLimitedError("LinkedIn session on cooldown after 429 (RATE_LIMITED)")

        await self._ensure_logged_in()

        if operation == "staff":
            if block or connect:
                require_write_allowed("linkedin", browser_tools=self._browser_tools)
            staff = await self._scraper.scrape_staff(
                company_name=company or None,
                search_term=search_term,
                location=location,
                extra_profile_data=extra_profile_data,
                max_results=max_results,
                block=block,
                connect=connect,
            )
            rows = staff_rows_to_dicts(staff)
            logger.info("scrape_staff returned {} rows", len(rows))
            return {"op": "staff", "count": len(rows), "rows": rows}

        if operation == "users":
            ids = [item.strip() for item in (user_ids or []) if item.strip()]
            if not ids:
                raise RecipeError("--user-ids is required for users op")
            if block or connect:
                require_write_allowed("linkedin", browser_tools=self._browser_tools)
            staff = await self._scraper.scrape_users(
                ids,
                extra_profile_data=extra_profile_data,
                block=block,
                connect=connect,
            )
            rows = staff_rows_to_dicts(staff)
            return {"op": "users", "count": len(rows), "rows": rows}

        if operation == "companies":
            names = [item.strip() for item in (company_names or []) if item.strip()]
            if not names:
                raise RecipeError("company_names is required for companies op")
            rows = []
            for name in names:
                response = await self._scraper.fetch_or_search_company(name)
                payload = response.json()
                if payload is None:
                    continue
                rows.append(parse_company_data(payload, search_term=name))
            return {"op": "companies", "count": len(rows), "rows": rows}

        if operation == "connections":
            staff = await self._scraper.scrape_connections(
                max_results=max_results,
                extra_profile_data=extra_profile_data,
            )
            rows = staff_rows_to_dicts(staff)
            return {"op": "connections", "count": len(rows), "rows": rows}

        if operation == "session_status":
            return {
                "op": "session_status",
                "logged_in": True,
                "egress_domains": list(LINKEDIN_EGRESS),
                "url": await self._page.url(),
            }

        raise RecipeError(f"unknown linkedin op {operation!r}")


async def _resolve_work_page(
    session: Any,
    content_root: Path,
    session_id: str,
) -> tuple[Any, Any]:
    """Return ``(Page, Dom)`` for the active tab, opening LinkedIn when needed.

    Args:
        session (Any): Active CDP browser session.
        content_root (Path): Workspace content root (tab registry lookup).
        session_id (str): Gateway session id.

    Returns:
        tuple[Any, Any]: ``(Page, Dom)`` bound to the resolved tab.

    Raises:
        RecipeError: When no browser tab can be resolved or opened.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_resolve_work_page)
        True
    """
    from sevn.browser.element import Dom
    from sevn.browser.page import Page
    from sevn.skills.browser_session import read_registry

    reg = read_registry(content_root, session_id)
    active_id = reg.active_target_id if reg is not None else None
    pages = await session.page_targets()
    page_ids = {str(item.get("targetId")) for item in pages}
    target_id = active_id if active_id and active_id in page_ids else None
    if not target_id and pages:
        target_id = str(pages[-1].get("targetId"))
    if not target_id:
        row = await session.open_tab(_LINKEDIN_FEED)
        target_id = str(row.get("target_id") or "")
    if not target_id:
        msg = "no open browser tab (NO_CDP or TAB_NOT_FOUND)"
        raise RecipeError(msg)
    cdp_session = await session.session_for(target_id)
    return Page(cdp_session), Dom(cdp_session)


def _browser_tools_cfg(content_root: Path) -> dict[str, Any] | None:
    """Load ``tools.browser`` from workspace ``sevn.json`` when present.

    Args:
        content_root (Path): Workspace content root holding ``sevn.json``.

    Returns:
        dict[str, Any] | None: The ``tools.browser`` mapping, or ``None`` when absent.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_browser_tools_cfg)
        True
    """
    import json

    path = content_root / "sevn.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    tools = raw.get("tools")
    if isinstance(tools, dict):
        browser = tools.get("browser")
        if isinstance(browser, dict):
            return browser
    return None


async def run_linkedin_op(
    *,
    content_root: Path,
    session_id: str,
    op: str,
    browser_tools: dict[str, Any] | None = None,
    dry_run: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run a LinkedIn recipe operation using the CDP browser engine.

    Args:
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.
        op (str): Operation name forwarded to :meth:`LinkedInRecipe.run`.
        browser_tools (dict[str, Any] | None): Override ``tools.browser`` config.
        dry_run (bool): Return a plan-only payload without touching the browser.
        kwargs (Any): Operation arguments forwarded to :meth:`LinkedInRecipe.run`.

    Returns:
        dict[str, Any]: Operation result or a dry-run plan payload.

    Raises:
        RecipeError: When the engine is missing or a scraper error escapes.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(run_linkedin_op)
        True
    """
    if dry_run:
        return {
            "mode": "dry_run",
            "op": op,
            "content_root": str(content_root),
            "session_id": session_id,
            **kwargs,
        }

    from sevn.browser import HAS_CDP
    from sevn.browser.lifecycle import get_or_create_session

    if not HAS_CDP:
        msg = "browser engine missing — run: uv sync --extra browser-cdp (ENGINE_MISSING)"
        raise RecipeError(msg)

    session = await get_or_create_session(content_root, session_id)
    page, dom = await _resolve_work_page(session, content_root, session_id)
    tools_cfg = browser_tools if browser_tools is not None else _browser_tools_cfg(content_root)
    recipe = LinkedInRecipe(page, dom, browser_tools=tools_cfg)
    try:
        return await recipe.run(op, dry_run=dry_run, **kwargs)
    except (RateLimitedError, VoyagerStaleError, GeoUrnNotFound) as exc:
        raise RecipeError(str(exc)) from exc


def run_linkedin_op_sync(**kwargs: Any) -> dict[str, Any]:
    """Sync wrapper for bundled skill scripts.

    Args:
        kwargs (Any): Keyword arguments forwarded to :func:`run_linkedin_op`.

    Returns:
        dict[str, Any]: Operation result or dry-run plan payload.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(run_linkedin_op_sync)
        True
    """
    return asyncio.run(run_linkedin_op(**kwargs))


__all__ = [
    "LinkedInRecipe",
    "dry_run_requested",
    "linkedin_write_allowed",
    "run_linkedin_op",
    "run_linkedin_op_sync",
]
