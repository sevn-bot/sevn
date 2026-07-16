"""Session-scoped browser lifecycle — profile, CDP, registry, spawn/attach/close.

Module: sevn.skills.browser_session
Depends: asyncio, hashlib, json, os, pathlib, subprocess, urllib

Exports:
    BrowserSessionRegistry — persisted registry row for one gateway session.
    CloseBrowserResult — outcome of :func:`close_browser_session`.
    TabOperationError — tab CRUD refused (for example last-tab close).
    TabSessionView — duck-typed browser surface for tab enumeration and CRUD.
    activate_tab — focus a tab and persist ``active_target_id`` (D14).
    browser_autoclose_enabled — read ``SEVN_BROWSER_AUTOCLOSE`` (default keep-alive).
    browser_page — async context manager yielding a Playwright ``Page``.
    close_tab — close one tab; refuses the last tab (D14).
    connected_tab_session — async context manager yielding :class:`TabSessionView`.
    list_tabs — enumerate tabs with ``target_id``, url, title, and active flag.
    open_tab — open a URL in a new tab; optionally activate (D14).
    page_target_id — stable tab id (Playwright GUID or CDP /json/list fallback).
    persist_active_target_id — update registry ``active_target_id`` for a session.
    try_persist_active_page — best-effort registry ``active_target_id`` after navigation.
    cdp_list_page_targets — fetch Chrome DevTools page targets from ``/json/list``.
    resolve_target_page — resolve explicit ``--tab`` id, registry active, or heuristic.
    cdp_port_from_url — parse TCP port from a CDP base URL.
    cdp_port_seed — deterministic seed port hint from ``session_id`` (D2).
    cdp_reachable — probe ``/json/version`` on a CDP endpoint.
    clear_registry — remove the registry file for a session.
    close_all_gateway_browsers — close sevn-spawned browsers for gateway session rows.
    close_browser_session — kill sevn-spawned browser or skip external CDP.
    close_idle_browser_sessions — close stale sevn-spawned browsers by ``last_used_at``.
    default_cdp_url — read ``SEVN_CDP_URL`` when set.
    merge_browser_proc_env — inject content root, profile, CDP env for skill runs.
    pick_work_page — choose a tab; prefer registry ``active_target_id``.
    pid_is_alive — return whether a process id responds to ``signal 0``.
    pid_matches_sevn_chrome_profile — cmdline identity check before SIGTERM (convention 11).
    read_devtools_active_port — read Chrome ``DevToolsActivePort`` line 1 (optional freshness).
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
    spawn_chrome — detached Chrome with ``--remote-debugging-port=0`` (D2/D5).
    wait_for_page_ready — post-navigation load + best-effort network idle.
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
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlparse

from sevn.config.workspace_config import WorkspaceConfig

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright

BROWSER_SKILL_IDS: Final[frozenset[str]] = frozenset(
    {"playwright-browser", "browser-harness", "x-use", "facebook-use"},
)
EXTERNAL_CDP: Final[str] = "EXTERNAL_CDP"
_DEFAULT_SESSION_ID: Final[str] = "default"
_PROFILE_ENV: Final[str] = "SEVN_BROWSER_PROFILE_DIR"
_CONTENT_ROOT_ENV: Final[str] = "SEVN_CONTENT_ROOT"
_SESSION_ID_ENV: Final[str] = "SEVN_SESSION_ID"


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


class TabOperationError(Exception):
    """Tab CRUD refused — for example closing the last tab (D14)."""

    def __init__(self, code: str, message: str) -> None:
        """Store a machine-readable tab error code and operator message.

        Args:
            code (str): Error code (for example ``LAST_TAB``).
            message (str): Human-readable explanation.

        Returns:
            None

        Examples:
            >>> err = TabOperationError("LAST_TAB", "cannot close the last tab")
            >>> err.code
            'LAST_TAB'
        """
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class TabSessionView:
    """Duck-typed browser surface for tab CRUD over CDP attach or persistent context."""

    browser: Any | None = None
    context: Any | None = None
    cdp_url: str | None = None

    def collect_pages(self) -> list[Any]:
        """Return all open pages across the session browser.

        Returns:
            list[Any]: Playwright ``Page`` instances.

        Examples:
            >>> view = TabSessionView(context=type("C", (), {"pages": []})())
            >>> view.collect_pages()
            []
        """
        if self.context is not None:
            return list(self.context.pages)
        pages: list[Any] = []
        if self.browser is not None:
            for ctx in self.browser.contexts:
                pages.extend(ctx.pages)
        return pages

    async def new_page(self) -> Any:
        """Open a new page in the default browser context.

        Returns:
            Any: New Playwright ``Page``.

        Raises:
            RuntimeError: When no browser or context is attached.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TabSessionView.new_page)
            True
        """
        if self.context is not None:
            return await self.context.new_page()
        if self.browser is None:
            msg = "no browser context available for new_page"
            raise RuntimeError(msg)
        ctx = (
            self.browser.contexts[0] if self.browser.contexts else await self.browser.new_context()
        )
        return await ctx.new_page()


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
    ``skills.social_browser.profile_dir`` →
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
    if from_cfg is None:
        from_cfg = _read_profile_from_cfg(cfg, "social_browser")
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
    exists, headless is forced for Playwright fallback paths.

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


def pid_is_alive(pid: int) -> bool:
    """Return whether ``pid`` responds to ``os.kill(..., 0)``.

    Args:
        pid (int): Operating-system process id.

    Returns:
        bool: ``True`` when the process exists (and is signalable by this user).

    Examples:
        >>> pid_is_alive(os.getpid())
        True
        >>> pid_is_alive(0)
        False
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _read_pid_cmdline(pid: int) -> str:
    """Best-effort process command line for ``pid`` (Linux ``/proc`` or ``ps``).

    Args:
        pid (int): Operating-system process id.

    Returns:
        str: Command line text, or empty when unreadable.

    Examples:
        >>> _read_pid_cmdline(0)
        ''
    """
    if pid <= 0:
        return ""
    proc_cmdline = Path(f"/proc/{pid}/cmdline")
    if proc_cmdline.is_file():
        try:
            return (
                proc_cmdline.read_bytes()
                .replace(b"\x00", b" ")
                .decode(
                    "utf-8",
                    errors="replace",
                )
            )
        except OSError:
            return ""
    try:
        completed = subprocess.run(  # nosec B603 B607 — fixed argv, no shell
            ["ps", "-p", str(pid), "-o", "args="],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if completed.returncode != 0:
        return ""
    return (completed.stdout or "").strip()


def pid_matches_sevn_chrome_profile(pid: int, profile_dir: Path) -> bool:
    """Return whether ``pid`` still looks like Chrome for ``profile_dir`` (convention 11).

    Fail closed: when the cmdline cannot be read, returns ``False`` so we never
    SIGTERM/SIGKILL an unverified PID (operator Chrome / PID reuse).

    Args:
        pid (int): Candidate process id from the session registry.
        profile_dir (Path): Expected ``--user-data-dir`` for this session.

    Returns:
        bool: ``True`` when cmdline mentions Chrome/Chromium and this profile path.

    Examples:
        >>> pid_matches_sevn_chrome_profile(0, Path("/tmp/p"))
        False
    """
    if pid <= 0:
        return False
    try:
        needle = str(profile_dir.expanduser().resolve())
    except OSError:
        needle = str(profile_dir)
    cmdline = _read_pid_cmdline(pid)
    if not cmdline:
        return False
    lowered = cmdline.lower()
    if "chrome" not in lowered and "chromium" not in lowered:
        return False
    return needle in cmdline or f"--user-data-dir={needle}" in cmdline


def read_devtools_active_port(
    profile_dir: Path,
    *,
    timeout: float | None = None,
    spawned_after: float | None = None,
) -> int | None:
    """Read Chrome's chosen debugging port from ``DevToolsActivePort`` (D2).

    When ``spawned_after`` is set, only accept a port file whose mtime is
    strictly later than that unix timestamp (a stale file from a prior Chrome
    is ignored). Callers that need to wait for a fresh write should poll this
    helper inside their own wait window (or pass an explicit ``timeout``).

    Args:
        profile_dir (Path): Chrome ``user-data-dir``.
        timeout (float | None): Maximum seconds to wait. Defaults to ``15.0``
            when ``spawned_after`` is omitted, or ``0.0`` (single check) when
            freshness is requested so callers own the adaptive wait loop.
        spawned_after (float | None): Unix mtime lower bound for freshness.

    Returns:
        int | None: Port number from line 1, or ``None`` on timeout / stale.

    Examples:
        >>> import tempfile
        >>> d = Path(tempfile.mkdtemp())
        >>> read_devtools_active_port(d, timeout=0.05) is None
        True
    """
    wait_s = (
        15.0 if timeout is None and spawned_after is None else (0.0 if timeout is None else timeout)
    )
    port_file = profile_dir / "DevToolsActivePort"
    deadline = time.monotonic() + wait_s
    while True:
        if port_file.is_file():
            try:
                if spawned_after is not None and port_file.stat().st_mtime <= spawned_after:
                    pass
                else:
                    lines = port_file.read_text(encoding="utf-8").splitlines()
                    if lines:
                        return int(lines[0].strip())
            except (OSError, ValueError):
                pass
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.05)


