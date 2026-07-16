"""sevn-native ``browser`` tool — drive host Chrome over CDP (native engine).

A single multi-action ``@sevn_tool`` over the :mod:`sevn.browser` engine: tab CRUD,
navigation, extraction, synthetic click/fill/type, screenshots, cookies, and a gated
``eval``. Attaches to the operator's Chrome (or spawns one) via the shared
``sevn.skills.browser_session`` lifecycle; recipe actions (Google/Gmail/Telegram/…)
are layered on in later waves.

Module: sevn.tools.browser
Depends: contextlib, pathlib, sevn.browser, sevn.skills.browser_session, sevn.tools.*

Exports:
    browser_tool — ``@sevn_tool`` multi-action CDP browser automation callable.
    register_browser_tool — register the tool on a ``ToolExecutor`` when gated ok.
    set_eval_allowed — set the process-wide gate for the raw ``eval`` action.

Examples:
    >>> from sevn.tools.browser import register_browser_tool
    >>> from sevn.tools.base import ToolExecutor
    >>> register_browser_tool(ToolExecutor(), cfg=None)
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from sevn.browser import HAS_CDP
from sevn.tools.base import enveloped_failure, enveloped_success, maybe_spill_large_payload
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.decorator import sevn_tool, tool_from_decorated

if TYPE_CHECKING:
    from sevn.browser.element import Dom, ElementHandle
    from sevn.browser.lifecycle import CDPBrowserSession
    from sevn.browser.page import Page
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.tools.base import ToolExecutor

# Process-wide gate for the raw ``eval`` action (D8); set by register_browser_tool.
_EVAL_ALLOWED: bool = False

_EXTRACT_TEXT_MAX: Final[int] = 8_000
_EXTRACT_HTML_MAX: Final[int] = 32_000
_DEFAULT_SCROLL_PIXELS: Final[int] = 400
_DISMISS_HINTS: Final[tuple[str, ...]] = (
    "Accept all cookies",
    "Accept all",
    "Accept cookies",
    "Accept & close",
    "Allow all cookies",
    "Allow all",
    "Allow cookies",
    "I agree",
    "I accept",
    "Agree and continue",
    "Agree",
    "Consent",
)

# CSS selectors for known consent-management platforms (OneTrust, Cookiebot, Funding Choices,
# TrustArc, Osano, …). Tried in order after each navigation; only the first *visible* match
# is clicked so generic page buttons are not mass-clicked.
_DISMISS_SELECTORS: Final[tuple[str, ...]] = (
    "#onetrust-accept-btn-handler",
    "#accept-recommended-btn-handler",
    "button#onetrust-accept-btn-handler",
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "#CybotCookiebotDialogBodyButtonAccept",
    ".fc-cta-consent",
    ".fc-button.fc-cta-consent",
    "[data-testid='cookie-accept']",
    "[data-testid='accept-all']",
    ".cookie-accept",
    ".cookie-consent-accept",
    "#truste-consent-button",
    ".osano-cm-accept-all",
)

_DEFAULT_DISMISS_WAIT_MS: Final[int] = 500


async def _element_is_visible(el: ElementHandle) -> bool:
    """Return whether ``el`` has a non-zero client rect (visible on screen).

    Args:
        el (ElementHandle): Resolved DOM node.

    Returns:
        bool: ``True`` when the element appears visible.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_element_is_visible)
        True
    """
    with contextlib.suppress(Exception):
        return bool(
            await el._call_js(
                "function() { const r = this.getClientRects(); "
                "return r.length > 0 && r[0].width > 0 && r[0].height > 0; }"
            )
        )
    return False


async def _dismiss_page_blockers(
    page: Page,
    dom: Dom,
    *,
    wait_ms: int = _DEFAULT_DISMISS_WAIT_MS,
) -> int:
    """Best-effort dismissal of cookie/consent walls after navigation.

    Waits briefly for late-loading CMPs, then clicks the first *visible* known-consent
    CSS selector or cookie-specific text hint. Stops after one successful click so generic
    page buttons (Close, OK, …) are not mass-clicked.

    Args:
        page (Page): Working-tab page (unused today; reserved for frame-aware handling).
        dom (Dom): Working-tab element finder.
        wait_ms (int): Milliseconds to wait after navigation before probing (default 500).

    Returns:
        int: ``1`` when a blocker was dismissed, ``0`` otherwise.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_dismiss_page_blockers)
        True
    """
    _ = page
    if wait_ms > 0:
        await asyncio.sleep(wait_ms / 1000.0)
    for selector in _DISMISS_SELECTORS:
        with contextlib.suppress(Exception):
            el = await dom.query(selector)
            if el is not None and await _element_is_visible(el):
                await el.click()
                return 1
    for hint in _DISMISS_HINTS:
        with contextlib.suppress(Exception):
            el = await dom.find_by_text(hint)
            if el is not None and await _element_is_visible(el):
                await el.click()
                return 1
    return 0


_BROWSER_PARAMS: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "list_tabs",
                "open_tab",
                "close_tab",
                "activate_tab",
                "goto",
                "back",
                "forward",
                "reload",
                "page_state",
                "extract_text",
                "extract_html",
                "wait_for",
                "click",
                "fill",
                "type",
                "press_key",
                "select_option",
                "scroll",
                "screenshot",
                "dismiss_blockers",
                "get_cookies",
                "set_cookies",
                "login_state",
                "login",
                "resume_login",
                "export_cookies",
                "import_cookies",
                "eval",
                "telegram",
                "google_search",
                "gmail",
                "maps",
                "youtube",
                "social",
                "linkedin",
            ],
            "description": "Which browser action to execute.",
        },
        "op": {
            "type": "string",
            "description": (
                "Recipe sub-op: telegram (login|chats|read|send|reply|search|botfather); "
                "gmail (list|read|search|compose|reply); maps (search|place|directions|reviews) "
                '— e.g. action=maps, op=search, query="coffee near me"; '
                "youtube (search|info|comments|read_replies|comment|reply); "
                "social (read|post|reply|read_replies|search|timeline_collect|home_feed) "
                "with site param (X timeline_collect/home_feed/read return structured posts); "
                "linkedin (staff|users|companies|connections). Required whenever action is "
                "telegram/gmail/maps/youtube/social/linkedin — an empty op fails validation."
            ),
        },
        "company": {
            "type": "string",
            "description": "Company name for linkedin op=staff.",
        },
        "location": {
            "type": "string",
            "description": "Location filter for linkedin op=staff.",
        },
        "search_term": {
            "type": "string",
            "description": "Keyword filter for linkedin op=staff.",
        },
        "max_results": {
            "type": "integer",
            "description": "Cap for linkedin staff/connections scrape.",
        },
        "extra_profile_data": {
            "type": "boolean",
            "description": "Enrich linkedin profiles with full profileView data.",
        },
        "user_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Public profile id slugs for linkedin op=users.",
        },
        "company_names": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Company names for linkedin op=companies.",
        },
        "site": {
            "type": "string",
            "description": (
                "Site key for login_state/login/resume_login (gmail, telegram, …) or "
                "social action (x|facebook|instagram|linkedin|reddit|tiktok)."
            ),
        },
        "mode": {
            "type": "string",
            "description": "google_search mode: results (organic + PAA) or ask (AI Overview / Gemini).",
        },
        "message_id": {
            "type": "string",
            "description": "Gmail message subject/sender hint for read/reply.",
        },
        "to": {"type": "string", "description": "Recipient for gmail compose."},
        "subject": {"type": "string", "description": "Subject line for gmail compose/reply."},
        "body": {"type": "string", "description": "Message body for gmail compose/reply."},
        "place": {"type": "string", "description": "Place name/slug for maps place/reviews."},
        "origin": {"type": "string", "description": "Start location for maps directions."},
        "destination": {
            "type": "string",
            "description": "End location for maps directions.",
        },
        "chat": {
            "type": "string",
            "description": "Chat title or @username for telegram read/send.",
        },
        "query": {
            "type": "string",
            "description": "Search query for google_search, gmail search, or maps search.",
        },
        "tab": {"type": "string", "description": "Target CDP target_id; defaults to active tab."},
        "url": {"type": "string", "description": "URL for goto / open_tab."},
        "target_id": {"type": "string", "description": "Target id for close_tab / activate_tab."},
        "selector": {"type": "string", "description": "CSS selector for element actions."},
        "text": {"type": "string", "description": "Text hint for click / fill / type / wait_for."},
        "value": {"type": "string", "description": "Value for fill / type / select_option."},
        "key": {"type": "string", "description": "Key name for press_key (Enter, Tab, ...)."},
        "max_chars": {"type": "integer", "description": "Cap for extract_text / extract_html."},
        "pixels": {"type": "integer", "description": "Scroll distance; negative scrolls up."},
        "full_page": {"type": "boolean", "description": "Full-page screenshot when true."},
        "auto_dismiss": {
            "type": "boolean",
            "description": (
                "For goto: auto-accept cookie/consent walls after navigation (default true). "
                "Clicks the first visible known-consent control only. Set false to skip."
            ),
        },
        "dismiss_wait_ms": {
            "type": "integer",
            "description": (
                "For goto with auto_dismiss: milliseconds to wait after navigation before "
                "probing consent controls (default 500)."
            ),
        },
        "expression": {"type": "string", "description": "JavaScript for the gated eval action."},
        "cookies": {
            "type": "array",
            "items": {"type": "object"},
            "description": "Cookie objects for set_cookies.",
        },
        "comment_hint": {
            "type": "string",
            "description": "Comment author/text hint for youtube reply/read_replies.",
        },
        "credentials_ref": {
            "type": "string",
            "description": "Secrets-store ref for login (never inline passwords).",
        },
        "cookies_path": {
            "type": "string",
            "description": "Path for export_cookies/import_cookies JSON file.",
        },
    },
    "required": ["action"],
}


def _active_target_id(content_root: Path, session_id: str) -> str | None:
    """Return the registry ``active_target_id`` for the session, if any.

    Args:
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.

    Returns:
        str | None: Active target id or ``None``.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_active_target_id)
        True
    """
    from sevn.skills.browser_session import read_registry

    row = read_registry(content_root, session_id)
    return row.active_target_id if row is not None else None


async def _resolve_target_id(
    session: CDPBrowserSession,
    content_root: Path,
    session_id: str,
    tab: str | None,
) -> str | None:
    """Resolve the working target id: explicit ``tab`` → registry active → last page.

    Args:
        session (CDPBrowserSession): Active engine session.
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.
        tab (str | None): Explicit target id override.

    Returns:
        str | None: Resolved target id or ``None`` when no page tabs exist.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_resolve_target_id)
        True
    """
    if tab and tab.strip():
        return tab.strip()
    active = _active_target_id(content_root, session_id)
    pages = await session.page_targets()
    page_ids = {str(p.get("targetId")) for p in pages}
    if active and active in page_ids:
        return active
    if pages:
        return str(pages[-1].get("targetId"))
    return None


def _browser_tools_cfg(content_root: Path) -> dict[str, Any] | None:
    """Load ``tools.browser`` from workspace ``sevn.json`` when present.

    Args:
        content_root (Path): Workspace content root.

    Returns:
        dict[str, Any] | None: Parsed ``tools.browser`` section or ``None``.

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


