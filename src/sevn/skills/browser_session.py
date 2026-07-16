"""Session-scoped browser lifecycle — profile, CDP, registry, spawn/attach/close.

Module: sevn.skills.browser_session
Depends: asyncio, hashlib, json, os, pathlib, subprocess, urllib

Exports:
    BrowserSessionRegistry — persisted registry row for one gateway session.
    CloseBrowserResult — outcome of :func:`close_browser_session`.
    browser_autoclose_enabled — read ``SEVN_BROWSER_AUTOCLOSE`` (default keep-alive).
    persist_active_target_id — update registry ``active_target_id`` for a session.
    cdp_list_page_targets — fetch Chrome DevTools page targets from ``/json/list``.
    cdp_port_from_url — parse TCP port from a CDP base URL.
    cdp_port_seed — deterministic seed port hint from ``session_id`` (D2).
    cdp_reachable — probe ``/json/version`` on a CDP endpoint.
    clear_registry — remove the registry file for a session.
    close_all_gateway_browsers — close sevn-spawned browsers for gateway session rows.
    close_browser_session — kill sevn-spawned browser or skip external CDP.
    close_idle_browser_sessions — close stale sevn-spawned browsers by ``last_used_at``.
    default_cdp_url — read ``SEVN_CDP_URL`` when set.
    merge_browser_proc_env — inject content root, profile, CDP env for skill runs.
    read_devtools_active_port — read Chrome ``DevToolsActivePort`` (optional freshness gate).
    read_registry — load registry JSON for a session.
    registry_path — path to ``.sevn/browser-sessions/<session_id>.json``.
    resolve_browser_engine — read ``skills.browser.engine`` / ``SEVN_BROWSER_ENGINE``.
    resolve_browser_extra_args — parse ``SEVN_BROWSER_EXTRA_ARGS`` spawn flags.
    is_brave_executable — detect Brave from a resolved binary path.
    browser_readiness_snapshot — doctor/CLI browser readiness probe.
    BrowserReadiness — dataclass returned by :func:`browser_readiness_snapshot`.
    resolve_profile_dir — session-scoped persistent profile directory.
    resolve_browser_headless — headed default on host unless config/binary absent (D13).
    resolve_idle_close_seconds — read ``skills.browser.idle_close_seconds`` (D8).
    resolve_cdp_url — operator CDP override, else registry, else seed hint URL.
    resolve_chrome_executable — locate Chrome, Chromium, or Brave binary.
    restart_browser_session — close then spawn and wait for CDP.
    session_status_payload — unified JSON status dict for lifecycle scripts.
    spawn_chrome — detached Chrome with login-grade defaults + ``--remote-debugging-port=0``.
    write_registry — atomic JSON write for a session registry row.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess  # nosec B404
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlparse

from sevn.config.workspace_config import WorkspaceConfig

BROWSER_SKILL_IDS: Final[frozenset[str]] = frozenset({"browser-harness"})
EXTERNAL_CDP: Final[str] = "EXTERNAL_CDP"
_DEFAULT_SESSION_ID: Final[str] = "default"
_PROFILE_ENV: Final[str] = "SEVN_BROWSER_PROFILE_DIR"
_CONTENT_ROOT_ENV: Final[str] = "SEVN_CONTENT_ROOT"
_SESSION_ID_ENV: Final[str] = "SEVN_SESSION_ID"
# Login-grade defaults (DB1): re-passed on every spawn; cookies live in the profile.
_LOGIN_GRADE_CHROME_ARGS: Final[tuple[str, ...]] = (
    "--remote-allow-origins=*",
    "--no-service-autorun",
    "--homepage=about:blank",
    "--no-pings",
    "--password-store=basic",
    "--disable-infobars",
    "--disable-breakpad",
    "--disable-dev-shm-usage",
    "--disable-session-crashed-bubble",
    "--disable-search-engine-choice-screen",
    "--disable-features=IsolateOrigins,site-per-process",
    "--disable-blink-features=AutomationControlled",
)
_PROFILE_BROWSER_LOCK_NAMES: Final[tuple[str, ...]] = (
    "DevToolsActivePort",
    "SingletonLock",
    "SingletonCookie",
    "SingletonSocket",
)


@dataclass(frozen=True)
class BrowserSessionRegistry:
    """Persisted browser session metadata under ``.sevn/browser-sessions/`` (D3)."""

    pid: int | None
    cdp_url: str
    cdp_port: int
    profile_dir: str
    headless: bool
    spawned_by_sevn: bool
    last_used_at: str
    active_target_id: str | None = None
    headless_persistent: bool = False


@dataclass(frozen=True)
class CloseBrowserResult:
    """Outcome of :func:`close_browser_session`."""

    ok: bool
    code: str
    message: str


def _normalise_session_id(session_id: str | None) -> str:
    """Return a filesystem-safe session id segment (D1 fallback ``default``).

    Args:
        session_id (str | None): Gateway session id or ``None``.

    Returns:
        str: Non-empty session key.

    Examples:
        >>> _normalise_session_id("")
        'default'
        >>> _normalise_session_id("web:abc")
        'web:abc'
    """
    text = (session_id or "").strip()
    return text or _DEFAULT_SESSION_ID


def _registry_dir(content_root: Path) -> Path:
    """Return ``<content_root>/.sevn/browser-sessions`` directory path.

    Args:
        content_root (Path): Workspace content root.

    Returns:
        Path: Registry directory (may not exist yet).

    Examples:
        >>> import tempfile
        >>> d = _registry_dir(Path(tempfile.mkdtemp()))
        >>> d.name
        'browser-sessions'
    """
    return content_root / ".sevn" / "browser-sessions"


def registry_path(content_root: Path, session_id: str) -> Path:
    """Return the registry JSON path for ``session_id``.

    Args:
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.

    Returns:
        Path: ``.sevn/browser-sessions/<session_id>.json``.

    Examples:
        >>> import tempfile
        >>> p = registry_path(Path(tempfile.mkdtemp()), "s1")
        >>> p.suffix
        '.json'
    """
    sid = _normalise_session_id(session_id)
    return _registry_dir(content_root) / f"{sid}.json"


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    """Write JSON via temp file + ``os.replace``.

    Args:
        path (Path): Destination file path.
        payload (dict[str, object]): Serializable registry payload.

    Returns:
        None

    Examples:
        >>> import tempfile
        >>> p = Path(tempfile.mkdtemp()) / "reg.json"
        >>> _atomic_write_json(p, {"cdp_url": "http://127.0.0.1:9222"})
        >>> json.loads(p.read_text(encoding="utf-8"))["cdp_url"]
        'http://127.0.0.1:9222'
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=".browser-session-",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp_name, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def _registry_from_dict(data: dict[str, object]) -> BrowserSessionRegistry:
    """Coerce a decoded JSON dict into :class:`BrowserSessionRegistry`.

    Args:
        data (dict[str, object]): Raw registry JSON object.

    Returns:
        BrowserSessionRegistry: Parsed row.

    Examples:
        >>> row = _registry_from_dict({"cdp_url": "http://127.0.0.1:1", "cdp_port": 1,
        ...     "profile_dir": "/p", "headless": False, "spawned_by_sevn": True,
        ...     "last_used_at": "2026-01-01T00:00:00+00:00"})
        >>> row.cdp_port
        1
    """
    pid_raw = data.get("pid")
    pid = int(pid_raw) if isinstance(pid_raw, int) else None
    port_raw = data.get("cdp_port", 0)
    cdp_port = int(port_raw) if isinstance(port_raw, int) else 0
    active = data.get("active_target_id")
    active_target_id = active if isinstance(active, str) and active.strip() else None
    return BrowserSessionRegistry(
        pid=pid,
        cdp_url=str(data.get("cdp_url", "")),
        cdp_port=cdp_port,
        profile_dir=str(data.get("profile_dir", "")),
        headless=bool(data.get("headless", False)),
        spawned_by_sevn=bool(data.get("spawned_by_sevn", False)),
        last_used_at=str(data.get("last_used_at", "")),
        active_target_id=active_target_id,
        headless_persistent=bool(data.get("headless_persistent", False)),
    )


