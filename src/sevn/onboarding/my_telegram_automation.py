"""my.telegram.org API credential automation for the onboarding wizard.

Uses :class:`~sevn.onboarding.browser_automation.BrowserSession` (native CDP) to sign in
at ``my.telegram.org``, open **API development tools**, read an existing app's
``api_id``/``api_hash`` or create a new app when none exists.

Module: sevn.onboarding.my_telegram_automation
Depends: asyncio, contextlib, dataclasses, re, time, sevn.onboarding.browser_automation,
    sevn.onboarding.telegram_automation

Exports:
    MyTelegramApiExtract — parsed api_id, api_hash, and phone used.
    MyTelegramSkipError — non-fatal skip (rate limit, optional step).
    extract_api_hash_from_text — regex helper for 32-char hex hash.
    extract_api_id_from_text — regex helper for numeric api_id.
    normalize_phone — international phone normalisation.
    run_fetch_my_telegram_api — full my.telegram.org flow (best-effort).

Examples:
    >>> extract_api_id_from_text("App api_id: 12345678")
    '12345678'
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import time
from dataclasses import dataclass

from sevn.onboarding.browser_automation import BrowserSession
from sevn.onboarding.telegram_automation import _human_pause, _press_enter

MY_TELEGRAM_AUTH_URL = "https://my.telegram.org/auth"
MY_TELEGRAM_APPS_URL = "https://my.telegram.org/apps"

_API_ID_RE = re.compile(r"(?:app\s*)?api_id[^\d]{0,20}(\d{5,10})", re.IGNORECASE)
_API_HASH_RE = re.compile(r"\b([a-f0-9]{32})\b", re.IGNORECASE)
_PHONE_RE = re.compile(r"^\+\d{8,15}$")

_PHONE_INPUT_SELECTORS: tuple[str, ...] = (
    "#phone",
    "input[name='phone']",
    "input[type='tel']",
)
_SUBMIT_SELECTORS: tuple[str, ...] = (
    "button[type='submit']",
    "input[type='submit']",
    "button.btn-primary",
)
_APP_TITLE_SELECTORS: tuple[str, ...] = (
    "#app_title",
    "input[name='app_title']",
)
_APP_SHORTNAME_SELECTORS: tuple[str, ...] = (
    "#app_shortname",
    "input[name='app_shortname']",
)

_AUTH_POLL_SECONDS = 15.0
_CODE_WAIT_POLL_SECONDS = 30.0
_AUTH_TIMEOUT_SECONDS = 600.0
_PAGE_SETTLE_SECONDS = 1.5

_RATE_LIMIT_NEEDLES: tuple[str, ...] = (
    "too many tries",
    "try again later",
)

_CURRENT_URL_JS = "(() => location.href)()"

_READ_APPS_JS = (
    "(() => {"
    " let apiId = '';"
    " let apiHash = '';"
    " const idEl = document.querySelector("
    "   '#api_id, input[name=\"api_id\"], .form-horizontal input[readonly]'"
    " );"
    " if (idEl) apiId = String(idEl.value || idEl.textContent || '').trim();"
    " const hashInput = document.querySelector('#api_hash, input[name=\"api_hash\"]');"
    " if (hashInput) apiHash = String(hashInput.value || hashInput.textContent || '').trim();"
    " if (!apiHash) {"
    "   for (const el of document.querySelectorAll("
    "     'span.form-control, span.uneditable-input, .input-xlarge, code, pre'"
    "   )) {"
    "     const t = (el.textContent || '').trim();"
    "     if (/^[a-f0-9]{32}$/i.test(t)) { apiHash = t; break; }"
    "   }"
    " }"
    " if (!apiId) {"
    "   const m = (document.body.innerText || '').match(/api_id[^\\d]{0,20}(\\d{5,10})/i);"
    "   if (m) apiId = m[1];"
    " }"
    " if (!apiHash) {"
    "   const m = (document.body.innerText || '').match(/\\b([a-f0-9]{32})\\b/i);"
    "   if (m) apiHash = m[1];"
    " }"
    " const titleEl = document.querySelector('#app_title, input[name=\"app_title\"]');"
    " const titleEditable = !!(titleEl && !titleEl.readOnly && !titleEl.disabled"
    "   && titleEl.offsetParent !== null);"
    " const hasCreds = !!(apiId && apiHash);"
    " const createForm = !hasCreds && titleEditable;"
    " return JSON.stringify({"
    "   apiId, apiHash, hasCreds, createForm,"
    "   url: location.href,"
    "   needsCode: !!document.querySelector("
    '     \'#phone_code, input[name="phone_code"], input[name="code"]\''
    "   ),"
    "   needsPhone: !!document.querySelector('#phone, input[name=\"phone\"]')"
    " });"
    "})()"
)


CONFIGURE_LATER_HINT = (
    "Optional — set api_id and api_hash later from the Telegram /config menu "
    "or Mission Control once the bot is running."
)


class MyTelegramSkipError(Exception):
    """Non-fatal skip — onboarding continues without my.telegram.org credentials."""

    def __init__(self, reason: str, message: str) -> None:
        """Record why my.telegram.org setup was skipped.

        Args:
            reason (str): Machine-readable skip reason (for example ``rate_limited``).
            message (str): Operator-facing explanation.

        Examples:
            >>> err = MyTelegramSkipError("rate_limited", "too many tries")
            >>> err.reason
            'rate_limited'
        """
        self.reason = reason
        self.message = message
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class MyTelegramApiExtract:
    """my.telegram.org API credentials extracted during onboarding."""

    api_id: str
    api_hash: str
    phone: str | None = None


def normalize_phone(raw: str | None) -> str | None:
    """Return a normalised international phone or ``None`` when empty.

    Args:
        raw (str | None): Operator phone (for example ``+15551234567``).

    Returns:
        str | None: Normalised phone when valid.

    Raises:
        ValueError: When the phone is non-empty but invalid.

    Examples:
        >>> normalize_phone("+15551234567")
        '+15551234567'
    """
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    if not text.startswith("+"):
        text = f"+{text.lstrip('+')}"
    if not _PHONE_RE.fullmatch(text):
        msg = "phone must use international format like +15551234567"
        raise ValueError(msg)
    return text


def extract_api_id_from_text(text: str) -> str | None:
    """Return the first my.telegram.org ``api_id`` in ``text``.

    Args:
        text (str): Visible page text.

    Returns:
        str | None: Numeric api_id when matched.

    Examples:
        >>> extract_api_id_from_text("App api_id: 12345678")
        '12345678'
    """
    match = _API_ID_RE.search(text)
    return match.group(1) if match else None


def extract_api_hash_from_text(text: str) -> str | None:
    """Return the first 32-char hex ``api_hash`` in ``text``.

    Args:
        text (str): Visible page text.

    Returns:
        str | None: api_hash when matched.

    Examples:
        >>> extract_api_hash_from_text("App api_hash: abcdef0123456789abcdef0123456789")
        'abcdef0123456789abcdef0123456789'
    """
    match = _API_HASH_RE.search(text)
    return match.group(1).lower() if match else None


async def _read_apps_page(session: BrowserSession) -> dict[str, object]:
    """Evaluate the apps page DOM for credentials and form state.

    Args:
        session (BrowserSession): Active browser session on ``/apps``.

    Returns:
        dict[str, object]: Parsed page snapshot (best-effort).

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_read_apps_page)
        True
    """
    tab = session._resolve_tab()
    with contextlib.suppress(Exception):
        raw = await tab.evaluate(_READ_APPS_JS, await_promise=False)
        if isinstance(raw, str):
            import json

            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
    text = await session.extract_text(max_chars=12000)
    api_id = extract_api_id_from_text(text)
    api_hash = extract_api_hash_from_text(text)
    return {
        "apiId": api_id or "",
        "apiHash": api_hash or "",
        "hasCreds": bool(api_id and api_hash),
        "createForm": "app_title" in text.lower() or "short name" in text.lower(),
        "url": "",
        "needsCode": False,
        "needsPhone": False,
    }


async def _click_first(session: BrowserSession, selectors: tuple[str, ...]) -> bool:
    """Click the first matching selector on the page.

    Args:
        session (BrowserSession): Active browser session.
        selectors (tuple[str, ...]): CSS selectors to try in order.

    Returns:
        bool: ``True`` when a control was clicked.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_click_first)
        True
    """
    tab = session._resolve_tab()
    for selector in selectors:
        with contextlib.suppress(Exception):
            elem = await tab.select(selector, timeout=2)
            if elem is not None:
                await elem.click()
                return True
    return False


async def _fill_first(session: BrowserSession, selectors: tuple[str, ...], value: str) -> bool:
    """Type ``value`` into the first matching input.

    Args:
        session (BrowserSession): Active browser session.
        selectors (tuple[str, ...]): CSS selectors to try in order.
        value (str): Text to enter.

    Returns:
        bool: ``True`` when an input was filled.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_fill_first)
        True
    """
    tab = session._resolve_tab()
    for selector in selectors:
        with contextlib.suppress(Exception):
            elem = await tab.select(selector, timeout=3)
            if elem is None:
                continue
            await elem.click()
            with contextlib.suppress(Exception):
                await elem.clear_input()
            await elem.send_keys(value)
            return True
    return False


async def _maybe_submit_phone(session: BrowserSession, phone: str | None) -> None:
    """Enter the operator phone on ``/auth`` when provided and submit.

    Args:
        session (BrowserSession): Active browser session on the auth page.
        phone (str | None): International phone number.

    Returns:
        None

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_maybe_submit_phone)
        True
    """
    if not phone:
        return
    auth = await _auth_page_state(session)
    if auth.get("needsCode"):
        return
    filled = await _fill_first(session, _PHONE_INPUT_SELECTORS, phone)
    if not filled:
        return
    await _human_pause()
    clicked = await _click_first(session, _SUBMIT_SELECTORS)
    if not clicked:
        await _press_enter(session)
    await _human_pause()
    session._record_step("mytelegram.phone_sent")


async def _current_url(session: BrowserSession) -> str:
    """Return the active tab URL (best-effort).

    Args:
        session (BrowserSession): Active browser session.

    Returns:
        str: Current page URL or empty string.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_current_url)
        True
    """
    tab = session._resolve_tab()
    with contextlib.suppress(Exception):
        result = await tab.evaluate(_CURRENT_URL_JS, await_promise=False)
        if isinstance(result, str):
            return result
    return ""


async def _auth_page_state(session: BrowserSession) -> dict[str, object]:
    """Read the current auth page for phone/code prompts.

    Args:
        session (BrowserSession): Active browser session.

    Returns:
        dict[str, object]: ``needsPhone``, ``needsCode``, ``onAuth`` flags from the DOM.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_auth_page_state)
        True
    """
    tab = session._resolve_tab()
    js = (
        "(() => {"
        " const body = (document.body.innerText || '').toLowerCase();"
        " const phoneEl = document.querySelector('#phone, input[name=\"phone\"]');"
        " const codeEl = document.querySelector("
        '   \'#phone_code, input[name="phone_code"], input[name="password"], #my_password\''
        " );"
        " const phoneVisible = !!(phoneEl && phoneEl.offsetParent !== null"
        "   && !phoneEl.disabled && phoneEl.type !== 'hidden');"
        " const codeVisible = !!(codeEl && codeEl.offsetParent !== null"
        "   && !codeEl.disabled && codeEl.type !== 'hidden');"
        " const codePrompt = body.includes('sent you a code')"
        "   || body.includes('confirmation code')"
        "   || body.includes('message to your telegram')"
        "   || body.includes('we have sent you');"
        " const needsCode = codeVisible || (codePrompt && !phoneVisible);"
        " const needsPhone = phoneVisible && !needsCode;"
        " return JSON.stringify({"
        "   needsPhone, needsCode, onAuth: location.pathname.includes('auth')"
        " });"
        "})()"
    )
    with contextlib.suppress(Exception):
        raw = await tab.evaluate(js, await_promise=False)
        if isinstance(raw, str):
            import json

            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
    return {"needsPhone": False, "needsCode": False, "onAuth": False}


async def _raise_if_rate_limited(session: BrowserSession) -> None:
    """Raise when my.telegram.org shows the rate-limit message.

    Args:
        session (BrowserSession): Active browser session.

    Returns:
        None

    Raises:
        MyTelegramSkipError: When the page says ``too many tries``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_raise_if_rate_limited)
        True
    """
    text = (await session.extract_text(max_chars=4000)).lower()
    if any(needle in text for needle in _RATE_LIMIT_NEEDLES):
        msg = "my.telegram.org rate-limited (too many tries) — skipping this optional step"
        session._record_step("mytelegram.skipped", state="done")
        raise MyTelegramSkipError("rate_limited", msg)


async def _apps_session_ready(session: BrowserSession) -> bool:
    """Return whether ``/apps`` is reachable with the saved Chrome profile cookie.

    Args:
        session (BrowserSession): Active browser session.

    Returns:
        bool: ``True`` when logged in (existing app or create-app form visible).

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_apps_session_ready)
        True
    """
    url = await _current_url(session)
    if "/apps" not in url:
        return False
    _api_id, _api_hash, has_creds, needs_create = await _parse_apps_credentials(session)
    return has_creds or needs_create


async def _ensure_my_telegram_auth(
    session: BrowserSession,
    phone: str | None,
) -> None:
    """Use saved cookies on ``/apps`` first; only open ``/auth`` when not logged in.

    The onboarding Chrome profile (``~/.sevn/onboarding-chrome-profile``) persists
    my.telegram.org cookies separately from Telegram Web (different site). After one
    successful sign-in here, later runs reuse the session without re-entering phone.

    Args:
        session (BrowserSession): Active browser session.
        phone (str | None): Optional phone to pre-fill on ``/auth`` when needed.

    Returns:
        None

    Raises:
        RuntimeError: When rate-limited.
        TimeoutError: When sign-in does not complete in time.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_ensure_my_telegram_auth)
        True
    """
    session._record_step("mytelegram.open_apps")
    await _open_apps_page(session)
    await _raise_if_rate_limited(session)
    if await _apps_session_ready(session):
        session._record_step("mytelegram.session_reused")
        return
    url = await _current_url(session)
    if "/auth" not in url:
        session._record_step("mytelegram.open_auth")
        await session.open_url(MY_TELEGRAM_AUTH_URL)
        await asyncio.sleep(_PAGE_SETTLE_SECONDS)
        await _raise_if_rate_limited(session)
    auth = await _auth_page_state(session)
    if not auth.get("needsCode"):
        await _maybe_submit_phone(session, phone)
    await _wait_for_my_telegram_auth(session)


async def _wait_for_my_telegram_auth(
    session: BrowserSession,
    *,
    wait_seconds: float = _AUTH_TIMEOUT_SECONDS,
) -> None:
    """Poll until my.telegram.org shows the apps page or API credentials.

    When the operator must enter an SMS/Telegram code, waits **30 seconds** between
    checks and never navigates away from the code-entry page. General auth polling
    uses 15 seconds; total wait up to 10 minutes.

    Args:
        session (BrowserSession): Active browser session.
        wait_seconds (float): Maximum seconds to wait for authentication.

    Returns:
        None

    Raises:
        TimeoutError: When authentication does not complete in time.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_wait_for_my_telegram_auth)
        True
    """
    session._record_step("mytelegram.wait_auth", state="running")
    deadline = time.monotonic() + max(1.0, wait_seconds)
    while time.monotonic() < deadline:
        await _raise_if_rate_limited(session)
        url = await _current_url(session)
        if "/apps" in url:
            page = await _read_apps_page(session)
            if page.get("hasCreds") or page.get("createForm"):
                if session._steps and session._steps[-1]["label"] == "mytelegram.wait_auth":
                    session._steps[-1]["state"] = "done"
                session._record_step("mytelegram.authenticated")
                return

        auth = await _auth_page_state(session)
        waiting_for_code = bool(auth.get("needsCode")) or (
            auth.get("onAuth") and not auth.get("needsPhone")
        )
        if waiting_for_code:
            session._record_step("mytelegram.enter_code", state="running")
            await asyncio.sleep(_CODE_WAIT_POLL_SECONDS)
            continue

        if auth.get("needsPhone"):
            await asyncio.sleep(_AUTH_POLL_SECONDS)
            continue

        await session.open_url(MY_TELEGRAM_APPS_URL)
        await asyncio.sleep(_PAGE_SETTLE_SECONDS)
        page = await _read_apps_page(session)
        if page.get("hasCreds") or page.get("createForm"):
            if session._steps and session._steps[-1]["label"] == "mytelegram.wait_auth":
                session._steps[-1]["state"] = "done"
            session._record_step("mytelegram.authenticated")
            return
        await asyncio.sleep(_AUTH_POLL_SECONDS)
    if session._steps and session._steps[-1]["label"] == "mytelegram.wait_auth":
        session._steps[-1]["state"] = "done"
    msg = (
        "my.telegram.org sign-in timed out — enter your phone and verification code "
        "in Chrome, then retry"
    )
    raise TimeoutError(msg)


async def _parse_apps_credentials(session: BrowserSession) -> tuple[str, str, bool, bool]:
    """Return ``(api_id, api_hash, has_creds, needs_create)`` from ``/apps``.

    Args:
        session (BrowserSession): Active browser session on ``/apps``.

    Returns:
        tuple[str, str, bool, bool]: Parsed id/hash and whether to skip create-app.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_parse_apps_credentials)
        True
    """
    page = await _read_apps_page(session)
    api_id = str(page.get("apiId") or "").strip()
    api_hash = str(page.get("apiHash") or "").strip().lower()
    if not api_id or not api_hash:
        text = await session.extract_text(max_chars=12000)
        api_id = api_id or extract_api_id_from_text(text) or ""
        api_hash = api_hash or extract_api_hash_from_text(text) or ""
    has_creds = bool(api_id and api_hash and api_id.isdigit() and len(api_hash) == 32)
    needs_create = not has_creds and bool(page.get("createForm"))
    return api_id, api_hash, has_creds, needs_create


async def _open_apps_page(session: BrowserSession) -> None:
    """Navigate to my.telegram.org ``/apps`` and let the page settle.

    Args:
        session (BrowserSession): Active browser session.

    Returns:
        None

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_open_apps_page)
        True
    """
    await session.open_url(MY_TELEGRAM_APPS_URL)
    await asyncio.sleep(_PAGE_SETTLE_SECONDS)


async def _create_app_if_needed(session: BrowserSession) -> None:
    """Submit the new-app form only when ``/apps`` has no existing credentials.

    When the operator already has an app on my.telegram.org, this is a no-op and
    existing ``api_id``/``api_hash`` values are left unchanged.

    Args:
        session (BrowserSession): Authenticated browser session on ``/apps``.

    Returns:
        None

    Raises:
        RuntimeError: When the create form cannot be filled or submitted.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_create_app_if_needed)
        True
    """
    await _open_apps_page(session)
    _api_id, _api_hash, has_creds, needs_create = await _parse_apps_credentials(session)
    if has_creds:
        session._record_step("mytelegram.use_existing_app")
        return
    if not needs_create:
        msg = "my.telegram.org apps page has no credentials and no create-app form"
        raise RuntimeError(msg)
    session._record_step("mytelegram.create_app", state="running")
    if not await _fill_first(session, _APP_TITLE_SELECTORS, "sevn bot"):
        msg = "could not find app title field on my.telegram.org/apps"
        raise RuntimeError(msg)
    await _human_pause()
    if not await _fill_first(session, _APP_SHORTNAME_SELECTORS, "sevn_bot"):
        msg = "could not find app short name field on my.telegram.org/apps"
        raise RuntimeError(msg)
    await _human_pause()
    if not await _click_first(session, _SUBMIT_SELECTORS):
        await _press_enter(session)
    await _human_pause()
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        _api_id, _api_hash, has_creds, _needs = await _parse_apps_credentials(session)
        if has_creds:
            if session._steps and session._steps[-1]["label"] == "mytelegram.create_app":
                session._steps[-1]["state"] = "done"
            return
        await asyncio.sleep(1.0)
    if session._steps and session._steps[-1]["label"] == "mytelegram.create_app":
        session._steps[-1]["state"] = "done"
    msg = "submitted new app on my.telegram.org but api_id/api_hash did not appear"
    raise RuntimeError(msg)


async def run_fetch_my_telegram_api(
    session: BrowserSession,
    *,
    phone: str | None = None,
) -> MyTelegramApiExtract:
    """Fetch ``api_id`` and ``api_hash`` from my.telegram.org (create app if needed).

    Uses the same headed Chrome profile as Telegram Web — opens ``/apps`` first so
    an existing my.telegram.org cookie session is reused without re-entering phone/code.
    Only visits ``/auth`` when the session cookie is missing. Reuses an existing app
    when ``api_id``/``api_hash`` are already on the page; creates one only when none
    exists.

    Args:
        session (BrowserSession): Started onboarding browser session.
        phone (str | None): Optional international phone (``+15551234567``).

    Returns:
        MyTelegramApiExtract: Parsed credentials.

    Raises:
        RuntimeError: When credentials cannot be extracted or rate-limited.
        TimeoutError: When sign-in does not complete in time.
        ValueError: When ``phone`` is invalid.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(run_fetch_my_telegram_api)
        True
    """
    normalized_phone = normalize_phone(phone)
    await _ensure_my_telegram_auth(session, normalized_phone)
    await _open_apps_page(session)
    await _raise_if_rate_limited(session)
    api_id, api_hash, has_creds, needs_create = await _parse_apps_credentials(session)
    if not has_creds and needs_create:
        await _create_app_if_needed(session)
        api_id, api_hash, has_creds, _needs = await _parse_apps_credentials(session)
    elif has_creds:
        session._record_step("mytelegram.use_existing_app")
    if not has_creds:
        text = await session.extract_text(max_chars=12000)
        api_id = api_id or extract_api_id_from_text(text) or ""
        api_hash = api_hash or extract_api_hash_from_text(text) or ""
    if not api_id or not api_hash:
        msg = (
            "could not extract api_id and api_hash from my.telegram.org — "
            "open https://my.telegram.org/apps manually and paste below"
        )
        raise RuntimeError(msg)
    if not api_id.isdigit() or len(api_hash) != 32:
        msg = "extracted my.telegram.org credentials look invalid — paste manually"
        raise RuntimeError(msg)
    session._record_step("mytelegram.credentials_ready")
    return MyTelegramApiExtract(
        api_id=api_id,
        api_hash=api_hash,
        phone=normalized_phone,
    )


__all__ = [
    "CONFIGURE_LATER_HINT",
    "MY_TELEGRAM_APPS_URL",
    "MY_TELEGRAM_AUTH_URL",
    "MyTelegramApiExtract",
    "MyTelegramSkipError",
    "extract_api_hash_from_text",
    "extract_api_id_from_text",
    "normalize_phone",
    "run_fetch_my_telegram_api",
]
