"""Session-bound logged-in browser helpers for ``x-use`` and ``facebook-use`` skills.

Module: sevn.skills.social_browser
Depends: asyncio, pathlib, urllib.parse, urllib.request, sevn.config.workspace_config

Exports:
    host_allowed — suffix match against an egress allowlist.
    validate_social_url — parse URL and enforce skill egress policy.
    resolve_browser_profile — resolve persistent Chrome profile directory.
    dry_run_requested — CLI/env dry-run selector.
    cdp_reachable — probe CDP HTTP endpoint without Playwright.
    default_cdp_url — read ``SEVN_CDP_URL`` with localhost default.
    session_status_payload — JSON payload for ``session_status`` scripts.
    merge_social_browser_proc_env — inject profile/CDP env for skill subprocesses.
    x_search_url — build an X search URL from a query string.
    facebook_search_url — build a Facebook search URL from a query string.
    logged_in_browser_page — async context manager yielding a Playwright page.
    fetch_page_snapshot — navigate and return page text snapshot (live or dry-run).
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Final
from urllib.parse import quote_plus, urlparse

from sevn.config.workspace_config import WorkspaceConfig
from sevn.skills.browser_session import (
    browser_page,
    merge_browser_proc_env,
    resolve_profile_dir,
)
from sevn.skills.browser_session import (
    cdp_reachable as _cdp_reachable,
)
from sevn.skills.browser_session import (
    default_cdp_url as _default_cdp_url,
)
from sevn.skills.browser_session import (
    session_status_payload as _session_status_payload,
)

X_USE_SKILL_ID: Final[str] = "x-use"
FACEBOOK_USE_SKILL_ID: Final[str] = "facebook-use"
SOCIAL_BROWSER_SKILL_IDS: Final[frozenset[str]] = frozenset(
    {X_USE_SKILL_ID, FACEBOOK_USE_SKILL_ID},
)

X_EGRESS_DOMAINS: Final[tuple[str, ...]] = (
    "x.com",
    "twitter.com",
    "twimg.com",
    "abs.twimg.com",
    "pbs.twimg.com",
    "video.twimg.com",
    "api.twitter.com",
    "api.x.com",
    "t.co",
)

FACEBOOK_EGRESS_DOMAINS: Final[tuple[str, ...]] = (
    "facebook.com",
    "fb.com",
    "fbcdn.net",
    "fbsbx.com",
    "facebook.net",
    "messenger.com",
)

SKILL_EGRESS: Final[dict[str, tuple[str, ...]]] = {
    X_USE_SKILL_ID: X_EGRESS_DOMAINS,
    FACEBOOK_USE_SKILL_ID: FACEBOOK_EGRESS_DOMAINS,
}

_DRY_RUN_ENV = "SEVN_SOCIAL_BROWSER_DRY_RUN"
_DEFAULT_PROFILE_NAME = "default"


def host_allowed(host: str, *, allowlist: tuple[str, ...]) -> bool:
    """Return whether ``host`` matches an allowlisted egress suffix.

    Args:
        host (str): Parsed URL hostname.
        allowlist (tuple[str, ...]): Host suffixes permitted for navigation.

    Returns:
        bool: ``True`` when the host equals or ends with ``.<suffix>`` for some suffix.

    Examples:
        >>> host_allowed("www.x.com", allowlist=X_EGRESS_DOMAINS)
        True
        >>> host_allowed("evil.example", allowlist=X_EGRESS_DOMAINS)
        False
    """
    normalized = host.lower().rstrip(".")
    if not normalized:
        return False
    for suffix in allowlist:
        candidate = suffix.lower()
        if normalized == candidate or normalized.endswith(f".{candidate}"):
            return True
    return False


def validate_social_url(raw_url: str, *, skill_id: str) -> str:
    """Validate ``raw_url`` against the skill session-bound egress allowlist.

    Args:
        raw_url (str): Target page URL supplied by the agent.
        skill_id (str): Bundled skill id (``x-use`` or ``facebook-use``).

    Returns:
        str: Stripped URL when the host is allowlisted.

    Raises:
        ValueError: When ``skill_id`` is unknown or the host is not allowlisted.

    Examples:
        >>> validate_social_url("https://x.com/home", skill_id="x-use")
        'https://x.com/home'
    """
    allowlist = SKILL_EGRESS.get(skill_id)
    if allowlist is None:
        msg = f"unknown social browser skill {skill_id!r}"
        raise ValueError(msg)
    url = raw_url.strip()
    if not url:
        raise ValueError("url is required")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("url must use http or https")
    if not parsed.netloc:
        raise ValueError("url must include a host")
    if not host_allowed(parsed.hostname or "", allowlist=allowlist):
        raise ValueError(f"host {parsed.hostname!r} is outside session-bound egress allowlist")
    return url


def dry_run_requested(*, cli_flag: bool = False) -> bool:
    """Return whether social-browser scripts should emit a dry-run plan only.

    Args:
        cli_flag (bool): ``True`` when ``--dry-run`` was passed on the CLI.

    Returns:
        bool: ``True`` when dry-run is requested via CLI or ``SEVN_SOCIAL_BROWSER_DRY_RUN``.

    Examples:
        >>> dry_run_requested(cli_flag=True)
        True
    """
    if cli_flag:
        return True
    return os.environ.get(_DRY_RUN_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def default_cdp_url() -> str:
    """Return the CDP HTTP endpoint URL from the environment.

    Returns:
        str: ``SEVN_CDP_URL`` when set, otherwise ``http://127.0.0.1:9222``.

    Examples:
        >>> default_cdp_url().startswith("http")
        True
    """
    url = _default_cdp_url()
    return url.rstrip("/") if url else "http://127.0.0.1:9222"


def cdp_reachable(url: str, *, timeout: float = 2.0) -> bool:
    """Return whether the CDP HTTP endpoint responds.

    Args:
        url (str): CDP base URL (for example ``http://127.0.0.1:9222``).
        timeout (float): Probe timeout in seconds.

    Returns:
        bool: ``True`` when ``/json/version`` returns HTTP 200.

    Examples:
        >>> cdp_reachable("http://127.0.0.1:1")
        False
    """
    return _cdp_reachable(url, timeout=timeout)


def resolve_browser_profile(
    workspace: Path,
    *,
    skill_id: str,
    cfg: WorkspaceConfig | None = None,
) -> Path:
    """Resolve the persistent Chrome profile directory for a social browser skill.

    Precedence: ``SEVN_BROWSER_PROFILE_DIR`` env → ``skills.social_browser.profile_dir``
    → ``skills.<skill>.profile_dir`` → ``<workspace>/.sevn/browser-profiles/default``.

    Args:
        workspace (Path): Workspace content root.
        skill_id (str): Bundled skill id.
        cfg (WorkspaceConfig | None): Optional workspace config for profile overrides.

    Returns:
        Path: Absolute profile directory (may not exist yet).

    Examples:
        >>> import tempfile
        >>> ws = Path(tempfile.mkdtemp())
        >>> resolve_browser_profile(ws, skill_id="x-use").name
        'default'
    """
    _ = skill_id
    session_id = os.environ.get("SEVN_SESSION_ID", "").strip() or _DEFAULT_PROFILE_NAME
    return resolve_profile_dir(workspace, session_id, cfg=cfg)


def merge_social_browser_proc_env(
    env: dict[str, str],
    *,
    skill_id: str,
    workspace: Path,
    cfg: WorkspaceConfig | None,
) -> None:
    """Inject logged-in browser session env vars for social skill subprocesses (in-place).

    Args:
        env (dict[str, str]): Subprocess environment to mutate.
        skill_id (str): Canonical bundled skill id.
        workspace (Path): Workspace content root.
        cfg (WorkspaceConfig | None): Workspace config for profile resolution.

    Returns:
        None

    Examples:
        >>> env: dict[str, str] = {}
        >>> import tempfile
        >>> merge_social_browser_proc_env(env, skill_id="x-use", workspace=Path(tempfile.mkdtemp()), cfg=None)
        >>> "SEVN_BROWSER_PROFILE_DIR" in env
        True
    """
    if skill_id not in SOCIAL_BROWSER_SKILL_IDS:
        return
    session_id = env.get("SEVN_SESSION_ID", "").strip()
    merge_browser_proc_env(
        env,
        content_root=workspace,
        session_id=session_id,
        cfg=cfg,
        skill_name=skill_id,
    )


def session_status_payload(
    *,
    skill_id: str,
    workspace: Path,
    cfg: WorkspaceConfig | None,
    cdp_url: str | None = None,
) -> dict[str, object]:
    """Build the ``session_status`` JSON payload for a social browser skill.

    Args:
        skill_id (str): Bundled skill id.
        workspace (Path): Workspace content root.
        cfg (WorkspaceConfig | None): Workspace config for profile resolution.
        cdp_url (str | None): Optional CDP override; defaults to :func:`default_cdp_url`.

    Returns:
        dict[str, object]: Profile path, CDP reachability, and egress allowlist metadata.

    Examples:
        >>> import tempfile
        >>> payload = session_status_payload(skill_id="x-use", workspace=Path(tempfile.mkdtemp()), cfg=None)
        >>> payload["skill_id"]
        'x-use'
    """
    session_id = os.environ.get("SEVN_SESSION_ID", "").strip() or _DEFAULT_PROFILE_NAME
    base = _session_status_payload(
        content_root=workspace,
        session_id=session_id,
        cfg=cfg,
        skill_name=skill_id,
    )
    if cdp_url is not None:
        base = {**base, "cdp_url": cdp_url.rstrip("/"), "cdp_reachable": cdp_reachable(cdp_url)}
    allowlist = SKILL_EGRESS[skill_id]
    return {
        **base,
        "skill_id": skill_id,
        "egress_domains": list(allowlist),
        "session_model": "logged_in_browser_profile_or_cdp_attach",
    }


def x_search_url(query: str) -> str:
    """Return an X search URL for ``query``.

    Args:
        query (str): Search terms.

    Returns:
        str: HTTPS search URL on ``x.com``.

    Examples:
        >>> x_search_url("hello world")
        'https://x.com/search?q=hello+world'
    """
    return f"https://x.com/search?q={quote_plus(query.strip())}"


def facebook_search_url(query: str) -> str:
    """Return a Facebook search URL for ``query``.

    Args:
        query (str): Search terms.

    Returns:
        str: HTTPS search URL on ``facebook.com``.

    Examples:
        >>> facebook_search_url("hello")
        'https://www.facebook.com/search/top?q=hello'
    """
    return f"https://www.facebook.com/search/top?q={quote_plus(query.strip())}"


def _content_root_from_env() -> Path:
    """Return workspace content root from ``SEVN_CONTENT_ROOT``.

    Returns:
        Path: Absolute content root directory.

    Raises:
        RuntimeError: When ``SEVN_CONTENT_ROOT`` is unset.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_content_root_from_env)
        True
    """
    content_raw = os.environ.get("SEVN_CONTENT_ROOT", "").strip()
    if not content_raw:
        msg = "SEVN_CONTENT_ROOT is not set (gateway should inject it for skill runs)."
        raise RuntimeError(msg)
    return Path(content_raw).expanduser().resolve()


@asynccontextmanager
async def logged_in_browser_page(*, profile_dir: Path) -> AsyncIterator[Any]:
    """Yield a Playwright page using the shared session browser lifecycle.

    Args:
        profile_dir (Path): Legacy parameter; profile resolution uses
            ``SEVN_CONTENT_ROOT`` + ``SEVN_SESSION_ID`` via :func:`browser_page`.

    Yields:
        Any: Playwright ``Page`` connected via CDP or spawned Chrome.

    Returns:
        AsyncIterator[Any]: Async context manager over the active page.

    Examples:
        >>> import inspect
        >>> inspect.isasyncgenfunction(logged_in_browser_page.__wrapped__)
        True
    """
    _ = profile_dir
    content_root = _content_root_from_env()
    session_id = os.environ.get("SEVN_SESSION_ID", "").strip()
    async with browser_page(
        content_root=content_root,
        session_id=session_id,
        cfg=None,
        headless_fallback=False,
    ) as page:
        yield page


async def fetch_page_snapshot(
    *,
    skill_id: str,
    url: str,
    workspace: Path,
    cfg: WorkspaceConfig | None,
    max_chars: int = 8000,
    dry_run: bool = False,
) -> dict[str, object]:
    """Navigate to ``url`` and return a compact text snapshot from the logged-in session.

    Args:
        skill_id (str): Bundled skill id.
        url (str): Validated target URL.
        workspace (Path): Workspace content root.
        cfg (WorkspaceConfig | None): Workspace config for profile resolution.
        max_chars (int): Maximum characters of extracted visible text.
        dry_run (bool): When ``True``, skip Playwright and return a plan payload.

    Returns:
        dict[str, object]: Snapshot metadata and optional ``text`` excerpt.

    Raises:
        RuntimeError: When Playwright is missing or navigation fails.

    Examples:
        >>> import asyncio, tempfile
        >>> ws = Path(tempfile.mkdtemp())
        >>> payload = asyncio.run(
        ...     fetch_page_snapshot(
        ...         skill_id="x-use",
        ...         url="https://x.com/home",
        ...         workspace=ws,
        ...         cfg=None,
        ...         dry_run=True,
        ...     )
        ... )
        >>> payload["mode"]
        'dry_run'
    """
    validated = validate_social_url(url, skill_id=skill_id)
    profile = resolve_browser_profile(workspace, skill_id=skill_id, cfg=cfg)
    if dry_run:
        return {
            "mode": "dry_run",
            "skill_id": skill_id,
            "url": validated,
            "profile_dir": str(profile),
            "max_chars": max_chars,
        }

    try:
        import playwright  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("playwright is not installed (uv sync --extra browser)") from exc

    async with logged_in_browser_page(profile_dir=profile) as page:
        await page.goto(validated, wait_until="load", timeout=60_000)
        with contextlib.suppress(Exception):
            await page.wait_for_load_state("networkidle", timeout=15_000)
        title = ""
        with contextlib.suppress(Exception):
            title = await page.title()
        try:
            text = (await page.locator("body").inner_text(timeout=20_000) or "").strip()
        except Exception as exc:
            raise RuntimeError(f"failed to extract page text: {exc}") from exc
        if len(text) > max_chars:
            text = text[:max_chars]
        return {
            "mode": "live",
            "skill_id": skill_id,
            "url": validated,
            "title": title,
            "text": text,
            "chars": len(text),
            "profile_dir": str(profile),
        }


__all__ = [
    "FACEBOOK_EGRESS_DOMAINS",
    "FACEBOOK_USE_SKILL_ID",
    "SKILL_EGRESS",
    "SOCIAL_BROWSER_SKILL_IDS",
    "X_EGRESS_DOMAINS",
    "X_USE_SKILL_ID",
    "cdp_reachable",
    "default_cdp_url",
    "dry_run_requested",
    "facebook_search_url",
    "fetch_page_snapshot",
    "host_allowed",
    "logged_in_browser_page",
    "merge_social_browser_proc_env",
    "resolve_browser_profile",
    "session_status_payload",
    "validate_social_url",
    "x_search_url",
]