def read_registry(content_root: Path, session_id: str) -> BrowserSessionRegistry | None:
    """Load registry JSON for ``session_id`` when present.

    Args:
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.

    Returns:
        BrowserSessionRegistry | None: Parsed row or ``None`` when missing.

    Examples:
        >>> import tempfile
        >>> root = Path(tempfile.mkdtemp())
        >>> read_registry(root, "missing") is None
        True
    """
    path = registry_path(content_root, session_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return _registry_from_dict(data)


def write_registry(content_root: Path, session_id: str, row: BrowserSessionRegistry) -> None:
    """Atomically persist registry JSON for ``session_id``.

    Args:
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.
        row (BrowserSessionRegistry): Registry payload.

    Returns:
        None

    Examples:
        >>> import tempfile
        >>> from datetime import UTC, datetime
        >>> root = Path(tempfile.mkdtemp())
        >>> row = BrowserSessionRegistry(
        ...     pid=1, cdp_url="http://127.0.0.1:9333", cdp_port=9333,
        ...     profile_dir="/tmp/p", headless=False, spawned_by_sevn=True,
        ...     last_used_at=datetime.now(tz=UTC).isoformat(),
        ... )
        >>> write_registry(root, "s1", row)
        >>> read_registry(root, "s1") is not None
        True
    """
    path = registry_path(content_root, session_id)
    payload: dict[str, object] = dict(asdict(row))
    _atomic_write_json(path, payload)


def clear_registry(content_root: Path, session_id: str) -> None:
    """Remove the registry file for ``session_id`` when it exists.

    Args:
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.

    Returns:
        None

    Examples:
        >>> import tempfile
        >>> from datetime import UTC, datetime
        >>> root = Path(tempfile.mkdtemp())
        >>> row = BrowserSessionRegistry(
        ...     pid=None, cdp_url="", cdp_port=0, profile_dir="/p",
        ...     headless=False, spawned_by_sevn=False,
        ...     last_used_at=datetime.now(tz=UTC).isoformat(),
        ... )
        >>> write_registry(root, "s1", row)
        >>> clear_registry(root, "s1")
        >>> read_registry(root, "s1") is None
        True
    """
    path = registry_path(content_root, session_id)
    with contextlib.suppress(OSError):
        path.unlink()


def _read_profile_from_cfg(cfg: WorkspaceConfig | None, key: str) -> Path | None:
    """Read ``skills.<key>.profile_dir`` when configured.

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace config.
        key (str): Skills subtree key (for example ``browser``).

    Returns:
        Path | None: Configured profile path or ``None``.

    Examples:
        >>> _read_profile_from_cfg(None, "browser") is None
        True
    """
    if cfg is None or not isinstance(cfg.skills, dict):
        return None
    block = cfg.skills.get(key)
    if isinstance(block, dict):
        raw = block.get("profile_dir")
        if isinstance(raw, str) and raw.strip():
            return Path(raw.strip()).expanduser()
    return None


def resolve_profile_dir(
    content_root: Path,
    session_id: str,
    cfg: WorkspaceConfig | None = None,
) -> Path:
    """Resolve the persistent Chrome profile directory for a gateway session (D1).

    Precedence: ``SEVN_BROWSER_PROFILE_DIR`` → ``skills.browser.profile_dir`` →
    ``<content_root>/.sevn/browser-profiles/<session_id|default>``.

    Args:
        content_root (Path): Workspace content root (not shadow workspace).
        session_id (str): Gateway session id.
        cfg (WorkspaceConfig | None): Optional workspace config overrides.

    Returns:
        Path: Absolute profile directory (may not exist yet).

    Examples:
        >>> import tempfile
        >>> root = Path(tempfile.mkdtemp())
        >>> resolve_profile_dir(root, "conv-1").name
        'conv-1'
    """
    env_raw = os.environ.get(_PROFILE_ENV, "").strip()
    if env_raw:
        return Path(env_raw).expanduser().resolve()
    from_cfg = _read_profile_from_cfg(cfg, "browser")
    if from_cfg is not None:
        return from_cfg.expanduser().resolve()
    sid = _normalise_session_id(session_id)
    return (content_root / ".sevn" / "browser-profiles" / sid).resolve()


def cdp_port_seed(session_id: str) -> int:
    """Return a deterministic CDP port seed hint from ``session_id`` (D2).

    Args:
        session_id (str): Gateway session id.

    Returns:
        int: Port in ``9300..9399`` range.

    Examples:
        >>> cdp_port_seed("session-a") == cdp_port_seed("session-a")
        True
        >>> 9300 <= cdp_port_seed("session-a") <= 9399
        True
    """
    sid = _normalise_session_id(session_id)
    digest = hashlib.sha256(sid.encode()).hexdigest()
    return 9300 + (int(digest[:4], 16) % 100)


def default_cdp_url() -> str | None:
    """Return operator ``SEVN_CDP_URL`` when set (D6 attach-only override).

    Returns:
        str | None: Normalised CDP base URL or ``None`` when unset.

    Examples:
        >>> default_cdp_url() is None or default_cdp_url().startswith("http")
        True
    """
    raw = os.environ.get("SEVN_CDP_URL", "").strip()
    return raw.rstrip("/") if raw else None


def cdp_port_from_url(url: str) -> int:
    """Parse the TCP port embedded in a CDP URL.

    Args:
        url (str): CDP base URL.

    Returns:
        int: Explicit port or default ``9222``.

    Examples:
        >>> cdp_port_from_url("http://127.0.0.1:9333")
        9333
    """
    parsed = urlparse(url)
    if parsed.port is not None:
        return parsed.port
    return 9222


def resolve_cdp_url(
    content_root: Path,
    session_id: str,
    cfg: WorkspaceConfig | None = None,
) -> str:
    """Resolve the effective CDP URL for a session (D2/D6).

    Operator ``SEVN_CDP_URL`` wins. Otherwise use the registry ``cdp_url`` when
    present. When neither applies, return a seed-hint URL for legacy attach attempts.

    Args:
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.
        cfg (WorkspaceConfig | None): Unused today; reserved for future config keys.

    Returns:
        str: CDP base URL (may not be reachable until spawn completes).

    Examples:
        >>> import tempfile
        >>> root = Path(tempfile.mkdtemp())
        >>> url = resolve_cdp_url(root, "sess-1")
        >>> url.startswith("http://127.0.0.1:")
        True
    """
    _ = cfg
    operator = default_cdp_url()
    if operator:
        return operator
    row = read_registry(content_root, session_id)
    if row is not None and row.cdp_url.strip():
        return row.cdp_url.rstrip("/")
    port = cdp_port_seed(session_id)
    return f"http://127.0.0.1:{port}"


def cdp_reachable(url: str, *, timeout: float = 2.0) -> bool:
    """Return whether the CDP HTTP endpoint responds.

    Args:
        url (str): CDP base URL.
        timeout (float): Probe timeout in seconds.

    Returns:
        bool: ``True`` when ``/json/version`` returns HTTP 200.

    Examples:
        >>> cdp_reachable("http://127.0.0.1:1")
        False
    """
    try:
        ver = f"{url.rstrip('/')}/json/version"
        with urllib.request.urlopen(ver, timeout=timeout) as response:  # nosec B310
            return int(response.getcode()) == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def cdp_list_page_targets(cdp_url: str, *, timeout: float = 2.0) -> list[dict[str, Any]]:
    """Return page-type targets from the CDP HTTP ``/json/list`` endpoint.

    Args:
        cdp_url (str): CDP base URL (for example ``http://127.0.0.1:9222``).
        timeout (float): HTTP timeout in seconds.

    Returns:
        list[dict[str, Any]]: Rows with at least ``id``, ``url``, and ``title`` when present.

    Examples:
        >>> cdp_list_page_targets("http://127.0.0.1:1")
        []
    """
    listing_url = f"{cdp_url.rstrip('/')}/json/list"
    try:
        with urllib.request.urlopen(listing_url, timeout=timeout) as response:  # nosec B310
            raw = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, ValueError, UnicodeDecodeError):
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict) or item.get("type") != "page":
            continue
        target_id = item.get("id")
        if not isinstance(target_id, str) or not target_id.strip():
            continue
        rows.append(
            {
                "id": target_id.strip(),
                "url": str(item.get("url") or ""),
                "title": str(item.get("title") or ""),
            },
        )
    return rows


