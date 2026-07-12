"""Browser auth helpers — login-state detection, credential login, human handoff, cookies.

Per-site login profiles detect logged-in vs login-form vs 2FA/QR/CAPTCHA challenge states.
The generic :func:`login` scaffold fills identifier/password from the workspace secrets store
(never inline), submits the form, and pauses with ``HUMAN_REQUIRED`` when a human step is
needed. :func:`resume_login` re-checks state after the operator completes verification.
Cookie import/export reuses :meth:`~sevn.browser.page.Page.get_cookies` /
:meth:`~sevn.browser.page.Page.set_cookies` for profile portability and onboarding seeding.

Module: sevn.browser.auth
Depends: asyncio, json, dataclasses, pathlib, sevn.browser.element, sevn.browser.page,
    sevn.browser.recipes.base, sevn.security.secrets

Exports:
    AuthError — auth/login failure (missing credentials, unknown site, …).
    SiteProfile — per-site login detection + form selector map.
    site_profile — resolve a :class:`SiteProfile` for a site key.
    login_state — detect logged-in vs login-form vs human-challenge for a site.
    login — generic credential login scaffold (secrets store only).
    resume_login — re-check login state after a human handoff.
    human_handoff — screenshot + HUMAN_REQUIRED operator payload (D9).
    export_cookies — write browser cookies to a JSON file.
    import_cookies — load cookies from a JSON file into the browser.
    resolve_login_credentials — load identifier/password from the secrets chain.

Examples:
    >>> from sevn.browser.auth import SiteProfile
    >>> "login_url" in SiteProfile.__dataclass_fields__
    True
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from sevn.browser.recipes.base import RecipeError, human_required

if TYPE_CHECKING:
    from sevn.browser.element import Dom
    from sevn.browser.page import Page
    from sevn.config.workspace_config import SecretsBackendSectionConfig

_POST_SUBMIT_PAUSE_S: Final[float] = 0.35


def _write_json(path: Path, payload: object) -> None:
    """Write ``payload`` as JSON to ``path`` (blocking; called via ``to_thread``).

    Args:
        path (Path): Destination file (parents created).
        payload (object): JSON-serializable value.

    Returns:
        None

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_write_json)
        True
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read_json_list(path: Path) -> list[Any]:
    """Read a JSON array from ``path`` (blocking; called via ``to_thread``).

    Args:
        path (Path): Source JSON file.

    Returns:
        list[Any]: Parsed JSON list.

    Raises:
        AuthError: When the file is missing or not a JSON array.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_read_json_list)
        True
    """
    if not path.is_file():
        msg = f"cookies file not found: {path}"
        raise AuthError(msg)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        msg = "cookies file must contain a JSON array"
        raise AuthError(msg)
    return raw


class AuthError(RecipeError):
    """Auth/login could not proceed (missing credentials, unknown site, …)."""


@dataclass(frozen=True)
class SiteProfile:
    """Per-site login URL, DOM markers, and form selectors."""

    login_url: str
    logged_in_markers: tuple[str, ...]
    login_markers: tuple[str, ...]
    challenge_markers: tuple[str, ...]
    identifier_selectors: tuple[str, ...]
    password_selectors: tuple[str, ...]
    submit_selectors: tuple[str, ...]
    challenge_reason: str


