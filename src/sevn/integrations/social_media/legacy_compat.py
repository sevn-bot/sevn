"""Thin compatibility aliases for migrated operator ``x-use`` / ``social_browser`` scripts.

Module: sevn.integrations.social_media.legacy_compat
Depends: os, sys, pathlib, urllib.parse, sevn.browser.chrome, sevn.browser.recipes.social,
    sevn.skills.browser_session

Exports:
    dry_run_requested — CLI/env dry-run selector (bundled script parity).
    resolve_browser_profile — alias for :func:`sevn.browser.chrome.resolve_profile_dir`.
    validate_social_url — legacy egress validation for x-use / facebook-use scripts.
    merge_social_browser_proc_env — inject profile env for migrated social skill subprocesses.
    session_status_payload — legacy session_status JSON for social browser skills.
    host_allowed — suffix match against an egress allowlist.
    x_search_url — build an X search URL from a query string.
    facebook_search_url — build a Facebook search URL from a query string.
    logged_in_browser_page — legacy Playwright-era helper (raises with migration guidance).
    fetch_page_snapshot — legacy page snapshot helper (dry-run or migration error).
"""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import quote_plus, urlparse

from sevn.browser.chrome import cdp_reachable, resolve_profile_dir
from sevn.browser.recipes.social import FACEBOOK_EGRESS_DOMAINS, X_EGRESS_DOMAINS
from sevn.skills.browser_session import session_status_payload as _session_status_payload

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sevn.config.workspace_config import WorkspaceConfig

X_USE_SKILL_ID: Final[str] = "x-use"
FACEBOOK_USE_SKILL_ID: Final[str] = "facebook-use"
SOCIAL_BROWSER_SKILL_IDS: Final[frozenset[str]] = frozenset(
    {X_USE_SKILL_ID, FACEBOOK_USE_SKILL_ID},
)

SKILL_EGRESS: Final[dict[str, tuple[str, ...]]] = {
    X_USE_SKILL_ID: X_EGRESS_DOMAINS,
    FACEBOOK_USE_SKILL_ID: FACEBOOK_EGRESS_DOMAINS,
}

_DRY_RUN_ENV = "SEVN_SOCIAL_BROWSER_DRY_RUN"
_DEFAULT_PROFILE_NAME = "default"
_CONTENT_ROOT_ENV = "SEVN_CONTENT_ROOT"
_PROFILE_ENV = "SEVN_BROWSER_PROFILE_DIR"