async def _resolve_page(
    session: CDPBrowserSession,
    content_root: Path,
    session_id: str,
    tab: str | None,
) -> tuple[Page, Dom, str] | None:
    """Return ``(Page, Dom, target_id)`` for the working tab, or ``None``.

    Args:
        session (CDPBrowserSession): Active engine session.
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.
        tab (str | None): Explicit target id override.

    Returns:
        tuple[Page, Dom, str] | None: Page/Dom bound to the working tab, or ``None``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_resolve_page)
        True
    """
    from sevn.browser.element import Dom
    from sevn.browser.page import Page

    target_id = await _resolve_target_id(session, content_root, session_id, tab)
    if not target_id:
        return None
    cdp_session = await session.session_for(target_id)
    return Page(cdp_session), Dom(cdp_session), target_id


async def _find_element(dom: Dom, selector: str | None, text: str | None) -> ElementHandle | None:
    """Resolve an element by selector (preferred) or visible text.

    Args:
        dom (Dom): Finder bound to the working tab.
        selector (str | None): CSS selector.
        text (str | None): Visible-text hint.

    Returns:
        ElementHandle | None: Resolved handle or ``None``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_find_element)
        True
    """
    sel = (selector or "").strip()
    txt = (text or "").strip()
    if sel:
        return await dom.query(sel)
    if txt:
        return await dom.find_by_text(txt)
    return None