_SITE_PROFILES: Final[dict[str, SiteProfile]] = {
    "generic": SiteProfile(
        login_url="about:blank",
        logged_in_markers=(
            "[data-testid='avatar']",
            ".account-avatar",
            "[aria-label*='Account']",
            ".user-menu",
        ),
        login_markers=(
            "input[type='password']",
            "form[action*='login']",
            "#login",
            ".login-form",
        ),
        challenge_markers=(
            ".qr-container",
            ".qr-code",
            "iframe[src*='captcha']",
            "[data-qa='two-factor']",
            ".two-factor",
            "#captcha",
        ),
        identifier_selectors=(
            "input[type='email']",
            "input[name='identifier']",
            "input[name='username']",
            "input[name='email']",
            "input#identifierId",
        ),
        password_selectors=("input[type='password']", "input[name='password']"),
        submit_selectors=(
            "button[type='submit']",
            "input[type='submit']",
            "#passwordNext",
            "#identifierNext",
        ),
        challenge_reason="Complete verification (2FA, QR code, or CAPTCHA) in the browser.",
    ),
    "gmail": SiteProfile(
        login_url="https://mail.google.com/",
        logged_in_markers=("[aria-label*='Google Account']", "[data-tooltip*='Account']", ".gb_d"),
        login_markers=("input[type='email']", "input#identifierId", "input[type='password']"),
        challenge_markers=(
            "iframe[src*='accounts.google.com/v3/signin/challenge']",
            "[data-challengeid]",
            ".qr-code",
        ),
        identifier_selectors=("input[type='email']", "input#identifierId"),
        password_selectors=("input[type='password']", "input[name='Passwd']"),
        submit_selectors=("#identifierNext", "#passwordNext", "button[type='submit']"),
        challenge_reason="Complete Google sign-in verification in the browser window.",
    ),
    "google": SiteProfile(
        login_url="https://accounts.google.com/",
        logged_in_markers=("[data-email]", "[aria-label*='Google Account']"),
        login_markers=("input#identifierId", "input[type='password']"),
        challenge_markers=("[data-challengeid]", ".qr-code", "iframe[src*='captcha']"),
        identifier_selectors=("input#identifierId", "input[type='email']"),
        password_selectors=("input[type='password']", "input[name='Passwd']"),
        submit_selectors=("#identifierNext", "#passwordNext", "button[type='submit']"),
        challenge_reason="Complete Google account verification in the browser window.",
    ),
    "youtube": SiteProfile(
        login_url="https://www.youtube.com/",
        logged_in_markers=("#avatar-btn", "button#avatar-btn", "ytd-topbar-menu-button-renderer"),
        login_markers=("ytd-button-renderer.style-scope", "input[type='email']"),
        challenge_markers=("[data-challengeid]", ".qr-code", "iframe[src*='captcha']"),
        identifier_selectors=("input[type='email']", "input#identifierId"),
        password_selectors=("input[type='password']",),
        submit_selectors=("#identifierNext", "#passwordNext", "button[type='submit']"),
        challenge_reason="Complete YouTube/Google sign-in verification in the browser.",
    ),
    "telegram": SiteProfile(
        login_url="https://web.telegram.org/k/",
        logged_in_markers=("#column-left", ".chatlist", ".sidebar-header"),
        login_markers=(".qr-container", ".login-page", "[data-qr]"),
        challenge_markers=(".qr-container", ".login-page", "[data-qr]", "input[type='tel']"),
        identifier_selectors=("input[type='tel']",),
        password_selectors=(),
        submit_selectors=("button[type='submit']",),
        challenge_reason="Open Telegram on your phone and scan the QR code (or enter the login code).",
    ),
    "x": SiteProfile(
        login_url="https://x.com/login",
        logged_in_markers=(
            "[data-testid='SideNav_AccountSwitcher_Button']",
            "[aria-label*='Profile']",
        ),
        login_markers=("input[name='text']", "input[name='password']", "[data-testid='LoginForm']"),
        challenge_markers=("[data-testid='ocfEnterTextTextInput']", "iframe[src*='captcha']"),
        identifier_selectors=("input[name='text']", "input[autocomplete='username']"),
        password_selectors=("input[name='password']", "input[type='password']"),
        submit_selectors=("[data-testid='LoginForm_Login_Button']", "button[type='submit']"),
        challenge_reason="Complete X/Twitter sign-in verification in the browser.",
    ),
    "linkedin": SiteProfile(
        login_url="https://www.linkedin.com/login",
        logged_in_markers=(
            ".global-nav__me-photo",
            "[data-control-name='identity_welcome_message']",
            ".feed-identity-module",
            "img.global-nav__me-photo",
        ),
        login_markers=(
            "input#username",
            "input[name='session_key']",
            "input#password",
            "form.login__form",
        ),
        challenge_markers=(
            "iframe[src*='captcha']",
            "#captcha-internal",
            "input[name='pin']",
            ".challenge-dialog",
        ),
        identifier_selectors=("input#username", "input[name='session_key']"),
        password_selectors=("input#password", "input[name='session_password']"),
        submit_selectors=("button[type='submit']",),
        challenge_reason="Complete LinkedIn verification (2FA, QR, or CAPTCHA) in the browser.",
    ),
}


def site_profile(site: str) -> SiteProfile:
    """Return the login profile for ``site`` (falls back to ``generic``).

    Args:
        site (str): Site key (``gmail``, ``telegram``, ``generic``, …).

    Returns:
        SiteProfile: Resolved profile.

    Raises:
        AuthError: When ``site`` is empty.

    Examples:
        >>> site_profile("telegram").login_url.startswith("https://web.telegram.org")
        True
    """
    key = (site or "").strip().lower()
    if not key:
        msg = "site is required for login_state/login"
        raise AuthError(msg)
    return _SITE_PROFILES.get(key, _SITE_PROFILES["generic"])


