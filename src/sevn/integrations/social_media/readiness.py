"""Shared readiness probes for ``social_media_manager`` (W4 / D10).

Module: sevn.integrations.social_media.readiness
Depends: sevn.browser.recipes.social, sevn.integrations.twexapi.config, sevn.skills.browser_session

Exports:
    twexapi_key_configured — boolean TwexAPI key presence (no secret values).
    format_browser_session_hint — one-line CDP/profile caption for Telegram.
    site_login_probe — cheap per-site login hint without headless login in CI.
    platform_readiness_fields — per-platform readiness slice for capabilities matrix.
    build_social_media_readiness — async TwexAPI + browser (+ optional site) snapshot.
    build_social_media_readiness_sync — sync readiness snapshot for worker matrix.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sevn.browser.recipes.social import _SITE_CONFIG, _SUPPORTED_SITES
from sevn.integrations.social_media.medium import allowed_media_for_site
from sevn.integrations.twexapi.config import (
    TWEXAPI_ENV_KEYS,
    TWEXAPI_SECRET_ALIAS,
    TwexApiSettings,
    load_twexapi_settings,
)
from sevn.skills.browser_session import (
    cdp_reachable,
    default_cdp_url,
    resolve_profile_dir,
)

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig

__all__ = [
    "build_social_media_readiness",
    "build_social_media_readiness_sync",
    "format_browser_session_hint",
    "platform_readiness_fields",
    "site_login_probe",
    "twexapi_key_configured",
]

_CHROME_COOKIE_PATHS: tuple[str, ...] = ("Default/Cookies", "Default/Network/Cookies")


def twexapi_key_configured(settings: TwexApiSettings) -> bool:
    """Return whether a TwexAPI key ref or env escape hatch is present.

    Never resolves or returns secret plaintext.

    Args:
        settings (TwexApiSettings): Parsed TwexAPI block.

    Returns:
        bool: ``True`` when an api_key ref or known env var is set.

    Examples:
        >>> twexapi_key_configured(TwexApiSettings(api_key_ref="${SECRET:SEVN_SECRET_TWEXAPI}"))
        True
    """
    if isinstance(settings.api_key_ref, str) and settings.api_key_ref.strip():
        return True
    return any(os.environ.get(name, "").strip() for name in TWEXAPI_ENV_KEYS)


def _twexapi_readiness_block(settings: TwexApiSettings) -> dict[str, Any]:
    """Build TwexAPI readiness fields without secret values.

    Args:
        settings (TwexApiSettings): Parsed TwexAPI settings.

    Returns:
        dict[str, Any]: TwexAPI readiness metadata.

    Examples:
        >>> block = _twexapi_readiness_block(TwexApiSettings())
        >>> block["api_key_configured"]
        False
    """
    env_present = any(os.environ.get(name, "").strip() for name in TWEXAPI_ENV_KEYS)
    return {
        "docs": settings.docs_url,
        "base_url": settings.base_url,
        "enabled": settings.enabled,
        "api_key_configured": twexapi_key_configured(settings),
        "api_key_ref_configured": bool(settings.api_key_ref),
        "env_key_present": env_present,
        "secret_alias": TWEXAPI_SECRET_ALIAS,
    }


def _resolve_browser_profile_dir(content_root: Path, cfg: WorkspaceConfig | None) -> Path:
    """Resolve the browser profile directory for social media workflows.

    Args:
        content_root (Path): Workspace content root.
        cfg (WorkspaceConfig | None): Parsed workspace config.

    Returns:
        Path: Absolute profile directory path.

    Examples:
        >>> import tempfile
        >>> root = Path(tempfile.mkdtemp())
        >>> _resolve_browser_profile_dir(root, None).name
        'default'
    """
    return resolve_profile_dir(content_root, "default", cfg=cfg)


def _chrome_cookies_db_exists(profile_dir: Path) -> bool:
    """Return whether a Chrome cookie store exists under ``profile_dir``.

    Args:
        profile_dir (Path): Browser profile directory.

    Returns:
        bool: ``True`` when a known cookie DB path exists.

    Examples:
        >>> _chrome_cookies_db_exists(Path("/nonexistent"))
        False
    """
    return any((profile_dir / rel).is_file() for rel in _CHROME_COOKIE_PATHS)


def _login_site_for_platform(site: str) -> str:
    """Map a social platform site key to an auth ``login_state`` site key.

    Args:
        site (str): Canonical platform site key.

    Returns:
        str: Auth site key (``x``, ``linkedin``, or ``generic``).

    Examples:
        >>> _login_site_for_platform("x")
        'x'
        >>> _login_site_for_platform("facebook")
        'generic'
    """
    cfg = _SITE_CONFIG.get(site)
    return cfg.login_site if cfg is not None else "generic"


def site_login_probe(
    site: str,
    *,
    profile_dir: Path,
    cdp_reachable_flag: bool,
) -> dict[str, Any]:
    """Cheap per-site login hint without spawning headless login in CI.

    Live ``login_state`` requires an attached CDP page; this probe only inspects
    profile/cookie presence and surfaces operator hints.

    Args:
        site (str): Canonical platform site key.
        profile_dir (Path): Resolved browser profile directory.
        cdp_reachable_flag (bool): Whether CDP responded to a reachability probe.

    Returns:
        dict[str, Any]: Site login probe metadata.

    Raises:
        ValueError: When ``site`` is not in the SSOT set.

    Examples:
        >>> import tempfile
        >>> probe = site_login_probe("x", profile_dir=Path(tempfile.mkdtemp()), cdp_reachable_flag=False)
        >>> probe["site"]
        'x'
    """
    normalized = site.strip().lower()
    if normalized not in _SUPPORTED_SITES:
        msg = f"unsupported site: {site!r}"
        raise ValueError(msg)
    login_site = _login_site_for_platform(normalized)
    has_profile = profile_dir.is_dir()
    has_cookies = _chrome_cookies_db_exists(profile_dir) if has_profile else False
    if has_cookies and cdp_reachable_flag:
        state = "probe_via_cdp"
        hint = f"Profile seeded; use browser action=login_state site={login_site}"
    elif has_cookies:
        state = "profile_seeded"
        hint = "Cookie store present; attach CDP for live login_state"
    elif has_profile:
        state = "profile_empty"
        hint = "Profile dir exists but no cookie store yet"
    else:
        state = "not_configured"
        hint = "Set SEVN_CDP_URL or seed browser profile cookies"
    return {
        "site": normalized,
        "login_site": login_site,
        "state": state,
        "hint": hint,
        "profile_exists": has_profile,
        "cookies_db_present": has_cookies,
    }


def _browser_readiness_block_sync(
    content_root: Path,
    cfg: WorkspaceConfig | None,
) -> dict[str, Any]:
    """Build browser/CDP readiness fields (sync — for worker capabilities matrix).

    Args:
        content_root (Path): Workspace content root.
        cfg (WorkspaceConfig | None): Parsed workspace config.

    Returns:
        dict[str, Any]: Browser readiness metadata.

    Examples:
        >>> import tempfile
        >>> block = _browser_readiness_block_sync(Path(tempfile.mkdtemp()), None)
        >>> block["engine"]
        'cdp'
    """
    profile = _resolve_browser_profile_dir(content_root, cfg)
    operator_cdp = default_cdp_url()
    reachable = cdp_reachable(operator_cdp) if operator_cdp else False
    return {
        "engine": "cdp",
        "cdp_url": operator_cdp,
        "cdp_url_configured": operator_cdp is not None,
        "profile_dir": str(profile),
        "profile_exists": profile.is_dir(),
        "cdp_reachable": reachable,
        "tool": "browser",
    }


async def _browser_readiness_block(
    content_root: Path,
    cfg: WorkspaceConfig | None,
) -> dict[str, Any]:
    """Build browser/CDP readiness fields (async wrapper for skill scripts).

    Args:
        content_root (Path): Workspace content root.
        cfg (WorkspaceConfig | None): Parsed workspace config.

    Returns:
        dict[str, Any]: Browser readiness metadata.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_browser_readiness_block)
        True
    """
    return await asyncio.to_thread(_browser_readiness_block_sync, content_root, cfg)


def format_browser_session_hint(
    cfg: WorkspaceConfig | None,
    content_root: Path | None,
) -> str:
    """Return a CDP URL or profile-dir hint for operator captions (no secrets).

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace config.
        content_root (Path | None): Workspace content root for default profile path.

    Returns:
        str: One-line browser session hint.

    Examples:
        >>> format_browser_session_hint(None, None).lower().startswith("browser")
        True
    """
    cdp = os.environ.get("SEVN_CDP_URL", "").strip()
    if cdp:
        return f"CDP: {cdp}"
    profile_env = os.environ.get("SEVN_BROWSER_PROFILE_DIR", "").strip()
    if profile_env:
        return f"Browser profile: {profile_env}"
    if cfg is not None and isinstance(cfg.skills, dict):
        for block_key in ("social_browser", "browser"):
            block = cfg.skills.get(block_key)
            if isinstance(block, dict):
                raw = block.get("profile_dir")
                if isinstance(raw, str) and raw.strip():
                    return f"Browser profile: {raw.strip()}"
    if content_root is not None:
        default_profile = content_root / ".sevn" / "browser-profiles" / "default"
        return f"Browser profile: {default_profile}"
    return "Browser: configure CDP (SEVN_CDP_URL) or profile dir"


def build_social_media_readiness_sync(
    content_root: Path,
    *,
    cfg: WorkspaceConfig | None = None,
    site: str | None = None,
) -> dict[str, Any]:
    """Sync readiness snapshot for worker capabilities matrix.

    Args:
        content_root (Path): Workspace content root.
        cfg (WorkspaceConfig | None): Optional preloaded workspace config.
        site (str | None): When set, include a per-site login probe block.

    Returns:
        dict[str, Any]: Readiness payload with ``twexapi`` and ``browser`` keys.

    Examples:
        >>> import tempfile
        >>> snap = build_social_media_readiness_sync(Path(tempfile.mkdtemp()))
        >>> "twexapi" in snap and "browser" in snap
        True
    """
    settings, loaded_cfg = load_twexapi_settings(content_root)
    workspace_cfg = cfg if cfg is not None else loaded_cfg
    browser = _browser_readiness_block_sync(content_root, workspace_cfg)
    payload: dict[str, Any] = {
        "specialist": "social_media_manager",
        "twexapi": _twexapi_readiness_block(settings),
        "browser": browser,
    }
    if site:
        payload["site"] = site_login_probe(
            site,
            profile_dir=Path(str(browser["profile_dir"])),
            cdp_reachable_flag=bool(browser["cdp_reachable"]),
        )
    return payload


async def build_social_media_readiness(
    content_root: Path,
    *,
    cfg: WorkspaceConfig | None = None,
    site: str | None = None,
) -> dict[str, Any]:
    """Build TwexAPI + browser readiness snapshot (optional per-site login probe).

    Args:
        content_root (Path): Workspace content root.
        cfg (WorkspaceConfig | None): Optional preloaded workspace config.
        site (str | None): When set, include a per-site login probe block.

    Returns:
        dict[str, Any]: Readiness payload with ``twexapi`` and ``browser`` keys.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(build_social_media_readiness)
        True
    """
    return await asyncio.to_thread(
        build_social_media_readiness_sync,
        content_root,
        cfg=cfg,
        site=site,
    )


def platform_readiness_fields(
    site: str,
    *,
    settings: TwexApiSettings,
    browser: dict[str, Any],
    profile_dir: Path,
    cdp_reachable_flag: bool,
) -> dict[str, Any]:
    """Build per-platform readiness fields for the capabilities matrix.

    Args:
        site (str): Canonical platform site key.
        settings (TwexApiSettings): Parsed TwexAPI settings.
        browser (dict[str, Any]): Browser readiness block.
        profile_dir (Path): Resolved browser profile directory.
        cdp_reachable_flag (bool): CDP reachability flag.

    Returns:
        dict[str, Any]: Platform readiness slice aligned with session_status.

    Examples:
        >>> fields = platform_readiness_fields(
        ...     "x",
        ...     settings=TwexApiSettings(),
        ...     browser={"profile_exists": False, "cdp_url_configured": False, "cdp_reachable": False},
        ...     profile_dir=Path("/tmp/p"),
        ...     cdp_reachable_flag=False,
        ... )
        >>> fields["twexapi_available"]
        True
    """
    allowed = allowed_media_for_site(site)
    login = site_login_probe(
        site,
        profile_dir=profile_dir,
        cdp_reachable_flag=cdp_reachable_flag,
    )
    return {
        "twexapi_enabled": settings.enabled,
        "twexapi_available": site == "x" and "twexapi" in allowed,
        "twexapi_key_configured": twexapi_key_configured(settings),
        "browser_profile_exists": bool(browser.get("profile_exists")),
        "cdp_url_configured": bool(browser.get("cdp_url_configured")),
        "cdp_reachable": cdp_reachable_flag,
        "login": login,
    }