async def _dispatch(
    ctx: ToolContext,
    page: Page,
    dom: Dom,
    target_id: str,
    *,
    action: str,
    params: dict[str, Any],
) -> str:
    """Execute one resolved-page browser action and return a JSON envelope.

    Args:
        ctx (ToolContext): Tool context (session id, workspace path).
        page (Page): Working-tab page.
        dom (Dom): Working-tab finder.
        target_id (str): Working-tab target id.
        action (str): Action name.
        params (dict[str, Any]): Action parameters.

    Returns:
        str: JSON envelope with the action result.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_dispatch)
        True
    """
    content_root = ctx.workspace_path
    session_id = (ctx.session_id or "default").strip() or "default"

    if action in {"goto", "back", "forward", "reload"}:
        if action == "goto":
            url = str(params.get("url") or "").strip()
            if not url:
                return enveloped_failure(
                    "url is required for goto", code=ToolResultCode.VALIDATION_ERROR
                )
            out = await page.goto(url)
            # Auto-accept cookie/consent walls so the agent lands on usable content. Opt out
            # with auto_dismiss=false; tune dismiss_wait_ms when CMPs load slowly.
            if params.get("auto_dismiss", True):
                with contextlib.suppress(Exception):
                    wait_ms = int(params.get("dismiss_wait_ms") or _DEFAULT_DISMISS_WAIT_MS)
                    cleared = await _dismiss_page_blockers(page, dom, wait_ms=max(0, wait_ms))
                    if cleared:
                        out = {**out, "blockers_dismissed": cleared}
        elif action == "back":
            out = {"navigated": await page.back()}
        elif action == "forward":
            out = {"navigated": await page.forward()}
        else:
            await page.reload()
            out = {"reloaded": True}
        from sevn.skills.browser_session import persist_active_target_id

        persist_active_target_id(content_root, session_id, target_id)
        return enveloped_success({**out, "target_id": target_id})

    if action == "page_state":
        return enveloped_success({**await page.page_state(), "target_id": target_id})

    if action == "extract_text":
        cap = int(params.get("max_chars") or _EXTRACT_TEXT_MAX)
        text = await page.extract_text(selector=params.get("selector") or None, max_chars=cap)
        envelope = enveloped_success({"text": text, "char_count": len(text)})
        return maybe_spill_large_payload(content_root, session_id, envelope_str=envelope)

    if action == "extract_html":
        cap = int(params.get("max_chars") or _EXTRACT_HTML_MAX)
        html = await page.extract_html(selector=params.get("selector") or None, max_chars=cap)
        envelope = enveloped_success({"html": html, "char_count": len(html)})
        return maybe_spill_large_payload(content_root, session_id, envelope_str=envelope)

    if action == "wait_for":
        selector = str(params.get("selector") or "").strip()
        if not selector:
            return enveloped_failure(
                "selector is required for wait_for", code=ToolResultCode.VALIDATION_ERROR
            )
        found = await page.wait_for(selector)
        return enveloped_success({"found": found, "selector": selector})

    if action in {"click", "fill", "type", "select_option", "press_key"}:
        element = await _find_element(dom, params.get("selector"), params.get("text"))
        if element is None and action != "press_key":
            hint = params.get("selector") or params.get("text")
            return enveloped_failure(
                f"element not found: {hint} (ELEMENT_NOT_FOUND)",
                code=ToolResultCode.VALIDATION_ERROR,
            )
        if action == "click":
            await element.click()  # type: ignore[union-attr]
            return enveloped_success({"clicked": True})
        if action in {"fill", "type"}:
            value = str(params.get("value") or params.get("text") or "")
            if action == "fill":
                await element.fill(value)  # type: ignore[union-attr]
            else:
                await element.type(value)  # type: ignore[union-attr]
            return enveloped_success({action: True, "value": value})
        if action == "select_option":
            await element.select_option(str(params.get("value") or ""))  # type: ignore[union-attr]
            return enveloped_success({"selected": True, "value": params.get("value")})
        # press_key (element optional — focus the matched node when present)
        key = str(params.get("key") or "Enter")
        if element is not None:
            await element.press_key(key)
            return enveloped_success({"pressed": key})
        return enveloped_failure(
            "press_key needs a selector or text to focus", code=ToolResultCode.VALIDATION_ERROR
        )

    if action == "scroll":
        pixels = int(params.get("pixels") or _DEFAULT_SCROLL_PIXELS)
        await page.evaluate(f"window.scrollBy(0, {pixels})")
        return enveloped_success({"scrolled": True, "pixels": pixels})

    if action == "screenshot":
        shots = content_root / "screenshots"
        dest = shots / "screenshot.png"
        out_path = await page.screenshot(dest, full_page=bool(params.get("full_page")))
        rel = str(Path(out_path).relative_to(content_root))
        return enveloped_success({"path": rel, "absolute_path": out_path})

    if action == "dismiss_blockers":
        dismissed = await _dismiss_page_blockers(page, dom)
        return enveloped_success({"dismissed": dismissed})

    if action == "get_cookies":
        cookies = await page.get_cookies()
        envelope = enveloped_success({"cookies": cookies, "count": len(cookies)})
        return maybe_spill_large_payload(content_root, session_id, envelope_str=envelope)

    if action == "set_cookies":
        cookies = params.get("cookies") or []
        count = await page.set_cookies([c for c in cookies if isinstance(c, dict)])
        return enveloped_success({"set": count})

    if action == "eval":
        expression = str(params.get("expression") or "").strip()
        if not expression:
            return enveloped_failure(
                "expression is required for eval", code=ToolResultCode.VALIDATION_ERROR
            )
        value = await page.evaluate(expression)
        return enveloped_success({"value": value})

    if action == "telegram":
        return await _telegram(page, dom, params)

    if action == "google_search":
        return await _google_search(page, dom, params)

    if action == "gmail":
        return await _gmail(page, dom, params, content_root)

    if action == "maps":
        return await _maps(page, dom, params)

    if action == "youtube":
        return await _youtube(page, dom, params, content_root)

    if action == "social":
        return await _social(page, dom, params, content_root)

    if action == "linkedin":
        return await _linkedin(page, dom, params, content_root, session_id)

    if action == "login_state":
        site = str(params.get("site") or "").strip()
        if not site:
            return enveloped_failure(
                "site is required for login_state", code=ToolResultCode.VALIDATION_ERROR
            )
        from sevn.browser.auth import login_state as auth_login_state

        return enveloped_success(await auth_login_state(page, site))

    if action == "login":
        site = str(params.get("site") or "").strip()
        credentials_ref = str(params.get("credentials_ref") or "").strip()
        if not site or not credentials_ref:
            return enveloped_failure(
                "site and credentials_ref are required for login",
                code=ToolResultCode.VALIDATION_ERROR,
            )
        from sevn.browser.auth import AuthError
        from sevn.browser.auth import login as auth_login

        try:
            out = await auth_login(
                page,
                dom,
                site,
                credentials_ref,
                content_root,
                session_id,
            )
        except AuthError as exc:
            return enveloped_failure(str(exc), code=ToolResultCode.VALIDATION_ERROR)
        return enveloped_success(out)

    if action == "resume_login":
        site = str(params.get("site") or "").strip()
        if not site:
            return enveloped_failure(
                "site is required for resume_login", code=ToolResultCode.VALIDATION_ERROR
            )
        from sevn.browser.auth import resume_login as auth_resume_login

        return enveloped_success(await auth_resume_login(page, site, content_root, session_id))

    if action == "export_cookies":
        from sevn.browser.auth import export_cookies as auth_export_cookies

        raw_path = str(params.get("cookies_path") or "").strip()
        if not raw_path:
            raw_path = str(content_root / "cookies" / "export.json")
        dest = Path(raw_path)
        if not dest.is_absolute():
            dest = content_root / dest
        return enveloped_success(await auth_export_cookies(page, dest))

    if action == "import_cookies":
        from sevn.browser.auth import AuthError
        from sevn.browser.auth import import_cookies as auth_import_cookies

        raw_path = str(params.get("cookies_path") or "").strip()
        if not raw_path:
            return enveloped_failure(
                "cookies_path is required for import_cookies",
                code=ToolResultCode.VALIDATION_ERROR,
            )
        src = Path(raw_path)
        if not src.is_absolute():
            src = content_root / src
        try:
            return enveloped_success(await auth_import_cookies(page, src))
        except AuthError as exc:
            return enveloped_failure(str(exc), code=ToolResultCode.VALIDATION_ERROR)

    return enveloped_failure(f"unknown action: {action!r}", code=ToolResultCode.VALIDATION_ERROR)


