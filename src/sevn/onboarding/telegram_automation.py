"""Telegram Web / BotFather automation for the onboarding wizard (D10, W5).

Uses :class:`~sevn.onboarding.browser_automation.BrowserSession` (system Chrome via
native CDP) to drive Telegram Web end to end: wait for the operator to sign in, open
``@BotFather``, run the ``/newbot`` (or ``/token``) conversation by waiting for each
prompt before replying, then read the operator user id from ``@getidsbot`` — all
without per-step button presses.

Module: sevn.onboarding.telegram_automation
Depends: asyncio, contextlib, dataclasses, re, time, sevn.onboarding.browser_automation

Exports:
    TelegramBotExtract — parsed bot token, username, and optional owner id.
    extract_bot_token_from_text — regex helper for BotFather replies.
    extract_bot_username_from_text — parse ``@username`` from page text.
    normalize_bot_username — strip leading ``@`` and validate shape.
    open_telegram_web — navigate the active tab to Telegram Web.
    run_create_new_bot — BotFather ``/newbot`` conversation (waits for each prompt).
    run_lookup_existing_bot — BotFather ``/token`` lookup by username.
    suggest_owner_user_id_from_text — infer operator user id from profile text.
    wait_for_login — block until Telegram Web shows the logged-in chat list.

Examples:
    >>> extract_bot_token_from_text("Use this token: 123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw")
    '123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw'
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass

from sevn.onboarding.browser_automation import BrowserSession

TELEGRAM_WEB_URL = "https://web.telegram.org/k/"
BOTFATHER_URL = "https://web.telegram.org/k/#@BotFather"
GETIDSBOT_URL = "https://web.telegram.org/k/#@getidsbot"

_BOT_TOKEN_RE = re.compile(r"\b(\d{8,12}:[A-Za-z0-9_-]{30,50})\b")
_BOT_USERNAME_RE = re.compile(r"@([a-zA-Z][a-zA-Z0-9_]{4,31})")
_OWNER_ID_HINT_RE = re.compile(
    r"(?:user\s*id|your\s*id|Id)\s*[:#]?\s*(\d{6,12})",
    re.IGNORECASE,
)

_COMPOSER_SELECTORS: tuple[str, ...] = (
    ".input-message-input",
    "#editable-message-text",
    "[contenteditable='true']",
    "div[contenteditable=true]",
)

_NAME_PROMPT_NEEDLES: tuple[str, ...] = (
    "choose a name for your bot",
    "how are we going to call it",
)
_USERNAME_PROMPT_NEEDLES: tuple[str, ...] = (
    "choose a username for your bot",
    "username for your bot",
    "username must end",
)
_USERNAME_TAKEN_NEEDLES: tuple[str, ...] = (
    "is already taken",
    "sorry, this username",
    "invalid username",
)
_TOKEN_READY_NEEDLES: tuple[str, ...] = (
    "use this token to access the http api",
    "access the http api",
    "congratulations on your new bot",
)
_TOKEN_REQUEST_NEEDLES: tuple[str, ...] = (
    "choose a bot",
    "which bot",
    "token",
)
_OWNER_ID_NEEDLES: tuple[str, ...] = ("id:", "user id", "your id")

# Telegram Web K renders the newest incoming (BotFather) message as the last
# ``.bubble.is-in`` element; reading only that bubble avoids matching old history.
_LAST_INCOMING_JS = (
    "(() => {"
    " const b = Array.from(document.querySelectorAll('.bubble.is-in'));"
    " const last = b[b.length - 1];"
    " if (!last) return '';"
    " const m = last.querySelector('.message, .translatable-message, .text-content');"
    " return ((m || last).textContent || '').trim();"
    "})()"
)
_INCOMING_COUNT_JS = "(() => document.querySelectorAll('.bubble.is-in').length)()"

_LOGIN_TIMEOUT_SECONDS = 600.0
_LOGIN_POLL_SECONDS = 10.0
_COMPOSER_TIMEOUT_SECONDS = 30.0
_PROMPT_TIMEOUT_SECONDS = 45.0
_USERNAME_TIMEOUT_SECONDS = 30.0
_OWNER_ID_TIMEOUT_SECONDS = 25.0
_POLL_SECONDS = 0.6
_HUMAN_PAUSE_MIN_SECONDS = 1.0
_HUMAN_PAUSE_MAX_SECONDS = 2.0

_LOGGED_IN_JS = (
    "(() => {"
    " function vis(el) {"
    "   if (!el) return false;"
    "   const r = el.getBoundingClientRect();"
    "   if (r.width < 2 || r.height < 2) return false;"
    "   const s = getComputedStyle(el);"
    "   return s.display !== 'none' && s.visibility !== 'hidden'"
    "     && parseFloat(s.opacity || '1') > 0.01;"
    " }"
    " const authNodes = document.querySelectorAll("
    "   '#auth-pages, .auth-form, .page-signQR, .page-signPhone, .page-authCode'"
    " );"
    " for (const node of authNodes) { if (vis(node)) return false; }"
    " const left = document.querySelector('#column-left');"
    " if (vis(left) && left.querySelector("
    "   '.chatlist, .chatlist-chat, .input-search, .folders-tabs-scrollable'"
    " )) return true;"
    " if (document.querySelectorAll('.chatlist-chat, .ListItem.chat-item').length > 0)"
    "   return true;"
    " const search = document.querySelector("
    "   '#column-left .input-search, .sidebar-header .input-search'"
    " );"
    " return vis(search);"
    "})()"
)


def _eval_bool(value: object) -> bool:
    """Coerce a CDP ``Runtime.evaluate`` result to ``bool``.

    CDP evaluate may return JSON booleans or stringified ``\"true\"``/``\"false\"``.

    Args:
        value (object): Raw evaluate return value.

    Returns:
        bool: Coerced truthiness.

    Examples:
        >>> _eval_bool(True)
        True
        >>> _eval_bool("true")
        True
        >>> _eval_bool("false")
        False
    """
    if value is True:
        return True
    if value is False or value is None:
        return False
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1"}:
            return True
        if lowered in {"false", "0", "", "null", "undefined"}:
            return False
    if isinstance(value, (int, float)):
        return value != 0
    return bool(value)


@dataclass(frozen=True, slots=True)
class TelegramBotExtract:
    """Credentials extracted from Telegram Web / BotFather automation."""

    bot_token: str
    bot_username: str
    owner_user_id: str | None = None


def normalize_bot_username(raw: str) -> str:
    """Return a bare bot username without a leading ``@``.

    Args:
        raw (str): Operator or page-supplied username.

    Returns:
        str: Normalised username (lowercase, no ``@``).

    Raises:
        ValueError: When the username is empty or invalid.

    Examples:
        >>> normalize_bot_username("@MySevnBot")
        'mysevnbot'
    """
    text = raw.strip().lstrip("@").lower()
    if not text:
        msg = "bot username is required"
        raise ValueError(msg)
    if not re.fullmatch(r"[a-z][a-z0-9_]{4,31}", text):
        msg = "bot username must be 5-32 characters: letters, digits, underscore"
        raise ValueError(msg)
    return text


def extract_bot_token_from_text(text: str) -> str | None:
    """Return the first BotFather-style bot token in ``text``.

    Args:
        text (str): Visible page or message text.

    Returns:
        str | None: Token when matched.

    Examples:
        >>> extract_bot_token_from_text("token: 123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw")
        '123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw'
    """
    match = _BOT_TOKEN_RE.search(text)
    return match.group(1) if match else None


def _latest_bot_token_from_text(text: str) -> str | None:
    """Return the last BotFather-style bot token in ``text`` (newest message).

    Args:
        text (str): Visible page or message text (oldest first, newest last).

    Returns:
        str | None: Most recent token when matched.

    Examples:
        >>> _latest_bot_token_from_text(
        ...     "old 111111111:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw "
        ...     "new 222222222:BBHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
        ... )
        '222222222:BBHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw'
    """
    matches = _BOT_TOKEN_RE.findall(text)
    return matches[-1] if matches else None


def extract_bot_username_from_text(text: str) -> str | None:
    """Return the first ``@username`` token in ``text``.

    Args:
        text (str): Visible page or message text.

    Returns:
        str | None: Username without ``@`` when matched.

    Examples:
        >>> extract_bot_username_from_text("Done! @my_sevn_bot is ready.")
        'my_sevn_bot'
    """
    match = _BOT_USERNAME_RE.search(text)
    return match.group(1) if match else None


def suggest_owner_user_id_from_text(text: str) -> str | None:
    """Best-effort owner user id from Telegram Web profile or settings text.

    Args:
        text (str): Page text that may mention the logged-in user id.

    Returns:
        str | None: Numeric user id when a hint is found.

    Examples:
        >>> suggest_owner_user_id_from_text("Your Id: 123456789")
        '123456789'
    """
    match = _OWNER_ID_HINT_RE.search(text)
    if match:
        return match.group(1)
    return None


def _username_candidates(name: str) -> Iterator[str]:
    """Yield valid BotFather usernames derived from a display name.

    Args:
        name (str): Bot display name.

    Returns:
        Iterator[str]: Candidate usernames ending in ``bot`` (base, then suffixed).

    Examples:
        >>> next(_username_candidates("Test Bot"))
        'test_bot'
    """
    core = re.sub(r"[^a-z0-9]", "", name.lower())
    if core.endswith("bot"):
        core = core[:-3]
    core = core[:24] or "sevn"
    if not core[0].isalpha():
        core = f"s{core}"
    yield f"{core}_bot"
    for i in range(1, 6):
        yield f"{core}{i}_bot"


async def open_telegram_web(session: BrowserSession) -> dict[str, object]:
    """Navigate the active browser tab to Telegram Web K.

    Args:
        session (BrowserSession): Started onboarding browser session.

    Returns:
        dict[str, object]: Tab info row after navigation.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(open_telegram_web)
        True
    """
    return await session.open_url(TELEGRAM_WEB_URL)


async def wait_for_login(
    session: BrowserSession,
    *,
    wait_seconds: float = _LOGIN_TIMEOUT_SECONDS,
) -> None:
    """Block until Telegram Web shows the logged-in chat list.

    Polls every :data:`_LOGIN_POLL_SECONDS` (10s) so the operator can scan the QR
    code or sign in without hammering the page. Records ``telegram.wait_login`` on
    the browser session for wizard status polling.

    Args:
        session (BrowserSession): Active browser session on Telegram Web.
        wait_seconds (float): Maximum seconds to wait for the operator to sign in.

    Returns:
        None

    Raises:
        TimeoutError: When the chat list does not appear in time.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(wait_for_login)
        True
    """
    session._record_step("telegram.wait_login", state="running")
    tab = session._resolve_tab()
    deadline = time.monotonic() + max(1.0, wait_seconds)
    while time.monotonic() < deadline:
        with contextlib.suppress(Exception):
            logged_in = await tab.evaluate(_LOGGED_IN_JS, await_promise=False)
            if _eval_bool(logged_in):
                session._record_step("telegram.logged_in")
                if session._steps and session._steps[-2]["label"] == "telegram.wait_login":
                    session._steps[-2]["state"] = "done"
                return
        await asyncio.sleep(_LOGIN_POLL_SECONDS)
    if session._steps and session._steps[-1]["label"] == "telegram.wait_login":
        session._steps[-1]["state"] = "done"
    msg = "not logged into Telegram Web — scan the QR code or sign in, then retry"
    raise TimeoutError(msg)


async def _human_pause() -> None:
    """Sleep a random 1-2 seconds between BotFather messages (human-like pacing).

    Returns:
        None

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_human_pause)
        True
    """
    await asyncio.sleep(random.uniform(_HUMAN_PAUSE_MIN_SECONDS, _HUMAN_PAUSE_MAX_SECONDS))  # nosec B311 — UX jitter, not crypto


async def _wait_for_composer(
    session: BrowserSession,
    *,
    wait_seconds: float = _COMPOSER_TIMEOUT_SECONDS,
) -> None:
    """Block until the open chat's message composer is ready.

    Args:
        session (BrowserSession): Active browser session with a chat open.
        wait_seconds (float): Maximum seconds to wait for the composer element.

    Returns:
        None

    Raises:
        RuntimeError: When no composer appears in time.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_wait_for_composer)
        True
    """
    tab = session._resolve_tab()
    deadline = time.monotonic() + max(1.0, wait_seconds)
    while time.monotonic() < deadline:
        for selector in _COMPOSER_SELECTORS:
            with contextlib.suppress(Exception):
                if await tab.select(selector, timeout=1) is not None:
                    return
        await asyncio.sleep(_POLL_SECONDS)
    msg = "Telegram message composer not found — make sure you are logged in"
    raise RuntimeError(msg)


async def _press_enter(session: BrowserSession) -> None:
    """Dispatch a real ``Enter`` keypress to submit the focused composer.

    Legacy CDP ``send_keys`` paths emit only ``char`` events, so a literal ``"\\n"`` is inserted
    as a literal newline instead of submitting. Telegram Web sends on a true Enter
    ``keyDown``/``keyUp``, dispatched here via ``Input.dispatchKeyEvent``.

    Args:
        session (BrowserSession): Active browser session with the composer focused.

    Returns:
        None

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_press_enter)
        True
    """
    await session.press_enter()


async def _send_chat_message(session: BrowserSession, text: str) -> None:
    """Type a message into the Telegram Web composer and submit it with Enter.

    Args:
        session (BrowserSession): Active browser session.
        text (str): Message body (for example ``/newbot``).

    Returns:
        None

    Raises:
        RuntimeError: When no composer element is found.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_send_chat_message)
        True
    """
    tab = session._resolve_tab()
    last_exc: Exception | None = None
    for selector in _COMPOSER_SELECTORS:
        try:
            elem = await tab.select(selector, timeout=4)
            if elem is None:
                continue
            await elem.send_keys(text)
            await _press_enter(session)
            await _human_pause()
            return
        except Exception as exc:
            last_exc = exc
            continue
    msg = "could not find Telegram message composer — log in to Telegram Web first"
    if last_exc is not None:
        msg = f"{msg} ({last_exc})"
    raise RuntimeError(msg)


async def _incoming_count(session: BrowserSession) -> int:
    """Return how many incoming (BotFather) message bubbles are rendered.

    Args:
        session (BrowserSession): Active browser session.

    Returns:
        int: Count of ``.bubble.is-in`` elements (0 on failure).

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_incoming_count)
        True
    """
    tab = session._resolve_tab()
    with contextlib.suppress(Exception):
        result = await tab.evaluate(_INCOMING_COUNT_JS, await_promise=False)
        if isinstance(result, (int, float)):
            return int(result)
    return 0


async def _last_incoming_text(session: BrowserSession) -> str:
    """Return the text of the newest incoming (BotFather) message bubble.

    Args:
        session (BrowserSession): Active browser session.

    Returns:
        str: Latest incoming bubble text (empty when none/failure).

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_last_incoming_text)
        True
    """
    tab = session._resolve_tab()
    with contextlib.suppress(Exception):
        result = await tab.evaluate(_LAST_INCOMING_JS, await_promise=False)
        if isinstance(result, str):
            return result
    return ""


async def _send_and_wait(
    session: BrowserSession,
    message: str,
    needles: tuple[str, ...],
    *,
    wait_seconds: float,
    poll: float = _POLL_SECONDS,
) -> tuple[bool, str]:
    """Send ``message`` then wait for a new incoming reply matching a needle.

    Waits for the incoming-bubble count to grow (a fresh BotFather reply) instead
    of scraping the whole transcript, so identical/older prompts are not matched.

    Args:
        session (BrowserSession): Active browser session in the target chat.
        message (str): Text to send (for example ``/newbot``).
        needles (tuple[str, ...]): Case-insensitive substrings to wait for.
        wait_seconds (float): Maximum seconds to wait for the reply.
        poll (float): Seconds between reads.

    Returns:
        tuple[bool, str]: ``(matched, latest_reply_text)`` — best-effort, never raises.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_send_and_wait)
        True
    """
    lowered = tuple(n.lower() for n in needles)
    before = await _incoming_count(session)
    await _send_chat_message(session, message)
    deadline = time.monotonic() + max(0.1, wait_seconds)
    text = ""
    while time.monotonic() < deadline:
        if await _incoming_count(session) > before:
            text = await _last_incoming_text(session)
            if any(n in text.lower() for n in lowered):
                return True, text
        await asyncio.sleep(poll)
    text = await _last_incoming_text(session)
    return any(n in text.lower() for n in lowered), text


async def _open_chat(session: BrowserSession, hash_url: str) -> None:
    """Open a Telegram Web chat by deep-link hash and wait for its composer.

    Telegram Web K only opens a ``#@username`` chat on a fresh document load — an
    in-app hash change is a no-op for the SPA. Routing through ``about:blank`` forces
    a full reload so the anchor is honoured on boot (works for switching chats too).

    Args:
        session (BrowserSession): Active browser session.
        hash_url (str): Telegram Web URL with a ``#@username`` chat anchor.

    Returns:
        None

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_open_chat)
        True
    """
    await session.open_url("about:blank")
    await asyncio.sleep(0.5)
    await session.open_url(hash_url)
    await _wait_for_composer(session)


async def _submit_username(session: BrowserSession, display_name: str) -> tuple[str, str]:
    """Send generated usernames until BotFather accepts one (returns its reply).

    Args:
        session (BrowserSession): Active browser session in the BotFather chat.
        display_name (str): Bot display name used to derive candidate usernames.

    Returns:
        tuple[str, str]: ``(accepted_username, botfather_reply_text)``.

    Raises:
        RuntimeError: When every generated candidate is rejected.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_submit_username)
        True
    """
    taken_needles = tuple(n.lower() for n in _USERNAME_TAKEN_NEEDLES)
    ok_needles = tuple(n.lower() for n in _TOKEN_READY_NEEDLES)
    for candidate in _username_candidates(display_name):
        before = await _incoming_count(session)
        await _send_chat_message(session, candidate)
        deadline = time.monotonic() + _USERNAME_TIMEOUT_SECONDS
        text = ""
        while time.monotonic() < deadline:
            if await _incoming_count(session) > before:
                text = await _last_incoming_text(session)
                low = text.lower()
                if _BOT_TOKEN_RE.search(text) or any(n in low for n in ok_needles):
                    return normalize_bot_username(candidate), text
                if any(n in low for n in taken_needles):
                    break
            await asyncio.sleep(_POLL_SECONDS)
        else:
            return normalize_bot_username(candidate), text
    msg = "BotFather rejected every generated username — choose one manually and retry"
    raise RuntimeError(msg)


async def _read_owner_user_id(session: BrowserSession) -> str | None:
    """Open ``@getidsbot`` and read the operator's numeric user id (best-effort).

    Args:
        session (BrowserSession): Active browser session.

    Returns:
        str | None: Numeric user id when getIDsBot replies, else ``None``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_read_owner_user_id)
        True
    """
    with contextlib.suppress(Exception):
        await _open_chat(session, GETIDSBOT_URL)
        await _send_chat_message(session, "/start")
        deadline = time.monotonic() + _OWNER_ID_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            owner = suggest_owner_user_id_from_text(await _last_incoming_text(session))
            if owner:
                return owner
            await asyncio.sleep(_POLL_SECONDS)
    return None


async def run_create_new_bot(
    session: BrowserSession,
    *,
    display_name: str | None = None,
) -> TelegramBotExtract:
    """Drive the full BotFather ``/newbot`` conversation without user intervention.

    Waits for the operator to log in, opens ``@BotFather``, sends ``/newbot``, waits
    for the name prompt before sending the display name, submits a username (retrying
    if taken), reads the token, then reads the owner id from ``@getidsbot``.

    Args:
        session (BrowserSession): Started onboarding browser session.
        display_name (str | None): Bot display name; defaults to ``My Sevn Bot``.

    Returns:
        TelegramBotExtract: Parsed credentials.

    Raises:
        RuntimeError: When automation cannot extract a token.
        TimeoutError: When the operator does not sign in before the login timeout.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(run_create_new_bot)
        True
    """
    name = (display_name or "My Sevn Bot").strip() or "My Sevn Bot"
    await open_telegram_web(session)
    await wait_for_login(session)
    await _open_chat(session, BOTFATHER_URL)
    await _send_and_wait(
        session, "/newbot", _NAME_PROMPT_NEEDLES, wait_seconds=_PROMPT_TIMEOUT_SECONDS
    )
    await _send_and_wait(
        session, name, _USERNAME_PROMPT_NEEDLES, wait_seconds=_PROMPT_TIMEOUT_SECONDS
    )
    username, reply = await _submit_username(session, name)
    token = _latest_bot_token_from_text(reply)
    if not token:
        msg = (
            "could not extract bot token from BotFather — paste the token manually "
            "or retry after logging into Telegram Web"
        )
        raise RuntimeError(msg)
    parsed = extract_bot_username_from_text(reply)
    final_username = normalize_bot_username(parsed) if parsed else username
    owner_id = await _read_owner_user_id(session)
    return TelegramBotExtract(
        bot_token=token,
        bot_username=final_username,
        owner_user_id=owner_id,
    )


async def run_lookup_existing_bot(
    session: BrowserSession,
    *,
    bot_username: str,
) -> TelegramBotExtract:
    """Ask BotFather for an existing bot token via ``/token`` (waits for replies).

    Args:
        session (BrowserSession): Started onboarding browser session.
        bot_username (str): Existing bot username (with or without ``@``).

    Returns:
        TelegramBotExtract: Parsed credentials when BotFather replies with a token.

    Raises:
        RuntimeError: When no token appears in the chat.
        TimeoutError: When the operator does not sign in before the login timeout.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(run_lookup_existing_bot)
        True
    """
    username = normalize_bot_username(bot_username)
    await open_telegram_web(session)
    await wait_for_login(session)
    await _open_chat(session, BOTFATHER_URL)
    await _send_and_wait(
        session, "/token", _TOKEN_REQUEST_NEEDLES, wait_seconds=_PROMPT_TIMEOUT_SECONDS
    )
    _matched, reply = await _send_and_wait(
        session,
        f"@{username}",
        (*_TOKEN_READY_NEEDLES, "token"),
        wait_seconds=_PROMPT_TIMEOUT_SECONDS,
    )
    token = _latest_bot_token_from_text(reply)
    if not token:
        msg = (
            f"could not extract token for @{username} — open "
            "https://t.me/BotFather and send /token manually, then paste below"
        )
        raise RuntimeError(msg)
    owner_id = await _read_owner_user_id(session)
    return TelegramBotExtract(
        bot_token=token,
        bot_username=username,
        owner_user_id=owner_id,
    )


__all__ = [
    "BOTFATHER_URL",
    "GETIDSBOT_URL",
    "TELEGRAM_WEB_URL",
    "TelegramBotExtract",
    "extract_bot_token_from_text",
    "extract_bot_username_from_text",
    "normalize_bot_username",
    "open_telegram_web",
    "run_create_new_bot",
    "run_lookup_existing_bot",
    "suggest_owner_user_id_from_text",
    "wait_for_login",
]