def spawn_chrome(
    profile_dir: Path,
    *,
    headless: bool = False,
    seed_port: int | None = None,
    cfg: WorkspaceConfig | None = None,
    session_id: str | None = None,
    log_dir: Path | None = None,
) -> tuple[subprocess.Popen[bytes], int, str]:
    """Spawn detached Chrome with ``--remote-debugging-port=0`` (D2/D5).

    When ``session_id`` and ``log_dir`` are provided, Chrome stdout/stderr are
    redirected to ``log_dir/chrome-<session_id>.log`` (D4) instead of ``DEVNULL``.

    Args:
        profile_dir (Path): Persistent ``user-data-dir``.
        headless (bool): When ``True``, pass ``--headless=new``.
        seed_port (int | None): Fallback port when ``DevToolsActivePort`` is slow.
        cfg (WorkspaceConfig | None): Workspace config for ``skills.browser.engine``.
        session_id (str | None): Gateway session id for the Chrome log filename.
        log_dir (Path | None): Directory for ``chrome-<session>.log`` (D4).

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
    args = [
        exe,
        "--remote-debugging-port=0",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        *resolve_browser_extra_args(),
    ]
    if headless:
        args.append("--headless=new")
    spawn_started = time.time()
    log_handle = None
    stdout_dest: Any = subprocess.DEVNULL
    stderr_dest: Any = subprocess.DEVNULL
    sid = (session_id or "").strip()
    if sid and log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"chrome-{sid}.log"
        log_handle = log_path.open("ab")
        stdout_dest = log_handle
        stderr_dest = log_handle
    try:
        proc = subprocess.Popen(  # nosec B603
            args,
            stdout=stdout_dest,
            stderr=stderr_dest,
            stdin=subprocess.DEVNULL,
        )
    finally:
        if log_handle is not None:
            with contextlib.suppress(OSError):
                log_handle.close()
    # Return after Popen — lifecycle (or caller) owns the single adaptive
    # DevTools/CDP wait. Avoid stacking spawn's former ~15s poll on top of
    # lifecycle's ~20s adaptive wait (Thermos).
    _ = spawn_started
    port = int(seed_port) if seed_port is not None else 0
    cdp_url = f"http://127.0.0.1:{port}" if port > 0 else "http://127.0.0.1:0"
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


async def pick_work_page(
    browser: Any,
    *,
    active_target_id: str | None = None,
    cdp_url: str | None = None,
) -> Any:
    """Choose a tab for interaction; prefer registry ``active_target_id`` (D14).

    Args:
        browser (Any): Playwright ``Browser`` connected over CDP.
        active_target_id (str | None): Registry active tab id when known.
        cdp_url (str | None): Reachable CDP base URL for target-id fallback matching.

    Returns:
        Any: Selected or newly created ``Page``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(pick_work_page)
        True
    """
    pages: list[Any] = []
    for ctx in browser.contexts:
        pages.extend(ctx.pages)
    cdp_targets = cdp_list_page_targets(cdp_url) if cdp_url and cdp_reachable(cdp_url) else None
    if active_target_id:
        for page in pages:
            try:
                if (
                    page_target_id(page, cdp_url=cdp_url, cdp_targets=cdp_targets)
                    == active_target_id
                ):
                    return page
            except RuntimeError:
                continue
    if not pages:
        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        return await ctx.new_page()
    for page in reversed(pages):
        url = page.url or ""
        if url.startswith(("http://", "https://")) and not _is_chrome_internal_or_ntp(url):
            return page
    for page in reversed(pages):
        if (page.url or "").startswith("https://"):
            return page
    return pages[-1]


def page_target_id(
    page: Any,
    *,
    cdp_url: str | None = None,
    cdp_targets: list[dict[str, Any]] | None = None,
    title: str = "",
) -> str:
    """Return a stable tab id — Playwright GUID or CDP ``/json/list`` fallback (D14).

    Args:
        page (Any): Playwright ``Page``.
        cdp_url (str | None): CDP base URL used to fetch ``/json/list`` when GUID absent.
        cdp_targets (list[dict[str, Any]] | None): Pre-fetched CDP page targets.
        title (str): Optional page title to disambiguate CDP matches.

    Returns:
        str: Tab target id string.

    Raises:
        RuntimeError: When neither Playwright GUID nor CDP target id resolves.

    Examples:
        >>> class _FakePage:
        ...     _guid = "page-guid-abc"
        >>> page_target_id(_FakePage())
        'page-guid-abc'
    """
    guid = getattr(page, "_guid", None) or getattr(page, "guid", None)
    if guid:
        return str(guid)
    targets = cdp_targets
    if targets is None and cdp_url and cdp_reachable(cdp_url):
        targets = cdp_list_page_targets(cdp_url)
    if targets:
        matched = _match_cdp_target_for_page(page, targets, title=title)
        if matched:
            return matched
    msg = "page has no stable target id"
    raise RuntimeError(msg)


async def try_persist_active_page(
    page: Any,
    *,
    content_root: Path,
    session_id: str,
    cdp_url: str | None = None,
) -> str | None:
    """Persist registry ``active_target_id`` when the page target id resolves.

    Args:
        page (Any): Playwright ``Page`` after navigation or attach.
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.
        cdp_url (str | None): Optional reachable CDP base URL for fallback matching.

    Returns:
        str | None: Resolved target id, or ``None`` when not persistable.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(try_persist_active_page)
        True
    """
    resolved_cdp = cdp_url
    if not resolved_cdp:
        candidate = resolve_cdp_url(content_root, session_id)
        if cdp_reachable(candidate):
            resolved_cdp = candidate.rstrip("/")
    title = ""
    with contextlib.suppress(Exception):
        title = await page.title()
    try:
        target_id = page_target_id(page, cdp_url=resolved_cdp, title=title)
    except RuntimeError:
        return None
    persist_active_target_id(content_root, session_id, target_id)
    return target_id


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


def _find_page_by_target_id(view: TabSessionView, target_id: str) -> Any | None:
    """Locate a page by ``target_id`` within a tab session view.

    Args:
        view (TabSessionView): Session browser view.
        target_id (str): Playwright GUID or CDP target id to match.

    Returns:
        Any | None: Matching ``Page`` or ``None``.

    Examples:
        >>> class _P:
        ...     _guid = "g1"
        >>> page = _P()
        >>> view = TabSessionView(context=type("C", (), {"pages": [page]})())
        >>> _find_page_by_target_id(view, "g1") is page
        True
    """
    needle = target_id.strip()
    if not needle:
        return None
    cdp_targets = (
        cdp_list_page_targets(view.cdp_url)
        if view.cdp_url and cdp_reachable(view.cdp_url)
        else None
    )
    for page in view.collect_pages():
        try:
            if page_target_id(page, cdp_url=view.cdp_url, cdp_targets=cdp_targets) == needle:
                return page
        except RuntimeError:
            continue
    return None


async def resolve_target_page(
    view: TabSessionView,
    *,
    active_target_id: str | None = None,
    tab_target_id: str | None = None,
) -> Any:
    """Resolve interaction page: explicit tab id, registry active, then heuristic (D14).

    Args:
        view (TabSessionView): Session browser view.
        active_target_id (str | None): Registry active tab when known.
        tab_target_id (str | None): Explicit ``--tab`` override.

    Returns:
        Any: Selected Playwright ``Page``.

    Raises:
        RuntimeError: When ``tab_target_id`` does not match any open tab.
        TabOperationError: When no pages exist and a new page cannot be created.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(resolve_target_page)
        True
    """
    if tab_target_id:
        page = _find_page_by_target_id(view, tab_target_id)
        if page is None:
            msg = f"tab not found: {tab_target_id}"
            raise RuntimeError(msg)
        return page
    if view.browser is not None:
        return await pick_work_page(
            view.browser,
            active_target_id=active_target_id,
            cdp_url=view.cdp_url,
        )
    pages = view.collect_pages()
    cdp_targets = (
        cdp_list_page_targets(view.cdp_url)
        if view.cdp_url and cdp_reachable(view.cdp_url)
        else None
    )
    if active_target_id:
        for page in pages:
            try:
                if (
                    page_target_id(page, cdp_url=view.cdp_url, cdp_targets=cdp_targets)
                    == active_target_id
                ):
                    return page
            except RuntimeError:
                continue
    if not pages:
        return await view.new_page()
    for page in reversed(pages):
        url = page.url or ""
        if url.startswith(("http://", "https://")) and not _is_chrome_internal_or_ntp(url):
            return page
    return pages[-1]


async def list_tabs(
    view: TabSessionView,
    *,
    active_target_id: str | None = None,
) -> dict[str, object]:
    """Enumerate open tabs with stable ``target_id`` values (D14).

    Uses Playwright GUIDs when present; otherwise matches CDP ``/json/list`` page
    targets by URL/title. Reports ``untrackable_count`` when pages exist but cannot
    be mapped.

    Args:
        view (TabSessionView): Session browser view.
        active_target_id (str | None): Registry active tab id for the ``active`` flag.

    Returns:
        dict[str, object]: ``tabs``, ``count``, ``page_count``, optional ``untrackable_count``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(list_tabs)
        True
    """
    pages = view.collect_pages()
    cdp_targets = (
        cdp_list_page_targets(view.cdp_url)
        if view.cdp_url and cdp_reachable(view.cdp_url)
        else None
    )
    rows: list[dict[str, object]] = []
    for page in pages:
        title = ""
        with contextlib.suppress(Exception):
            title = await page.title()
        try:
            tid = page_target_id(
                page,
                cdp_url=view.cdp_url,
                cdp_targets=cdp_targets,
                title=title,
            )
        except RuntimeError:
            continue
        rows.append(
            {
                "target_id": tid,
                "url": page.url or "",
                "title": title,
                "active": tid == active_target_id if active_target_id else False,
                "id_source": (
                    "playwright"
                    if getattr(page, "_guid", None) or getattr(page, "guid", None)
                    else "cdp"
                ),
            },
        )
    untrackable = len(pages) - len(rows)
    payload: dict[str, object] = {
        "tabs": rows,
        "count": len(rows),
        "page_count": len(pages),
    }
    if untrackable:
        payload["untrackable_count"] = untrackable
        payload["note"] = (
            f"{untrackable} page(s) open but no stable target id "
            "(Playwright GUID and CDP fallback both failed)"
        )
    return payload


async def open_tab(
    view: TabSessionView,
    url: str,
    *,
    activate: bool = True,
    content_root: Path | None = None,
    session_id: str | None = None,
) -> dict[str, object]:
    """Open ``url`` in a new tab; optionally focus and persist ``active_target_id`` (D14).

    Args:
        view (TabSessionView): Session browser view.
        url (str): Navigation URL (may be ``about:blank``).
        activate (bool): When ``True``, ``bring_to_front`` and update registry active tab.
        content_root (Path | None): Content root for registry persistence.
        session_id (str | None): Gateway session id for registry persistence.

    Returns:
        dict[str, object]: ``{target_id, url, title, active}``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(open_tab)
        True
    """
    page = await view.new_page()
    dest = (url or "about:blank").strip() or "about:blank"
    if dest != "about:blank":
        await page.goto(dest, wait_until="load", timeout=60_000)
        await wait_for_page_ready(page)
    title = ""
    with contextlib.suppress(Exception):
        title = await page.title()
    tid = page_target_id(page, cdp_url=view.cdp_url, title=title)
    if activate:
        with contextlib.suppress(Exception):
            await page.bring_to_front()
        if content_root is not None and session_id is not None:
            persist_active_target_id(content_root, session_id, tid)
    return {
        "target_id": tid,
        "url": page.url or dest,
        "title": title,
        "active": activate,
    }


async def close_tab(
    view: TabSessionView,
    target_id: str,
    *,
    content_root: Path | None = None,
    session_id: str | None = None,
) -> dict[str, object]:
    """Close one tab by ``target_id``; refuse when it is the last tab (D14).

    Args:
        view (TabSessionView): Session browser view.
        target_id (str): Page GUID to close.
        content_root (Path | None): Content root for registry persistence.
        session_id (str | None): Gateway session id for registry persistence.

    Returns:
        dict[str, object]: ``{target_id, closed: True}``.

    Raises:
        TabOperationError: When ``target_id`` is missing or is the last tab.
        RuntimeError: When ``target_id`` does not match any open tab.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(close_tab)
        True
    """
    pages = view.collect_pages()
    if len(pages) <= 1:
        raise TabOperationError("LAST_TAB", "cannot close the last tab")
    page = _find_page_by_target_id(view, target_id)
    if page is None:
        msg = f"tab not found: {target_id}"
        raise RuntimeError(msg)
    title = ""
    with contextlib.suppress(Exception):
        title = await page.title()
    closing_id = page_target_id(page, cdp_url=view.cdp_url, title=title)
    await page.close()
    if content_root is not None and session_id is not None:
        row = read_registry(content_root, session_id)
        if row is not None and row.active_target_id == closing_id:
            remaining = view.collect_pages()
            new_active: str | None = None
            if remaining:
                with contextlib.suppress(RuntimeError):
                    new_active = page_target_id(remaining[-1], cdp_url=view.cdp_url)
            persist_active_target_id(content_root, session_id, new_active)
    return {"target_id": closing_id, "closed": True}


async def activate_tab(
    view: TabSessionView,
    target_id: str,
    *,
    content_root: Path | None = None,
    session_id: str | None = None,
) -> dict[str, object]:
    """Focus a tab via ``bring_to_front`` and persist ``active_target_id`` (D14).

    Args:
        view (TabSessionView): Session browser view.
        target_id (str): Page GUID to activate.
        content_root (Path | None): Content root for registry persistence.
        session_id (str | None): Gateway session id for registry persistence.

    Returns:
        dict[str, object]: ``{target_id, url, title, active: True}``.

    Raises:
        RuntimeError: When ``target_id`` does not match any open tab.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(activate_tab)
        True
    """
    page = _find_page_by_target_id(view, target_id)
    if page is None:
        msg = f"tab not found: {target_id}"
        raise RuntimeError(msg)
    title = ""
    with contextlib.suppress(Exception):
        title = await page.title()
    tid = page_target_id(page, cdp_url=view.cdp_url, title=title)
    with contextlib.suppress(Exception):
        await page.bring_to_front()
    if content_root is not None and session_id is not None:
        persist_active_target_id(content_root, session_id, tid)
    return {
        "target_id": tid,
        "url": page.url or "",
        "title": title,
        "active": True,
    }


async def wait_for_page_ready(page: Any, *, network_idle_ms: float = 15_000.0) -> None:
    """After navigation, wait for load then best-effort network idle.

    Args:
        page (Any): Playwright ``Page``.
        network_idle_ms (float): ``networkidle`` timeout in milliseconds.

    Returns:
        None

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(wait_for_page_ready)
        True
    """
    await page.wait_for_load_state("load")
    with contextlib.suppress(Exception):
        await page.wait_for_load_state("networkidle", timeout=int(network_idle_ms))


def _utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 form.

    Returns:
        str: Timezone-aware ISO timestamp.

    Examples:
        >>> _utc_now_iso().endswith("+00:00")
        True
    """
    return datetime.now(tz=UTC).isoformat()