async def _telegram(page: Page, dom: Dom, params: dict[str, Any]) -> str:
    """Dispatch a Telegram Web recipe op and return a JSON envelope.

    Args:
        page (Page): Working-tab page.
        dom (Dom): Working-tab finder.
        params (dict[str, Any]): Action parameters (``op``, ``chat``, ``query``, ``value``).

    Returns:
        str: JSON envelope with the recipe result.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_telegram)
        True
    """
    from sevn.browser.recipes.base import RecipeError
    from sevn.browser.recipes.telegram_web import TelegramWeb

    tg = TelegramWeb(page, dom)
    op = str(params.get("op") or "").strip().lower()
    chat = str(params.get("chat") or "").strip()
    value = str(params.get("value") or params.get("text") or "")
    query = str(params.get("query") or "").strip()
    try:
        if op == "login":
            return enveloped_success(await tg.login())
        if op == "chats":
            return enveloped_success(await tg.list_chats())
        if op == "search":
            return enveloped_success(await tg.search(query))
        if op == "read":
            return enveloped_success(await tg.read(chat))
        if op == "send":
            return enveloped_success(await tg.send(chat, value))
        if op == "reply":
            return enveloped_success(await tg.reply(chat, value))
        if op == "botfather":
            return enveloped_success(await tg.botfather_token())
    except RecipeError as exc:
        return enveloped_failure(
            f"telegram {op} failed: {exc}", code=ToolResultCode.VALIDATION_ERROR
        )
    return enveloped_failure(
        f"unknown telegram op: {op!r} (login|chats|read|send|reply|search|botfather)",
        code=ToolResultCode.VALIDATION_ERROR,
    )