async def _marker_present(page: Page, selectors: tuple[str, ...]) -> bool:
    """Return whether any ``selectors`` match in the current document.

    Args:
        page (Page): Active page.
        selectors (tuple[str, ...]): CSS selectors to probe.

    Returns:
        bool: ``True`` when at least one selector matches.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_marker_present)
        True
    """
    for selector in selectors:
        if await page.evaluate(f"!!document.querySelector({selector!r})"):
            return True
    return False


async def login_state(page: Page, site: str) -> dict[str, Any]:
    """Detect logged-in vs login-form vs human-challenge state for ``site``.

    Args:
        page (Page): Active page (typically already on the site).
        site (str): Site key (``gmail``, ``telegram``, ``generic``, …).

    Returns:
        dict[str, Any]: ``{site, logged_in, state}`` where ``state`` is one of
        ``logged_in``, ``logged_out``, ``human_required``, or ``unknown``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(login_state)
        True
    """
    profile = site_profile(site)
    if await _marker_present(page, profile.logged_in_markers):
        return {"site": site, "logged_in": True, "state": "logged_in"}
    if await _marker_present(page, profile.challenge_markers):
        return {"site": site, "logged_in": False, "state": "human_required"}
    if await _marker_present(page, profile.login_markers):
        return {"site": site, "logged_in": False, "state": "logged_out"}
    return {"site": site, "logged_in": False, "state": "unknown"}


async def resolve_login_credentials(
    content_root: Path,
    credentials_ref: str,
    *,
    secrets_backend: SecretsBackendSectionConfig | None = None,
) -> tuple[str, str]:
    """Load identifier and password from the secrets chain (never from inline args).

    ``credentials_ref`` may be a JSON blob secret (``identifier``/``username``/``email`` +
    ``password`` keys) or a prefix with ``.identifier`` and ``.password`` suffix keys.

    Args:
        content_root (Path): Workspace content root.
        credentials_ref (str): Logical secret ref (never logged).
        secrets_backend (SecretsBackendSectionConfig | None): Optional secrets config section.

    Returns:
        tuple[str, str]: ``(identifier, password)``.

    Raises:
        AuthError: When the ref is missing or incomplete.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(resolve_login_credentials)
        True
    """
    from sevn.security.secrets.chain import get_secret_resilient
    from sevn.security.secrets.factory import secrets_chain_from_workspace

    ref = (credentials_ref or "").strip()
    if not ref:
        msg = "credentials_ref is required (never pass inline passwords)"
        raise AuthError(msg)

    chain = secrets_chain_from_workspace(content_root, secrets_backend)
    raw = await get_secret_resilient(chain, ref)
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            ident = (
                parsed.get("identifier")
                or parsed.get("username")
                or parsed.get("email")
                or parsed.get("user")
            )
            password = parsed.get("password") or parsed.get("pass")
            if isinstance(ident, str) and ident.strip() and isinstance(password, str) and password:
                return ident.strip(), password

    ident = await get_secret_resilient(chain, f"{ref}.identifier")
    password = await get_secret_resilient(chain, f"{ref}.password")
    if ident and password:
        return ident.strip(), password.strip()

    msg = f"credentials not found for ref (LOGIN_REQUIRED): {ref!r}"
    raise AuthError(msg)


async def _first_element(dom: Dom, selectors: tuple[str, ...]) -> Any:
    """Return the first element matching any selector in ``selectors``.

    Args:
        dom (Dom): Finder bound to the active tab.
        selectors (tuple[str, ...]): CSS selectors to try in order.

    Returns:
        Any: Element handle or ``None``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_first_element)
        True
    """
    for selector in selectors:
        element = await dom.query(selector)
        if element is not None:
            return element
    return None


async def human_handoff(
    page: Page,
    reason: str,
    content_root: Path,
    session_id: str,
) -> dict[str, Any]:
    """Capture a screenshot and return a ``HUMAN_REQUIRED`` operator handoff (D9).

    Args:
        page (Page): Active page.
        reason (str): Non-sensitive instruction for the operator.
        content_root (Path): Workspace root (screenshots written under ``screenshots/``).
        session_id (str): Gateway session id (used in the filename).

    Returns:
        dict[str, Any]: Handoff payload with ``human_required``, ``operator_message``, screenshot.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(human_handoff)
        True
    """
    rel: str | None = None
    shots = content_root / "screenshots"
    dest = shots / f"handoff-{session_id}.png"
    with contextlib.suppress(Exception):
        out = await page.screenshot(dest)
        rel = str(Path(out).relative_to(content_root))
    payload = human_required(reason, screenshot=rel, url=await page.url())
    payload["operator_message"] = reason
    return payload