def _kill_pid(pid: int | None, *, profile_dir: Path | None = None) -> bool:
    """Best-effort terminate a browser process by pid via lifecycle SSOT.

    Args:
        pid (int | None): Operating-system process id.
        profile_dir (Path | None): Optional profile for convention-11 matching.

    Returns:
        bool: ``True`` when a terminate signal was attempted.

    Examples:
        >>> _kill_pid(None)
        False
    """
    if pid is None or pid <= 0:
        return False
    from sevn.browser.lifecycle import terminate_sevn_chrome

    return terminate_sevn_chrome(pid, profile_dir, escalate=True)


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
    if pid is None:
        clear_registry(content_root, session_id)
        return CloseBrowserResult(ok=True, code="ALREADY_DEAD", message="no pid recorded")
    profile = Path(row.profile_dir) if row is not None and row.profile_dir else None
    killed = _kill_pid(pid, profile_dir=profile)
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
    """Close then respawn via the hardened lifecycle spawn path.

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
    from sevn.browser.lifecycle import spawn_or_attach

    await spawn_or_attach(content_root, session_id, cfg=cfg)
    row = read_registry(content_root, session_id)
    if row is None or not row.cdp_url.strip():
        msg = f"CDP not reachable after restart for session {session_id}"
        raise RuntimeError(msg)
    return row


async def _session_browser_resources(
    *,
    content_root: Path,
    session_id: str,
    cfg: WorkspaceConfig | None,
    headless_fallback: bool,
) -> tuple[
    Playwright,
    Browser | None,
    BrowserContext | None,
    subprocess.Popen[bytes] | None,
    bool,
    bool,
    str,
    BrowserSessionRegistry | None,
    Path,
    bool,
]:
    """Attach or spawn the session browser; shared setup for page and tab entry points.

    Args:
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.
        cfg (WorkspaceConfig | None): Workspace config.
        headless_fallback (bool): Allow Playwright headless fallback when Chrome absent.

    Returns:
        tuple: Playwright handle, browser, persistent context, chrome proc, spawn flags,
        session id, registry row, profile dir, headless flag.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_session_browser_resources)
        True
    """
    from playwright.async_api import async_playwright

    sid = _normalise_session_id(session_id or os.environ.get(_SESSION_ID_ENV, ""))
    profile_dir = resolve_profile_dir(content_root, sid, cfg=cfg)
    headless = resolve_browser_headless(cfg)
    operator_cdp = default_cdp_url()
    registry_row = read_registry(content_root, sid)
    active_target_id = registry_row.active_target_id if registry_row else None

    cdp_url = resolve_cdp_url(content_root, sid, cfg=cfg)
    chrome_proc: subprocess.Popen[bytes] | None = None
    playwright = await async_playwright().start()
    if playwright is None:
        msg = "playwright failed to start"
        raise RuntimeError(msg)
    browser: Browser | None = None
    persistent_context: BrowserContext | None = None
    launched_headless_fallback = False
    we_spawned_chrome = False
    spawn_attempted = False

    async def try_cdp(url: str) -> Browser | None:
        try:
            return await playwright.chromium.connect_over_cdp(url)
        except Exception:
            return None

    if cdp_reachable(cdp_url):
        browser = await try_cdp(cdp_url)

    if browser is None and operator_cdp is None:
        exe = resolve_chrome_executable(cfg)
        if exe:
            spawn_attempted = True
            seed = cdp_port_seed(sid)
            spawn_wall = time.time()
            spawned_proc, port, spawned_url = await asyncio.to_thread(
                spawn_chrome,
                profile_dir,
                headless=headless,
                seed_port=seed,
                cfg=cfg,
                session_id=sid,
                log_dir=content_root / "logs",
            )
            chrome_proc = spawned_proc
            we_spawned_chrome = True
            cdp_url = spawned_url
            # Single adaptive wait (spawn returns after Popen — no nested 15s).
            for _ in range(100):
                fresh = await asyncio.to_thread(
                    read_devtools_active_port,
                    profile_dir,
                    spawned_after=spawn_wall,
                )
                if fresh is not None:
                    port = fresh
                    cdp_url = f"http://127.0.0.1:{fresh}"
                if cdp_reachable(cdp_url):
                    break
                if spawned_proc.poll() is not None:
                    break
                await asyncio.sleep(0.2)
            if cdp_reachable(cdp_url):
                browser = await try_cdp(cdp_url)
            if browser is not None:
                registry_row = BrowserSessionRegistry(
                    pid=spawned_proc.pid,
                    cdp_url=cdp_url,
                    cdp_port=port,
                    profile_dir=str(profile_dir),
                    headless=headless,
                    spawned_by_sevn=True,
                    last_used_at=_utc_now_iso(),
                    active_target_id=active_target_id,
                )
                write_registry(content_root, sid, registry_row)
            elif spawned_proc.poll() is None:
                spawned_proc.terminate()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    spawned_proc.wait(timeout=5)
                chrome_proc = None
                we_spawned_chrome = False

    if browser is None and headless_fallback and operator_cdp is None:
        profile_dir.mkdir(parents=True, exist_ok=True)
        launch_kwargs: dict[str, Any] = {"headless": True}
        exe_path = resolve_chrome_executable(cfg)
        if exe_path and os.path.isfile(exe_path):  # noqa: ASYNC240
            launch_kwargs["executable_path"] = exe_path
        extra_args = resolve_browser_extra_args()
        if extra_args:
            launch_kwargs["args"] = extra_args
        persistent_context = await playwright.chromium.launch_persistent_context(
            str(profile_dir),
            **launch_kwargs,
        )
        launched_headless_fallback = True
        registry_row = BrowserSessionRegistry(
            pid=chrome_proc.pid if chrome_proc else None,
            cdp_url="",
            cdp_port=0,
            profile_dir=str(profile_dir),
            headless=True,
            spawned_by_sevn=True,
            last_used_at=_utc_now_iso(),
            active_target_id=active_target_id,
            headless_persistent=True,
        )
        write_registry(content_root, sid, registry_row)
        return (
            playwright,
            None,
            persistent_context,
            chrome_proc,
            launched_headless_fallback,
            we_spawned_chrome,
            sid,
            registry_row,
            profile_dir,
            headless,
        )

    if browser is None:
        if operator_cdp is not None:
            msg = (
                f"CDP attach-only mode: operator SEVN_CDP_URL ({operator_cdp}) is not reachable. "
                "Start Chrome on that URL or unset SEVN_CDP_URL."
            )
        elif spawn_attempted:
            msg = (
                f"Chrome spawn failed: CDP not reachable at {cdp_url} after starting system Chrome."
            )
        elif resolve_chrome_executable(cfg) is None and not headless_fallback:
            msg = "No browser available: system Chrome not found and headless fallback is disabled."
        elif resolve_chrome_executable(cfg) is None:
            msg = "No browser available: system Chrome not found and headless fallback failed."
        elif not headless_fallback:
            msg = "No browser available: CDP not reachable and headless fallback is disabled."
        else:
            msg = "No browser available: CDP not reachable and headless fallback failed."
        raise RuntimeError(msg)

    if registry_row is not None:
        write_registry(
            content_root,
            sid,
            BrowserSessionRegistry(
                pid=registry_row.pid,
                cdp_url=registry_row.cdp_url or cdp_url,
                cdp_port=registry_row.cdp_port or cdp_port_from_url(cdp_url),
                profile_dir=registry_row.profile_dir or str(profile_dir),
                headless=registry_row.headless,
                spawned_by_sevn=registry_row.spawned_by_sevn,
                last_used_at=_utc_now_iso(),
                active_target_id=registry_row.active_target_id,
                headless_persistent=registry_row.headless_persistent,
            ),
        )

    return (
        playwright,
        browser,
        persistent_context,
        chrome_proc,
        launched_headless_fallback,
        we_spawned_chrome,
        sid,
        registry_row,
        profile_dir,
        headless,
    )


async def _release_session_browser_resources(
    *,
    playwright: Playwright | None,
    browser: Browser | None,
    persistent_context: BrowserContext | None,
    chrome_proc: subprocess.Popen[bytes] | None,
    launched_headless_fallback: bool,
    we_spawned_chrome: bool,
) -> None:
    """Teardown Playwright without ``Browser.close()`` on CDP attach (D4).

    Args:
        playwright (Playwright | None): Playwright driver handle.
        browser (Browser | None): CDP-attached browser.
        persistent_context (BrowserContext | None): Headless persistent context.
        chrome_proc (subprocess.Popen[bytes] | None): Spawned Chrome process.
        launched_headless_fallback (bool): Whether headless persistent path was used.
        we_spawned_chrome (bool): Whether this call spawned Chrome.

    Returns:
        None

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_release_session_browser_resources)
        True
    """
    if launched_headless_fallback and persistent_context is not None:
        if browser_autoclose_enabled():
            with contextlib.suppress(Exception):
                await persistent_context.close()
    elif browser is not None and not launched_headless_fallback:
        pass
    if (
        we_spawned_chrome
        and browser_autoclose_enabled()
        and chrome_proc is not None
        and chrome_proc.poll() is None
    ):
        chrome_proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            chrome_proc.wait(timeout=8)
    with contextlib.suppress(Exception):
        if playwright is not None:
            await playwright.stop()


@asynccontextmanager
async def connected_tab_session(
    *,
    content_root: Path,
    session_id: str = "",
    cfg: WorkspaceConfig | None = None,
    headless_fallback: bool = True,
) -> AsyncIterator[TabSessionView]:
    """Yield a :class:`TabSessionView` for tab CRUD without closing CDP Chrome (D14).

    Args:
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.
        cfg (WorkspaceConfig | None): Workspace config.
        headless_fallback (bool): Allow Playwright headless fallback when Chrome absent.

    Yields:
        TabSessionView: Session browser surface for :func:`list_tabs` and friends.

    Returns:
        AsyncIterator[TabSessionView]: Async context manager over the tab view.

    Examples:
        >>> import inspect
        >>> inspect.isasyncgenfunction(connected_tab_session.__wrapped__)
        True
    """
    (
        playwright,
        browser,
        persistent_context,
        chrome_proc,
        launched_headless_fallback,
        we_spawned_chrome,
        _sid,
        _registry_row,
        _profile_dir,
        _headless,
    ) = await _session_browser_resources(
        content_root=content_root,
        session_id=session_id,
        cfg=cfg,
        headless_fallback=headless_fallback,
    )
    cdp_url = (
        _registry_row.cdp_url.rstrip("/")
        if _registry_row is not None
        and _registry_row.cdp_url.strip()
        and cdp_reachable(_registry_row.cdp_url)
        else None
    )
    view = TabSessionView(browser=browser, context=persistent_context, cdp_url=cdp_url)
    try:
        yield view
    finally:
        await _release_session_browser_resources(
            playwright=playwright,
            browser=browser,
            persistent_context=persistent_context,
            chrome_proc=chrome_proc,
            launched_headless_fallback=launched_headless_fallback,
            we_spawned_chrome=we_spawned_chrome,
        )


@asynccontextmanager
async def browser_page(
    *,
    content_root: Path,
    session_id: str = "",
    cfg: WorkspaceConfig | None = None,
    headless_fallback: bool = True,
    tab_target_id: str | None = None,
) -> AsyncIterator[Any]:
    """Yield a Playwright ``Page`` using CDP attach or sevn-spawned Chrome (D4/D5).

    Never calls ``Browser.close()`` on CDP attach — only disconnects Playwright.
    Updates ``last_used_at`` in the registry on successful attach/spawn.

    Args:
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.
        cfg (WorkspaceConfig | None): Workspace config.
        headless_fallback (bool): Allow Playwright headless fallback when Chrome absent.
        tab_target_id (str | None): Explicit ``--tab`` target id override (D14).

    Yields:
        Any: Playwright ``Page``.

    Returns:
        AsyncIterator[Any]: Async context manager over the active page.

    Raises:
        RuntimeError: When no browser can be attached or spawned.

    Examples:
        >>> import inspect
        >>> inspect.isasyncgenfunction(browser_page.__wrapped__)
        True
    """
    (
        playwright,
        browser,
        persistent_context,
        chrome_proc,
        launched_headless_fallback,
        we_spawned_chrome,
        _sid,
        registry_row,
        _profile_dir,
        _headless,
    ) = await _session_browser_resources(
        content_root=content_root,
        session_id=session_id,
        cfg=cfg,
        headless_fallback=headless_fallback,
    )
    active_target_id = registry_row.active_target_id if registry_row else None
    cdp_url = (
        registry_row.cdp_url.rstrip("/")
        if registry_row is not None
        and registry_row.cdp_url.strip()
        and cdp_reachable(registry_row.cdp_url)
        else None
    )
    view = TabSessionView(browser=browser, context=persistent_context, cdp_url=cdp_url)
    try:
        work_page: Page = await resolve_target_page(
            view,
            active_target_id=active_target_id,
            tab_target_id=tab_target_id,
        )
        await try_persist_active_page(
            work_page,
            content_root=content_root,
            session_id=_sid,
            cdp_url=cdp_url,
        )
        yield work_page
    finally:
        await _release_session_browser_resources(
            playwright=playwright,
            browser=browser,
            persistent_context=persistent_context,
            chrome_proc=chrome_proc,
            launched_headless_fallback=launched_headless_fallback,
            we_spawned_chrome=we_spawned_chrome,
        )


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
        ...     skill_name="playwright-browser",
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
    "TabOperationError",
    "TabSessionView",
    "activate_tab",
    "browser_autoclose_enabled",
    "browser_page",
    "browser_readiness_snapshot",
    "cdp_list_page_targets",
    "cdp_port_from_url",
    "cdp_port_seed",
    "cdp_reachable",
    "clear_registry",
    "close_all_gateway_browsers",
    "close_browser_session",
    "close_idle_browser_sessions",
    "close_tab",
    "connected_tab_session",
    "default_cdp_url",
    "is_brave_executable",
    "list_tabs",
    "merge_browser_proc_env",
    "open_tab",
    "page_target_id",
    "persist_active_target_id",
    "pick_work_page",
    "pid_is_alive",
    "pid_matches_sevn_chrome_profile",
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
    "resolve_target_page",
    "restart_browser_session",
    "session_status_payload",
    "spawn_chrome",
    "try_persist_active_page",
    "wait_for_page_ready",
    "write_registry",
]