async def _google_search(page: Page, dom: Dom, params: dict[str, Any]) -> str:
    """Dispatch a Google Search recipe action and return a JSON envelope.

    Args:
        page (Page): Working-tab page.
        dom (Dom): Working-tab finder.
        params (dict[str, Any]): Action parameters (``query``, ``mode``).

    Returns:
        str: JSON envelope with the recipe result.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_google_search)
        True
    """
    from sevn.browser.recipes.base import RecipeError
    from sevn.browser.recipes.google_search import GoogleSearch

    query = str(params.get("query") or "").strip()
    mode = str(params.get("mode") or "results").strip()
    try:
        out = await GoogleSearch(page, dom).search(query, mode=mode)
    except RecipeError as exc:
        return enveloped_failure(
            f"google_search failed: {exc}", code=ToolResultCode.VALIDATION_ERROR
        )
    return enveloped_success(out)


async def _gmail(page: Page, dom: Dom, params: dict[str, Any], content_root: Path) -> str:
    """Dispatch a Gmail recipe action and return a JSON envelope.

    Args:
        page (Page): Working-tab page.
        dom (Dom): Working-tab finder.
        params (dict[str, Any]): Action parameters.
        content_root (Path): Workspace root (config lookup).

    Returns:
        str: JSON envelope with the recipe result.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_gmail)
        True
    """
    from sevn.browser.recipes.base import RecipeError
    from sevn.browser.recipes.gmail import Gmail

    op = str(params.get("op") or "").strip().lower()
    try:
        out = await Gmail(page, dom, browser_tools=_browser_tools_cfg(content_root)).run(
            op,
            query=str(params.get("query") or ""),
            message_id=str(params.get("message_id") or ""),
            to=str(params.get("to") or ""),
            subject=str(params.get("subject") or ""),
            body=str(params.get("body") or params.get("value") or params.get("text") or ""),
        )
    except RecipeError as exc:
        return enveloped_failure(f"gmail {op} failed: {exc}", code=ToolResultCode.VALIDATION_ERROR)
    return enveloped_success(out)