__all__ = [
    "FACEBOOK_USE_SKILL_ID",
    "SKILL_EGRESS",
    "SOCIAL_BROWSER_SKILL_IDS",
    "X_USE_SKILL_ID",
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
    """
    normalized = host.lower().rstrip(".")
    if not normalized:
        return False
    return any(
        normalized == suffix.lower() or normalized.endswith(f".{suffix.lower()}")
        for suffix in allowlist
    )


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


def dry_run_requested(argv: list[str] | None = None) -> bool:
    """Return whether dry-run was requested via CLI flag or env.

    Args:
        argv (list[str] | None): CLI argv (defaults to ``sys.argv[1:]``).

    Returns:
        bool: ``True`` when dry-run is active.

    Examples:
        >>> dry_run_requested(["--dry-run"])
        True
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if "--dry-run" in args or "-n" in args:
        return True
    return os.environ.get(_DRY_RUN_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def resolve_browser_profile(
    content_root: Path,
    session_id: str = "default",
    *,
    cfg: object | None = None,
    skill_id: str | None = None,
    workspace: Path | None = None,
) -> Path:
    """Resolve persistent Chrome profile directory (legacy ``social_browser`` name).

    Accepts either ``content_root`` + ``session_id`` (new) or ``workspace`` + ``skill_id``
    (legacy operator scripts).

    Args:
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.
        cfg (object | None): Optional workspace config.
        skill_id (str | None): Legacy bundled skill id (ignored; profile is session-scoped).
        workspace (Path | None): Legacy alias for ``content_root``.

    Returns:
        Path: Absolute profile directory path.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> root = Path(tempfile.mkdtemp())
        >>> resolve_browser_profile(root).name
        'default'
    """
    _ = skill_id
    root = workspace if workspace is not None else content_root
    sid = os.environ.get("SEVN_SESSION_ID", "").strip() or session_id or _DEFAULT_PROFILE_NAME
    return resolve_profile_dir(root, sid, cfg=cfg)  # type: ignore[arg-type]


def merge_social_browser_proc_env(
    env: dict[str, str],
    *,
    skill_id: str,
    workspace: Path,
    cfg: WorkspaceConfig | None = None,
    content_root: Path | None = None,
) -> None:
    """Inject logged-in browser session env vars for social skill subprocesses (in-place).

    Args:
        env (dict[str, str]): Subprocess environment to mutate.
        skill_id (str): Canonical bundled skill id.
        workspace (Path): Workspace content root.
        cfg (WorkspaceConfig | None): Workspace config for profile resolution.
        content_root (Path | None): Alias for ``workspace``.

    Returns:
        None

    Examples:
        >>> env: dict[str, str] = {}
        >>> import tempfile
        >>> merge_social_browser_proc_env(
        ...     env, skill_id="x-use", workspace=Path(tempfile.mkdtemp()), cfg=None
        ... )
        >>> "SEVN_BROWSER_PROFILE_DIR" in env
        True
    """
    if skill_id not in SOCIAL_BROWSER_SKILL_IDS:
        return
    root = content_root if content_root is not None else workspace
    env[_CONTENT_ROOT_ENV] = str(root.expanduser().resolve())
    session_id = env.get("SEVN_SESSION_ID", "").strip() or _DEFAULT_PROFILE_NAME
    if session_id != _DEFAULT_PROFILE_NAME:
        env.setdefault("SEVN_SESSION_ID", session_id)
    if not env.get("SEVN_BROWSER_AUTOCLOSE", "").strip():
        env["SEVN_BROWSER_AUTOCLOSE"] = "0"
    profile = resolve_browser_profile(root, session_id, cfg=cfg, skill_id=skill_id)
    env.setdefault(_PROFILE_ENV, str(profile))


def session_status_payload(
    *,
    skill_id: str,
    workspace: Path,
    cfg: WorkspaceConfig | None = None,
    cdp_url: str | None = None,
    content_root: Path | None = None,
    session_id: str | None = None,
) -> dict[str, object]:
    """Build the ``session_status`` JSON payload for a social browser skill.

    Args:
        skill_id (str): Bundled skill id.
        workspace (Path): Workspace content root.
        cfg (WorkspaceConfig | None): Workspace config for profile resolution.
        cdp_url (str | None): Optional CDP override.
        content_root (Path | None): Alias for ``workspace``.
        session_id (str | None): Gateway session id override.

    Returns:
        dict[str, object]: Profile path, CDP reachability, and egress allowlist metadata.

    Examples:
        >>> import tempfile
        >>> payload = session_status_payload(
        ...     skill_id="x-use", workspace=Path(tempfile.mkdtemp()), cfg=None
        ... )
        >>> payload["skill_id"]
        'x-use'
    """
    root = content_root if content_root is not None else workspace
    sid = session_id or os.environ.get("SEVN_SESSION_ID", "").strip() or _DEFAULT_PROFILE_NAME
    base = _session_status_payload(
        content_root=root,
        session_id=sid,
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
    content_raw = os.environ.get(_CONTENT_ROOT_ENV, "").strip()
    if not content_raw:
        msg = "SEVN_CONTENT_ROOT is not set (gateway should inject it for skill runs)."
        raise RuntimeError(msg)
    return Path(content_raw).expanduser().resolve()


@asynccontextmanager
async def logged_in_browser_page(*, profile_dir: Path) -> AsyncIterator[Any]:
    """Legacy Playwright page helper — migrate to ``browser`` tool ``action=social``.

    Args:
        profile_dir (Path): Legacy parameter (ignored).

    Yields:
        Any: Never yields — raises with migration guidance.

    Returns:
        AsyncIterator[Any]: Async context manager (always raises).

    Raises:
        RuntimeError: Always — Playwright social_browser stack was removed.

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> async def _probe() -> bool:
        ...     try:
        ...         async with logged_in_browser_page(profile_dir=Path("/tmp/p")):
        ...             pass
        ...     except RuntimeError as exc:
        ...         return "Playwright" in str(exc)
        ...     return False
        >>> asyncio.run(_probe())
        True
    """
    _ = profile_dir
    msg = (
        "logged_in_browser_page removed with Playwright — use social_media_manager + "
        "browser tool action=social (see bundled skill migration docs)."
    )
    raise RuntimeError(msg)
    yield  # pragma: no cover — unreachable; satisfies async context manager protocol


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

    Live mode requires Playwright (removed). Dry-run returns a plan payload for migration.

    Args:
        skill_id (str): Bundled skill id.
        url (str): Target URL.
        workspace (Path): Workspace content root.
        cfg (WorkspaceConfig | None): Workspace config for profile resolution.
        max_chars (int): Maximum characters of extracted visible text.
        dry_run (bool): When ``True``, skip live navigation and return a plan payload.

    Returns:
        dict[str, object]: Snapshot metadata (dry-run) or raises for live mode.

    Raises:
        RuntimeError: When live mode is requested without Playwright migration path.

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
    _ = _content_root_from_env()
    msg = (
        "fetch_page_snapshot live mode removed with Playwright — use browser tool "
        "action=social or pass dry_run=True while migrating operator scripts."
    )
    raise RuntimeError(msg)