def _normalize_page_url(url: str) -> str:
    """Normalize a page URL for CDP target matching.

    Args:
        url (str): Raw page or CDP target URL.

    Returns:
        str: Lowercase URL without trailing slash (except root).

    Examples:
        >>> _normalize_page_url("https://Example.com/path/")
        'https://example.com/path'
    """
    text = (url or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if not parsed.scheme:
        return text.rstrip("/").lower()
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    normalized = f"{parsed.scheme}://{parsed.netloc.lower()}{path}"
    if parsed.query:
        normalized = f"{normalized}?{parsed.query}"
    return normalized


def _match_cdp_target_for_page(
    page: Any,
    targets: list[dict[str, Any]],
    *,
    title: str = "",
) -> str | None:
    """Match a Playwright page to a CDP ``/json/list`` page target id.

    Args:
        page (Any): Playwright ``Page``.
        targets (list[dict[str, Any]]): Rows from :func:`cdp_list_page_targets`.
        title (str): Optional page title already fetched by the caller.

    Returns:
        str | None: CDP target id when matched.

    Examples:
        >>> class _P:
        ...     url = "https://example.com/"
        >>> _match_cdp_target_for_page(_P(), [{"id": "T1", "url": "https://example.com/", "title": ""}])
        'T1'
    """
    page_url = _normalize_page_url(getattr(page, "url", "") or "")
    page_title = (title or "").strip()
    if page_url:
        exact = [
            row for row in targets if _normalize_page_url(str(row.get("url") or "")) == page_url
        ]
        if len(exact) == 1:
            return str(exact[0]["id"])
        if page_title:
            titled = [row for row in exact if str(row.get("title") or "").strip() == page_title]
            if len(titled) == 1:
                return str(titled[0]["id"])
            if len(titled) > 1:
                return str(titled[0]["id"])
        if len(exact) > 1:
            return str(exact[0]["id"])
    if page_title:
        titled_only = [row for row in targets if str(row.get("title") or "").strip() == page_title]
        if len(titled_only) == 1:
            return str(titled_only[0]["id"])
    return None


_BROWSER_ENGINE_VALUES: Final[frozenset[str]] = frozenset({"auto", "chrome", "chromium", "brave"})
_CHROME_PATH_NAMES: Final[tuple[str, ...]] = ("google-chrome-stable", "google-chrome", "chrome")
_CHROMIUM_PATH_NAMES: Final[tuple[str, ...]] = ("chromium", "chromium-browser")
_BRAVE_PATH_NAMES: Final[tuple[str, ...]] = ("brave-browser", "brave")


def resolve_browser_engine(cfg: WorkspaceConfig | None = None) -> str:
    """Return configured browser engine preference (``skills.browser.engine`` or env).

    Args:
        cfg (WorkspaceConfig | None): Workspace config.

    Returns:
        str: One of ``auto``, ``chrome``, ``chromium``, ``brave``.

    Examples:
        >>> resolve_browser_engine(None)
        'auto'
    """
    env = (os.environ.get("SEVN_BROWSER_ENGINE") or "").strip().lower()
    if env in _BROWSER_ENGINE_VALUES:
        return env
    if cfg is not None and isinstance(cfg.skills, dict):
        block = cfg.skills.get("browser")
        if isinstance(block, dict):
            raw = block.get("engine")
            if isinstance(raw, str):
                engine = raw.strip().lower()
                if engine in _BROWSER_ENGINE_VALUES:
                    return engine
    return "auto"


def _first_existing_file(candidates: tuple[str, ...]) -> str | None:
    """Return the first path in ``candidates`` that exists as a regular file.

    Args:
        candidates (tuple[str, ...]): Absolute or relative executable paths.

    Returns:
        str | None: First existing file path.

    Examples:
        >>> _first_existing_file(()) is None
        True
    """
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    return None


def _first_on_path(names: tuple[str, ...]) -> str | None:
    """Return the first name in ``names`` found on ``PATH`` via :func:`shutil.which`.

    Args:
        names (tuple[str, ...]): Binary names to probe.

    Returns:
        str | None: Resolved executable path when found.

    Examples:
        >>> _first_on_path(("definitely-not-a-real-binary-name-xyz",)) is None
        True
    """
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def _chrome_app_candidates() -> tuple[str, ...]:
    """Platform-specific Google Chrome install paths (not Chromium-only).

    Returns:
        tuple[str, ...]: Candidate paths for the current platform.

    Examples:
        >>> isinstance(_chrome_app_candidates(), tuple)
        True
    """
    if sys.platform == "darwin":
        return (
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        )
    if sys.platform == "win32":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")  # noqa: SIM112
        pfx86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")  # noqa: SIM112
        return (
            str(Path(pf) / "Google" / "Chrome" / "Application" / "chrome.exe"),
            str(Path(pfx86) / "Google" / "Chrome" / "Application" / "chrome.exe"),
        )
    return ()


def _chromium_app_candidates() -> tuple[str, ...]:
    """Platform-specific Chromium-only install paths.

    Returns:
        tuple[str, ...]: Candidate paths for the current platform.

    Examples:
        >>> isinstance(_chromium_app_candidates(), tuple)
        True
    """
    if sys.platform == "darwin":
        return ("/Applications/Chromium.app/Contents/MacOS/Chromium",)
    return ()


def _brave_app_candidates() -> tuple[str, ...]:
    """Platform-specific Brave install paths.

    Returns:
        tuple[str, ...]: Candidate paths for the current platform.

    Examples:
        >>> isinstance(_brave_app_candidates(), tuple)
        True
    """
    if sys.platform == "darwin":
        return ("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",)
    if sys.platform == "win32":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")  # noqa: SIM112
        pfx86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")  # noqa: SIM112
        return (
            str(Path(pf) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe"),
            str(Path(pfx86) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe"),
        )
    return ()


def _resolve_chrome_family(engine: str) -> str | None:
    """Resolve a binary for ``engine`` (``auto``, ``chrome``, ``chromium``, ``brave``).

    Args:
        engine (str): Browser engine preference.

    Returns:
        str | None: Executable path when found.

    Examples:
        >>> _resolve_chrome_family("brave") is None or True
        True
    """
    if engine == "chrome":
        return _first_existing_file(_chrome_app_candidates()) or _first_on_path(_CHROME_PATH_NAMES)
    if engine == "chromium":
        return _first_existing_file(_chromium_app_candidates()) or _first_on_path(
            _CHROMIUM_PATH_NAMES
        )
    if engine == "brave":
        return _first_existing_file(_brave_app_candidates()) or _first_on_path(_BRAVE_PATH_NAMES)
    chrome = _first_existing_file(_chrome_app_candidates()) or _first_on_path(
        _CHROME_PATH_NAMES + _CHROMIUM_PATH_NAMES,
    )
    if chrome:
        return chrome
    return _first_existing_file(_brave_app_candidates()) or _first_on_path(_BRAVE_PATH_NAMES)


def resolve_chrome_executable(cfg: WorkspaceConfig | None = None) -> str | None:
    """Locate a Chrome, Chromium, or Brave binary on the host.

    Precedence: ``SEVN_CHROME_EXECUTABLE`` env, then ``skills.browser.engine`` /
    ``SEVN_BROWSER_ENGINE`` (``auto`` prefers Chrome/Chromium before Brave).

    Args:
        cfg (WorkspaceConfig | None): Workspace config for engine preference.

    Returns:
        str | None: Executable path when found.

    Examples:
        >>> isinstance(resolve_chrome_executable(), str) or resolve_chrome_executable() is None
        True
    """
    env = (os.environ.get("SEVN_CHROME_EXECUTABLE") or "").strip()
    if env and Path(env).is_file():
        return env
    engine = resolve_browser_engine(cfg)
    return _resolve_chrome_family(engine)


def is_brave_executable(path: str) -> bool:
    """Return whether ``path`` points at a Brave browser binary.

    Args:
        path (str): Resolved executable path.

    Returns:
        bool: True when the basename or install path indicates Brave.

    Examples:
        >>> is_brave_executable("/usr/bin/brave-browser")
        True
        >>> is_brave_executable("/usr/bin/google-chrome-stable")
        False
    """
    lowered = path.replace("\\", "/").lower()
    base = Path(path).name.lower()
    if base in {"brave-browser", "brave", "brave.exe"}:
        return True
    return "/brave.com/" in lowered or "/bravesoftware/" in lowered


def resolve_browser_extra_args() -> list[str]:
    """Parse ``SEVN_BROWSER_EXTRA_ARGS`` (space-separated spawn flags).

    Returns:
        list[str]: Extra CLI args appended when spawning Chrome-compatible browsers.

    Examples:
        >>> resolve_browser_extra_args()
        []
    """
    raw = (os.environ.get("SEVN_BROWSER_EXTRA_ARGS") or "").strip()
    if not raw:
        return []
    return raw.split()


@dataclass(frozen=True, slots=True)
class BrowserReadiness:
    """Snapshot of browser binary resolution and CDP reachability for doctor probes."""

    executable: str | None
    engine: str
    is_brave: bool
    headless: bool
    cdp_url: str | None
    cdp_ok: bool


def browser_readiness_snapshot(
    content_root: Path,
    cfg: WorkspaceConfig | None = None,
    *,
    session_id: str = _DEFAULT_SESSION_ID,
) -> BrowserReadiness:
    """Collect browser readiness fields for ``sevn doctor`` and CLI checks.

    Args:
        content_root (Path): Workspace content root.
        cfg (WorkspaceConfig | None): Workspace config.
        session_id (str): Session id for CDP URL resolution.

    Returns:
        BrowserReadiness: Resolved binary, engine, headless mode, and CDP probe.

    Examples:
        >>> snap = browser_readiness_snapshot(Path("/tmp/ws-missing"))
        >>> snap.engine == "auto"
        True
    """
    exe = resolve_chrome_executable(cfg)
    engine = resolve_browser_engine(cfg)
    headless = resolve_browser_headless(cfg)
    cdp_url = resolve_cdp_url(content_root, session_id, cfg=cfg)
    cdp_ok = bool(cdp_url and cdp_reachable(cdp_url))
    return BrowserReadiness(
        executable=exe,
        engine=engine,
        is_brave=bool(exe and is_brave_executable(exe)),
        headless=headless,
        cdp_url=cdp_url,
        cdp_ok=cdp_ok,
    )


def resolve_browser_headless(cfg: WorkspaceConfig | None = None) -> bool:
    """Return whether new browser spawns should be headless (D13).

    Headed on host when Chrome exists unless ``skills.browser.headless`` is true.
    ``SEVN_BROWSER_HEADLESS`` wins over config when set. When no Chrome binary
    exists, headless is forced.

    Args:
        cfg (WorkspaceConfig | None): Workspace config.

    Returns:
        bool: ``True`` when spawns should use ``--headless=new``.

    Examples:
        >>> resolve_browser_headless(None) in (True, False)
        True
    """
    if resolve_chrome_executable(cfg) is None:
        return True
    env = os.environ.get("SEVN_BROWSER_HEADLESS", "").strip().lower()
    if env in {"1", "true", "yes", "on"}:
        return True
    if env in {"0", "false", "no", "off"}:
        return False
    if cfg is not None and isinstance(cfg.skills, dict):
        block = cfg.skills.get("browser")
        if isinstance(block, dict):
            raw = block.get("headless")
            if isinstance(raw, bool):
                return raw
            if isinstance(raw, str) and raw.strip().lower() in {"1", "true", "yes", "on"}:
                return True
    return False


def resolve_idle_close_seconds(cfg: WorkspaceConfig | None = None) -> int:
    """Return configured browser idle-close TTL in seconds (D8).

    Args:
        cfg (WorkspaceConfig | None): Workspace config.

    Returns:
        int: ``skills.browser.idle_close_seconds`` or ``0`` when disabled.

    Examples:
        >>> resolve_idle_close_seconds(None)
        0
    """
    if cfg is None or not isinstance(cfg.skills, dict):
        return 0
    block = cfg.skills.get("browser")
    if not isinstance(block, dict):
        return 0
    raw = block.get("idle_close_seconds")
    if isinstance(raw, bool):
        return 0
    if isinstance(raw, int):
        return max(0, raw)
    if isinstance(raw, float):
        return max(0, int(raw))
    if isinstance(raw, str) and raw.strip().isdigit():
        return max(0, int(raw.strip()))
    return 0


def _clear_profile_browser_locks(profile_dir: Path) -> None:
    """Delete stale CDP port / Singleton lock files under a sevn profile (DB2).

    Only call for a profile sevn owns (recorded registry ``profile_dir`` or the
    path about to be used by :func:`spawn_chrome`). Never pass an operator Chrome
    user-data directory (convention 11).

    Args:
        profile_dir (Path): Chrome ``user-data-dir`` owned by sevn.

    Returns:
        None

    Examples:
        >>> import tempfile
        >>> d = Path(tempfile.mkdtemp())
        >>> _ = (d / "DevToolsActivePort").write_text("1\\n", encoding="utf-8")
        >>> _clear_profile_browser_locks(d)
        >>> (d / "DevToolsActivePort").exists()
        False
    """
    for name in _PROFILE_BROWSER_LOCK_NAMES:
        path = profile_dir / name
        with contextlib.suppress(OSError):
            if path.is_symlink() or path.is_file():
                path.unlink()
            elif path.exists():
                # Singleton* can be a socket / special file on some platforms.
                path.unlink(missing_ok=True)


def read_devtools_active_port(
    profile_dir: Path,
    *,
    timeout: float = 15.0,
    spawn_started_at: float | None = None,
) -> int | None:
    """Read Chrome's chosen debugging port from ``DevToolsActivePort`` (D2/DB2).

    When ``spawn_started_at`` is set, ignore a port file whose mtime is not
    strictly later than that instant (stale file from a prior process).

    Args:
        profile_dir (Path): Chrome ``user-data-dir``.
        timeout (float): Maximum seconds to wait for a fresh file.
        spawn_started_at (float | None): ``time.time()`` at spawn start for the
            freshness probe; ``None`` accepts any present file.

    Returns:
        int | None: Port number from line 1, or ``None`` on timeout / stale-only.

    Examples:
        >>> import tempfile
        >>> d = Path(tempfile.mkdtemp())
        >>> read_devtools_active_port(d, timeout=0.05) is None
        True
    """
    port_file = profile_dir / "DevToolsActivePort"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_file.is_file():
            try:
                if spawn_started_at is not None:
                    mtime = port_file.stat().st_mtime
                    if mtime <= spawn_started_at:
                        time.sleep(0.05)
                        continue
                lines = port_file.read_text(encoding="utf-8").splitlines()
                if lines:
                    return int(lines[0].strip())
            except (OSError, ValueError):
                pass
        time.sleep(0.05)
    return None


def spawn_chrome(
    profile_dir: Path,
    *,
    headless: bool = False,
    seed_port: int | None = None,
    cfg: WorkspaceConfig | None = None,
) -> tuple[subprocess.Popen[bytes], int, str]:
    """Spawn detached Chrome with login-grade defaults and ephemeral CDP (D2/DB1).

    Clears stale ``DevToolsActivePort`` / Singleton* under ``profile_dir`` before
    launch, then re-passes AutomationControlled + hygiene flags every spawn.
    ``SEVN_BROWSER_EXTRA_ARGS`` still merge after the baked defaults.

    Args:
        profile_dir (Path): Persistent sevn ``user-data-dir``.
        headless (bool): When ``True``, pass ``--headless=new``.
        seed_port (int | None): Fallback port when ``DevToolsActivePort`` is slow.
        cfg (WorkspaceConfig | None): Workspace config for ``skills.browser.engine``.

    Returns:
        tuple[subprocess.Popen[bytes], int, str]: Process handle, port, CDP URL.

    Raises:
        RuntimeError: When Chrome is missing or port discovery fails.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(spawn_chrome)
        True
    """
    exe = resolve_chrome_executable(cfg)
    if not exe:
        msg = "Chrome executable not found"
        raise RuntimeError(msg)
    profile_dir.mkdir(parents=True, exist_ok=True)
    _clear_profile_browser_locks(profile_dir)
    args = [
        exe,
        "--remote-debugging-port=0",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        *_LOGIN_GRADE_CHROME_ARGS,
        *resolve_browser_extra_args(),
    ]
    if headless:
        args.append("--headless=new")
    spawn_started_at = time.time()
    proc = subprocess.Popen(  # nosec B603
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )
    port = read_devtools_active_port(profile_dir, spawn_started_at=spawn_started_at)
    if port is None and seed_port is not None:
        port = seed_port
    if port is None:
        if proc.poll() is None:
            proc.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=5)
        msg = "Failed to read DevToolsActivePort after spawning Chrome"
        raise RuntimeError(msg)
    cdp_url = f"http://127.0.0.1:{port}"
    return proc, port, cdp_url


def browser_autoclose_enabled() -> bool:
    """Return whether spawned browsers should terminate after each skill script (D4).

    Returns:
        bool: ``False`` when ``SEVN_BROWSER_AUTOCLOSE=0`` (gateway default for browser skills).

    Examples:
        >>> browser_autoclose_enabled() in (True, False)
        True
    """
    value = (os.environ.get("SEVN_BROWSER_AUTOCLOSE", "1") or "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _is_chrome_internal_or_ntp(url: str) -> bool:
    """Return whether ``url`` is an internal or new-tab page unsuitable as work tab.

    Args:
        url (str): Page URL from Playwright.

    Returns:
        bool: ``True`` for ``about:``, ``chrome://``, or bare Google NTP URLs.

    Examples:
        >>> _is_chrome_internal_or_ntp("chrome://newtab/")
        True
        >>> _is_chrome_internal_or_ntp("https://example.com/")
        False
    """
    u = (url or "").strip().lower()
    if not u:
        return True
    if u.startswith(("about:", "chrome://", "edge://", "devtools://")):
        return True
    try:
        parsed = urlparse(u)
        if parsed.scheme in ("http", "https") and parsed.netloc.endswith("google.com"):
            path = parsed.path or "/"
            if path in ("/", "") and not parsed.query:
                return True
    except ValueError:
        pass
    return False


def persist_active_target_id(
    content_root: Path,
    session_id: str,
    target_id: str | None,
) -> None:
    """Update registry ``active_target_id`` for a session when a registry row exists (D14).

    Args:
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.
        target_id (str | None): Active tab GUID or ``None`` to clear.

    Returns:
        None

    Examples:
        >>> import tempfile
        >>> from datetime import UTC, datetime
        >>> root = Path(tempfile.mkdtemp())
        >>> row = BrowserSessionRegistry(
        ...     pid=1, cdp_url="http://127.0.0.1:1", cdp_port=1, profile_dir="/p",
        ...     headless=False, spawned_by_sevn=True,
        ...     last_used_at=datetime.now(tz=UTC).isoformat(),
        ... )
        >>> write_registry(root, "s1", row)
        >>> persist_active_target_id(root, "s1", "tab-1")
        >>> read_registry(root, "s1").active_target_id
        'tab-1'
    """
    row = read_registry(content_root, session_id)
    if row is None:
        return
    write_registry(
        content_root,
        session_id,
        BrowserSessionRegistry(
            pid=row.pid,
            cdp_url=row.cdp_url,
            cdp_port=row.cdp_port,
            profile_dir=row.profile_dir,
            headless=row.headless,
            spawned_by_sevn=row.spawned_by_sevn,
            last_used_at=_utc_now_iso(),
            active_target_id=target_id,
            headless_persistent=row.headless_persistent,
        ),
    )


def _utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 form.

    Returns:
        str: Timezone-aware ISO timestamp.

    Examples:
        >>> _utc_now_iso().endswith("+00:00")
        True
    """
    return datetime.now(tz=UTC).isoformat()


def _kill_pid(pid: int | None) -> bool:
    """Best-effort terminate a browser process by pid.

    Args:
        pid (int | None): Operating-system process id.

    Returns:
        bool: ``True`` when ``SIGTERM`` was delivered.

    Examples:
        >>> _kill_pid(None)
        False
    """
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 15)
    except OSError:
        return False
    return True


def close_browser_session(
    content_root: Path,
    session_id: str,
    *,
    force: bool = False,
) -> CloseBrowserResult:
    """Close a sevn-managed browser for ``session_id`` (D6/D7).

    When the session is attach-only (operator CDP or ``spawned_by_sevn=False``),
    returns ``EXTERNAL_CDP`` unless ``force=True``.

    Args:
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.
        force (bool): When ``True``, attempt to kill even for external CDP (dangerous).

    Returns:
        CloseBrowserResult: Outcome code and message.

    Examples:
        >>> import tempfile
        >>> root = Path(tempfile.mkdtemp())
        >>> result = close_browser_session(root, "missing")
        >>> result.code in {"NOT_FOUND", "EXTERNAL_CDP", "CLOSED", "ALREADY_DEAD"}
        True
    """
    operator_cdp = default_cdp_url()
    row = read_registry(content_root, session_id)
    if row is None and operator_cdp is None:
        return CloseBrowserResult(ok=False, code="NOT_FOUND", message="no browser registry entry")
    if operator_cdp and not force:
        return CloseBrowserResult(
            ok=False,
            code=EXTERNAL_CDP,
            message="operator SEVN_CDP_URL is set; use force=True to override",
        )
    if row is not None and not row.spawned_by_sevn and not force:
        return CloseBrowserResult(
            ok=False,
            code=EXTERNAL_CDP,
            message="browser was not spawned by sevn; use force=True to override",
        )
    pid = row.pid if row is not None else None
    profile_dir: Path | None = None
    if row is not None and row.spawned_by_sevn and row.profile_dir.strip():
        profile_dir = Path(row.profile_dir)
    if pid is None:
        if profile_dir is not None:
            _clear_profile_browser_locks(profile_dir)
        clear_registry(content_root, session_id)
        return CloseBrowserResult(ok=True, code="ALREADY_DEAD", message="no pid recorded")
    killed = _kill_pid(pid)
    if profile_dir is not None:
        _clear_profile_browser_locks(profile_dir)
    clear_registry(content_root, session_id)
    if killed:
        return CloseBrowserResult(ok=True, code="CLOSED", message=f"terminated pid {pid}")
    return CloseBrowserResult(ok=True, code="ALREADY_DEAD", message="pid not running")


def _parse_last_used_at(raw: str) -> datetime | None:
    """Parse registry ``last_used_at`` ISO text into an aware datetime.

    Args:
        raw (str): Stored ISO-8601 timestamp.

    Returns:
        datetime | None: Parsed instant or ``None`` when invalid.

    Examples:
        >>> _parse_last_used_at("2026-01-01T00:00:00+00:00") is not None
        True
    """
    text = raw.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def close_idle_browser_sessions(
    *,
    content_root: Path,
    idle_seconds: int,
) -> int:
    """Close sevn-spawned browsers idle longer than ``idle_seconds`` (D8).

    Scans ``.sevn/browser-sessions/*.json`` registry files and calls
    :func:`close_browser_session` for stale ``spawned_by_sevn`` rows.

    Args:
        content_root (Path): Workspace content root.
        idle_seconds (int): Idle TTL; ``0`` disables the pass.

    Returns:
        int: Count of browsers closed (or already dead / skipped external CDP).

    Examples:
        >>> import tempfile
        >>> close_idle_browser_sessions(
        ...     content_root=Path(tempfile.mkdtemp()),
        ...     idle_seconds=0,
        ... )
        0
    """
    if idle_seconds <= 0:
        return 0
    reg_dir = _registry_dir(content_root)
    if not reg_dir.is_dir():
        return 0
    now = datetime.now(tz=UTC)
    closed = 0
    for path in reg_dir.glob("*.json"):
        row = read_registry(content_root, path.stem)
        if row is None or not row.spawned_by_sevn:
            continue
        last_used = _parse_last_used_at(row.last_used_at)
        if last_used is None:
            continue
        age_s = (now - last_used).total_seconds()
        if age_s < idle_seconds:
            continue
        result = close_browser_session(content_root, path.stem)
        if result.code in {"CLOSED", "ALREADY_DEAD"}:
            closed += 1
    return closed


def close_all_gateway_browsers(
    *,
    content_root: Path,
    conn: sqlite3.Connection,
) -> int:
    """Close sevn-spawned browsers for every ``gateway_sessions`` row.

    Args:
        content_root (Path): Workspace content root.
        conn (sqlite3.Connection): Open gateway SQLite handle.

    Returns:
        int: Count of browsers closed (or already dead / skipped external CDP).

    Examples:
        >>> import sqlite3
        >>> import tempfile
        >>> conn = sqlite3.connect(":memory:")
        >>> _ = conn.execute("CREATE TABLE gateway_sessions (session_id TEXT PRIMARY KEY)")
        >>> close_all_gateway_browsers(
        ...     content_root=Path(tempfile.mkdtemp()),
        ...     conn=conn,
        ... )
        0
    """
    rows = conn.execute("SELECT session_id FROM gateway_sessions").fetchall()
    closed = 0
    for row in rows:
        if not row or row[0] is None:
            continue
        session_id = str(row[0])
        result = close_browser_session(content_root, session_id)
        if result.code in {"CLOSED", "ALREADY_DEAD"}:
            closed += 1
    return closed


async def restart_browser_session(
    content_root: Path,
    session_id: str,
    *,
    cfg: WorkspaceConfig | None = None,
    force_close: bool = False,
) -> BrowserSessionRegistry:
    """Close then respawn the session browser and wait for CDP.

    Args:
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.
        cfg (WorkspaceConfig | None): Workspace config for headless/profile overrides.
        force_close (bool): Pass ``force=True`` to :func:`close_browser_session`.

    Returns:
        BrowserSessionRegistry: Fresh registry row after spawn.

    Raises:
        RuntimeError: When spawn or CDP attach fails.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(restart_browser_session)
        True
    """
    close_browser_session(content_root, session_id, force=force_close)
    profile_dir = resolve_profile_dir(content_root, session_id, cfg=cfg)
    headless = resolve_browser_headless(cfg)
    seed = cdp_port_seed(session_id)
    proc, port, cdp_url = await asyncio.to_thread(
        spawn_chrome,
        profile_dir,
        headless=headless,
        seed_port=seed,
        cfg=cfg,
    )
    for _ in range(50):
        if cdp_reachable(cdp_url):
            break
        await asyncio.sleep(0.2)
    if not cdp_reachable(cdp_url):
        if proc.poll() is None:
            proc.terminate()
        msg = f"CDP not reachable after restart at {cdp_url}"
        raise RuntimeError(msg)
    row = BrowserSessionRegistry(
        pid=proc.pid,
        cdp_url=cdp_url,
        cdp_port=port,
        profile_dir=str(profile_dir),
        headless=headless,
        spawned_by_sevn=True,
        last_used_at=_utc_now_iso(),
    )
    write_registry(content_root, session_id, row)
    return row


def session_status_payload(
    *,
    content_root: Path,
    session_id: str,
    cfg: WorkspaceConfig | None = None,
    skill_name: str | None = None,
) -> dict[str, object]:
    """Build unified browser session status metadata.

    ``operator_cdp_override`` is ``True`` only when the operator set ``SEVN_CDP_URL``
    in the process environment. Seed-hint URLs from :func:`resolve_cdp_url` (no registry
    row yet) are **not** operator overrides — see ``cdp_url_is_seed_hint``.

    Args:
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.
        cfg (WorkspaceConfig | None): Workspace config.
        skill_name (str | None): Optional bundled skill id for envelope context.

    Returns:
        dict[str, object]: Profile, CDP, registry, and reachability fields.

    Examples:
        >>> import tempfile
        >>> payload = session_status_payload(
        ...     content_root=Path(tempfile.mkdtemp()), session_id="s1",
        ... )
        >>> payload["session_id"]
        's1'
    """
    sid = _normalise_session_id(session_id)
    profile = resolve_profile_dir(content_root, sid, cfg=cfg)
    cdp = resolve_cdp_url(content_root, sid, cfg=cfg)
    row = read_registry(content_root, sid)
    operator_cdp = default_cdp_url()
    cdp_url_is_seed_hint = operator_cdp is None and (row is None or not row.cdp_url.strip())
    return {
        "skill_name": skill_name,
        "session_id": sid,
        "profile_dir": str(profile),
        "profile_exists": profile.is_dir(),
        "cdp_url": cdp,
        "cdp_reachable": cdp_reachable(cdp),
        "cdp_url_is_seed_hint": cdp_url_is_seed_hint,
        "operator_cdp_override": operator_cdp is not None,
        "registry": None if row is None else asdict(row),
        "headless_default": resolve_browser_headless(cfg),
        "session_model": "session_scoped_browser_profile_or_cdp_attach",
    }


def merge_browser_proc_env(
    env: dict[str, str],
    *,
    content_root: Path,
    session_id: str,
    cfg: WorkspaceConfig | None,
    skill_name: str,
) -> None:
    """Inject browser session env vars for skill subprocesses (in-place).

    Sets ``SEVN_CONTENT_ROOT``, profile directory, and default
    ``SEVN_BROWSER_AUTOCLOSE=0`` for browser skill ids (D4). Does **not** inject
    ``SEVN_CDP_URL`` — seed-hint URLs block Chrome auto-spawn; operator attach
    URLs propagate via gateway ``os.environ`` copy in :func:`SkillsManager._build_proc_env`.

    Args:
        env (dict[str, str]): Subprocess environment to mutate.
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.
        cfg (WorkspaceConfig | None): Workspace config.
        skill_name (str): Canonical bundled skill id.

    Returns:
        None

    Examples:
        >>> import tempfile
        >>> env: dict[str, str] = {}
        >>> merge_browser_proc_env(
        ...     env,
        ...     content_root=Path(tempfile.mkdtemp()),
        ...     session_id="s1",
        ...     cfg=None,
        ...     skill_name="browser-harness",
        ... )
        >>> env.get("SEVN_CONTENT_ROOT") is not None
        True
    """
    if skill_name not in BROWSER_SKILL_IDS:
        return
    env[_CONTENT_ROOT_ENV] = str(content_root.expanduser().resolve())
    sid = _normalise_session_id(session_id or env.get(_SESSION_ID_ENV, ""))
    if sid != _DEFAULT_SESSION_ID:
        env.setdefault(_SESSION_ID_ENV, sid)
    if not env.get("SEVN_BROWSER_AUTOCLOSE", "").strip():
        env["SEVN_BROWSER_AUTOCLOSE"] = "0"
    profile = resolve_profile_dir(content_root, sid, cfg=cfg)
    env.setdefault(_PROFILE_ENV, str(profile))


__all__ = [
    "BROWSER_SKILL_IDS",
    "EXTERNAL_CDP",
    "BrowserReadiness",
    "BrowserSessionRegistry",
    "CloseBrowserResult",
    "browser_autoclose_enabled",
    "browser_readiness_snapshot",
    "cdp_list_page_targets",
    "cdp_port_from_url",
    "cdp_port_seed",
    "cdp_reachable",
    "clear_registry",
    "close_all_gateway_browsers",
    "close_browser_session",
    "close_idle_browser_sessions",
    "default_cdp_url",
    "is_brave_executable",
    "merge_browser_proc_env",
    "persist_active_target_id",
    "read_devtools_active_port",
    "read_registry",
    "registry_path",
    "resolve_browser_engine",
    "resolve_browser_extra_args",
    "resolve_browser_headless",
    "resolve_cdp_url",
    "resolve_chrome_executable",
    "resolve_idle_close_seconds",
    "resolve_profile_dir",
    "restart_browser_session",
    "session_status_payload",
    "spawn_chrome",
    "write_registry",
]