async def _maps(page: Page, dom: Dom, params: dict[str, Any]) -> str:
    """Dispatch a Google Maps recipe action and return a JSON envelope.

    Args:
        page (Page): Working-tab page.
        dom (Dom): Working-tab finder.
        params (dict[str, Any]): Action parameters.

    Returns:
        str: JSON envelope with the recipe result.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_maps)
        True
    """
    from sevn.browser.recipes.base import RecipeError
    from sevn.browser.recipes.google_maps import GoogleMaps

    op = str(params.get("op") or "").strip().lower()
    try:
        out = await GoogleMaps(page, dom).run(
            op,
            query=str(params.get("query") or ""),
            place=str(params.get("place") or ""),
            origin=str(params.get("origin") or ""),
            destination=str(params.get("destination") or ""),
        )
    except RecipeError as exc:
        label = op or "<empty>"
        return enveloped_failure(
            f"maps op={label!r} failed: {exc}", code=ToolResultCode.VALIDATION_ERROR
        )
    return enveloped_success(out)


async def _youtube(page: Page, dom: Dom, params: dict[str, Any], content_root: Path) -> str:
    """Dispatch a YouTube recipe action and return a JSON envelope.

    Args:
        page (Page): Working-tab page.
        dom (Dom): Working-tab finder.
        params (dict[str, Any]): Action parameters.
        content_root (Path): Workspace root (config lookup).

    Returns:
        str: JSON envelope with the recipe result.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_youtube)
        True
    """
    from sevn.browser.recipes.base import RecipeError
    from sevn.browser.recipes.youtube import YouTube

    op = str(params.get("op") or "").strip().lower()
    try:
        out = await YouTube(page, dom, browser_tools=_browser_tools_cfg(content_root)).run(
            op,
            query=str(params.get("query") or ""),
            url=str(params.get("url") or ""),
            text=str(params.get("body") or params.get("value") or params.get("text") or ""),
            comment_hint=str(params.get("comment_hint") or params.get("message_id") or ""),
        )
    except RecipeError as exc:
        return enveloped_failure(
            f"youtube {op} failed: {exc}", code=ToolResultCode.VALIDATION_ERROR
        )
    return enveloped_success(out)


async def _social(page: Page, dom: Dom, params: dict[str, Any], content_root: Path) -> str:
    """Dispatch a social-site recipe action and return a JSON envelope.

    Args:
        page (Page): Working-tab page.
        dom (Dom): Working-tab finder.
        params (dict[str, Any]): Action parameters.
        content_root (Path): Workspace root (config lookup).

    Returns:
        str: JSON envelope with the recipe result.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_social)
        True
    """
    from sevn.browser.recipes.base import RecipeError
    from sevn.browser.recipes.social import SocialRecipe

    op = str(params.get("op") or "").strip().lower()
    site = str(params.get("site") or "").strip().lower()
    try:
        out = await SocialRecipe(page, dom, browser_tools=_browser_tools_cfg(content_root)).run(
            site,
            op,
            target=str(params.get("url") or params.get("target") or params.get("query") or ""),
            query=str(params.get("query") or ""),
            text=str(params.get("body") or params.get("value") or params.get("text") or ""),
        )
    except RecipeError as exc:
        return enveloped_failure(
            f"social {site} {op} failed: {exc}", code=ToolResultCode.VALIDATION_ERROR
        )
    return enveloped_success(out)


async def _linkedin(
    page: Page,
    dom: Dom,
    params: dict[str, Any],
    content_root: Path,
    session_id: str,
) -> str:
    """Dispatch a LinkedIn Voyager recipe action and return a JSON envelope.

    Args:
        page (Page): Working-tab page.
        dom (Dom): Working-tab element finder.
        params (dict[str, Any]): Action parameters (``op``, ``company``, ``user_ids`` ...).
        content_root (Path): Workspace content root for browser-tools config.
        session_id (str): Gateway session id.

    Returns:
        str: JSON envelope with the recipe result or an error.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_linkedin)
        True
    """
    from sevn.browser.recipes.base import RecipeError
    from sevn.browser.recipes.linkedin import LinkedInRecipe

    op = str(params.get("op") or "staff").strip().lower()
    user_ids = params.get("user_ids")
    company_names = params.get("company_names")
    try:
        recipe = LinkedInRecipe(page, dom, browser_tools=_browser_tools_cfg(content_root))
        out = await recipe.run(
            op,
            company=str(params.get("company") or ""),
            search_term=str(params.get("search_term") or ""),
            location=str(params.get("location") or ""),
            max_results=int(params.get("max_results") or 1000),
            extra_profile_data=bool(params.get("extra_profile_data")),
            user_ids=[str(item) for item in user_ids] if isinstance(user_ids, list) else None,
            company_names=(
                [str(item) for item in company_names] if isinstance(company_names, list) else None
            ),
        )
    except RecipeError as exc:
        message = str(exc)
        code = ToolResultCode.VALIDATION_ERROR
        if "LOGIN_REQUIRED" in message:
            code = ToolResultCode.TOOL_NOT_PROVISIONED
        return enveloped_failure(f"linkedin {op} failed: {message}", code=code)
    envelope = enveloped_success(out)
    return maybe_spill_large_payload(content_root, session_id, envelope_str=envelope)