async def login(
    page: Page,
    dom: Dom,
    site: str,
    credentials_ref: str,
    content_root: Path,
    session_id: str,
    *,
    secrets_backend: SecretsBackendSectionConfig | None = None,
) -> dict[str, Any]:
    """Drive a generic login form using secrets-store credentials (D9).

    Checks :func:`login_state` first and skips when already logged in. Navigates to the
    site login URL, fills identifier/password from :func:`resolve_login_credentials`, submits,
    and returns ``HUMAN_REQUIRED`` when 2FA/QR/CAPTCHA markers appear.

    Args:
        page (Page): Active page.
        dom (Dom): Finder bound to the same tab.
        site (str): Site key.
        credentials_ref (str): Secrets ref (never inline credentials).
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id (screenshot naming).
        secrets_backend (SecretsBackendSectionConfig | None): Optional secrets config section.

    Returns:
        dict[str, Any]: ``{logged_in: True}`` or a ``HUMAN_REQUIRED`` handoff payload.

    Raises:
        AuthError: When credentials cannot be resolved.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(login)
        True
    """
    profile = site_profile(site)
    state = await login_state(page, site)
    if state.get("logged_in"):
        return {"logged_in": True, "site": site}

    if profile.login_url and profile.login_url != "about:blank":
        await page.goto(profile.login_url, wait_until="none")

    identifier, password = await resolve_login_credentials(
        content_root, credentials_ref, secrets_backend=secrets_backend
    )

    id_el = await _first_element(dom, profile.identifier_selectors)
    if id_el is not None:
        await id_el.fill(identifier)
    pw_el = await _first_element(dom, profile.password_selectors)
    if pw_el is not None:
        await pw_el.fill(password)
    submit = await _first_element(dom, profile.submit_selectors)
    if submit is not None:
        await submit.click()

    await asyncio.sleep(_POST_SUBMIT_PAUSE_S)
    state = await login_state(page, site)
    if state.get("logged_in"):
        return {"logged_in": True, "site": site}
    if state.get("state") == "human_required":
        return await human_handoff(page, profile.challenge_reason, content_root, session_id)
    if await _marker_present(page, profile.login_markers):
        return await human_handoff(
            page,
            profile.challenge_reason,
            content_root,
            session_id,
        )
    return {"logged_in": False, "site": site, "code": "LOGIN_REQUIRED"}


async def resume_login(
    page: Page,
    site: str,
    content_root: Path,
    session_id: str,
) -> dict[str, Any]:
    """Re-check login state after the operator completes a human step (D9).

    Args:
        page (Page): Active page (operator should have finished verification).
        site (str): Site key.
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.

    Returns:
        dict[str, Any]: ``{logged_in: True}``, another ``HUMAN_REQUIRED`` handoff, or
        ``{code: LOGIN_REQUIRED}``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(resume_login)
        True
    """
    profile = site_profile(site)
    state = await login_state(page, site)
    if state.get("logged_in"):
        return {"logged_in": True, "site": site}
    if state.get("state") == "human_required":
        return await human_handoff(page, profile.challenge_reason, content_root, session_id)
    if await _marker_present(page, profile.login_markers):
        return await human_handoff(
            page,
            "Complete sign-in in the browser window, then call resume_login.",
            content_root,
            session_id,
        )
    return {"logged_in": False, "site": site, "code": "LOGIN_REQUIRED"}


async def export_cookies(page: Page, path: Path) -> dict[str, Any]:
    """Export all browser cookies to a JSON file (portability / onboarding seed).

    Args:
        page (Page): Active page.
        path (Path): Destination ``.json`` file (parents created).

    Returns:
        dict[str, Any]: ``{exported, path}`` — cookie values are on disk only, not echoed.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(export_cookies)
        True
    """
    cookies = await page.get_cookies()
    await asyncio.to_thread(_write_json, path, cookies)
    return {"exported": len(cookies), "path": str(path)}


async def import_cookies(page: Page, path: Path) -> dict[str, Any]:
    """Import cookies from a JSON file via :meth:`Page.set_cookies`.

    Args:
        page (Page): Active page.
        path (Path): Source ``.json`` file written by :func:`export_cookies`.

    Returns:
        dict[str, Any]: ``{imported, path}``.

    Raises:
        AuthError: When the file is missing or not a JSON list.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(import_cookies)
        True
    """
    raw = await asyncio.to_thread(_read_json_list, path)
    cookies = [c for c in raw if isinstance(c, dict)]
    count = await page.set_cookies(cookies)
    return {"imported": count, "path": str(path)}


__all__ = [
    "AuthError",
    "SiteProfile",
    "export_cookies",
    "human_handoff",
    "import_cookies",
    "login",
    "login_state",
    "resolve_login_credentials",
    "resume_login",
    "site_profile",
]