def _eval_allowed(cfg: WorkspaceConfig | None) -> bool:
    """Return whether the gated ``eval`` action is enabled in config (D8).

    Args:
        cfg (WorkspaceConfig | None): Workspace config.

    Returns:
        bool: ``True`` when ``tools.browser.allow_eval`` is set truthy.

    Examples:
        >>> _eval_allowed(None)
        False
    """
    tools = getattr(cfg, "tools", None)
    if not isinstance(tools, dict):
        return False
    entry = tools.get("browser")
    return bool(isinstance(entry, dict) and entry.get("allow_eval") is True)


def set_eval_allowed(allowed: bool) -> None:
    """Set the process-wide ``eval`` gate (called by :func:`register_browser_tool`).

    Args:
        allowed (bool): Whether the gated ``eval`` action is permitted.

    Returns:
        None

    Examples:
        >>> set_eval_allowed(False)
    """
    global _EVAL_ALLOWED
    _EVAL_ALLOWED = allowed


@sevn_tool(
    name="browser",
    category="web",
    description=(
        "Drive host Chrome over CDP (sevn-native engine). "
        "Tabs, navigate, extract, click/fill/type via synthetic input, screenshot, cookies, "
        "plus recipe actions (Google/Gmail/Maps/YouTube/Telegram/social)."
    ),
    parameters=_BROWSER_PARAMS,
    requires_human=False,
    large_result=True,
    see_also=["browser-harness", "get_page_content", "web_fetch"],
    long_description_file="tools/browser.md",
)
async def browser_tool(
    ctx: ToolContext,
    *,
    action: str,
    tab: str | None = None,
    url: str | None = None,
    target_id: str | None = None,
    selector: str | None = None,
    text: str | None = None,
    value: str | None = None,
    key: str | None = None,
    max_chars: int | None = None,
    pixels: int | None = None,
    full_page: bool = False,
    auto_dismiss: bool = True,
    dismiss_wait_ms: int | None = None,
    expression: str | None = None,
    cookies: list[dict[str, Any]] | None = None,
    op: str | None = None,
    chat: str | None = None,
    query: str | None = None,
    mode: str | None = None,
    message_id: str | None = None,
    to: str | None = None,
    subject: str | None = None,
    body: str | None = None,
    place: str | None = None,
    origin: str | None = None,
    destination: str | None = None,
    comment_hint: str | None = None,
    site: str | None = None,
    company: str | None = None,
    location: str | None = None,
    search_term: str | None = None,
    max_results: int | None = None,
    extra_profile_data: bool = False,
    user_ids: list[str] | None = None,
    company_names: list[str] | None = None,
    credentials_ref: str | None = None,
    cookies_path: str | None = None,
) -> str:
    """Execute a ``browser`` action against host Chrome via the sevn CDP engine.

    Args:
        ctx (ToolContext): Tool execution context (session id, workspace path).
        action (str): Action to perform (list_tabs, goto, click, ...).
        tab (str | None): Target CDP target id; defaults to the active tab.
        url (str | None): URL for goto / open_tab.
        target_id (str | None): Target id for close_tab / activate_tab.
        selector (str | None): CSS selector for element actions.
        text (str | None): Text hint for click / fill / type.
        value (str | None): Value for fill / type / select_option.
        key (str | None): Key name for press_key.
        max_chars (int | None): Cap for extract_text / extract_html.
        pixels (int | None): Scroll distance; negative scrolls up.
        full_page (bool): Full-page screenshot flag.
        auto_dismiss (bool): For goto, auto-accept the first visible cookie/consent control.
        dismiss_wait_ms (int | None): Milliseconds to wait after goto before probing (default 500).
        expression (str | None): JavaScript for the gated eval action.
        cookies (list[dict[str, Any]] | None): Cookie objects for set_cookies.
        op (str | None): Recipe sub-op for telegram/gmail/maps actions.
        chat (str | None): Chat title or @username for telegram read/send.
        query (str | None): Search query for google_search, gmail search, or maps search.
        mode (str | None): ``results`` or ``ask`` for google_search.
        message_id (str | None): Gmail message hint for read/reply.
        to (str | None): Recipient for gmail compose.
        subject (str | None): Subject for gmail compose/reply.
        body (str | None): Body text for gmail compose/reply.
        place (str | None): Place name for maps place/reviews.
        origin (str | None): Start location for maps directions.
        destination (str | None): End location for maps directions.
        comment_hint (str | None): Comment hint for youtube reply/read_replies.
        site (str | None): Site key for login or social recipe actions.
        company (str | None): Company name for linkedin op=staff.
        location (str | None): Location filter for linkedin op=staff.
        search_term (str | None): Keyword filter for linkedin op=staff.
        max_results (int | None): Cap for linkedin staff/connections scrape.
        extra_profile_data (bool): Enrich linkedin profiles with full profileView data.
        user_ids (list[str] | None): Public profile id slugs for linkedin op=users.
        company_names (list[str] | None): Company names for linkedin op=companies.
        credentials_ref (str | None): Secrets ref for login (never inline passwords).
        cookies_path (str | None): Path for export_cookies/import_cookies JSON file.

    Returns:
        str: JSON envelope with the action result or an error.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(browser_tool)
        True
    """
    if not HAS_CDP:
        return enveloped_failure(
            "browser engine missing — run: uv sync --extra browser-cdp (ENGINE_MISSING)",
            code=ToolResultCode.TOOL_NOT_PROVISIONED,
        )

    session_id = (ctx.session_id or "default").strip() or "default"
    content_root: Path = ctx.workspace_path
    params: dict[str, Any] = {
        "url": url,
        "target_id": target_id,
        "selector": selector,
        "text": text,
        "value": value,
        "key": key,
        "max_chars": max_chars,
        "pixels": pixels,
        "full_page": full_page,
        "auto_dismiss": auto_dismiss,
        "dismiss_wait_ms": dismiss_wait_ms,
        "expression": expression,
        "cookies": cookies,
        "op": op,
        "chat": chat,
        "query": query,
        "mode": mode,
        "message_id": message_id,
        "to": to,
        "subject": subject,
        "body": body,
        "place": place,
        "origin": origin,
        "destination": destination,
        "comment_hint": comment_hint,
        "site": site,
        "company": company,
        "location": location,
        "search_term": search_term,
        "max_results": max_results,
        "extra_profile_data": extra_profile_data,
        "user_ids": user_ids,
        "company_names": company_names,
        "credentials_ref": credentials_ref,
        "cookies_path": cookies_path,
    }

    if action == "eval" and not _EVAL_ALLOWED:
        return enveloped_failure(
            "eval action disabled — set tools.browser.allow_eval=true (EVAL_DISABLED)",
            code=ToolResultCode.TOOL_NOT_PROVISIONED,
        )

    from sevn.browser.lifecycle import get_or_create_session

    try:
        session = await get_or_create_session(content_root, session_id)
    except RuntimeError as exc:
        return enveloped_failure(
            f"could not attach/spawn Chrome: {exc} (NO_CDP)",
            code=ToolResultCode.TOOL_NOT_PROVISIONED,
        )

    # Tab-management actions operate on the engine session directly.
    if action == "list_tabs":
        active = _active_target_id(content_root, session_id)
        tabs = await session.list_tabs(active_id=active)
        return enveloped_success({"tabs": tabs, "count": len(tabs)})
    if action == "open_tab":
        row = await session.open_tab(url or "about:blank")
        if full_page is False and (url or "").strip():
            with contextlib.suppress(Exception):
                from sevn.skills.browser_session import persist_active_target_id

                persist_active_target_id(content_root, session_id, str(row["target_id"]))
        return enveloped_success(row)
    if action == "close_tab":
        tid = (target_id or tab or "").strip()
        if not tid:
            return enveloped_failure("target_id is required", code=ToolResultCode.VALIDATION_ERROR)
        return enveloped_success(await session.close_tab(tid))
    if action == "activate_tab":
        tid = (target_id or tab or "").strip()
        if not tid:
            return enveloped_failure("target_id is required", code=ToolResultCode.VALIDATION_ERROR)
        from sevn.skills.browser_session import persist_active_target_id

        out = await session.activate_tab(tid)
        persist_active_target_id(content_root, session_id, tid)
        return enveloped_success(out)

    resolved = await _resolve_page(session, content_root, session_id, tab)
    if resolved is None:
        return enveloped_failure(
            "no open browser tab (TAB_NOT_FOUND)", code=ToolResultCode.VALIDATION_ERROR
        )
    page, dom, working_target = resolved
    try:
        return await _dispatch(ctx, page, dom, working_target, action=action, params=params)
    except Exception as exc:
        return enveloped_failure(f"{action} failed: {exc}", code=ToolResultCode.INTERNAL_ERROR)


def register_browser_tool(executor: ToolExecutor, cfg: WorkspaceConfig | None = None) -> None:
    """Register the ``browser`` tool when the CDP engine is available + enabled.

    Skips registration when ``websockets`` is not installed (ENGINE_MISSING graceful)
    or when ``tools.browser.enabled`` is explicitly ``false``.

    Args:
        executor (ToolExecutor): Active tool executor for the gateway session.
        cfg (WorkspaceConfig | None): Workspace config for the ``enabled`` gate.

    Returns:
        None

    Examples:
        >>> from sevn.tools.base import ToolExecutor
        >>> register_browser_tool(ToolExecutor(), cfg=None)
    """
    if not HAS_CDP:
        return
    tools = getattr(cfg, "tools", None)
    if isinstance(tools, dict):
        entry = tools.get("browser")
        if isinstance(entry, dict) and entry.get("enabled") is False:
            return
    set_eval_allowed(_eval_allowed(cfg))
    executor.register(tool_from_decorated(browser_tool))


__all__ = ["browser_tool", "register_browser_tool", "set_eval_allowed"]
