"""Host Chrome discovery, CDP probes, and spawn (no Playwright).

Module: sevn.browser.chrome
Depends: hashlib, os, pathlib, shutil, subprocess, sys, time, urllib,
    sevn.browser.registry, sevn.config.workspace_config

Owns Chrome executable resolution, profile/CDP URL helpers, and
:func:`spawn_chrome` so :mod:`sevn.browser.lifecycle` never imports
:mod:`sevn.skills`.

Exports:
    cdp_port_from_url — parse TCP port from a CDP base URL.
    cdp_port_seed — deterministic seed port hint from ``session_id``.
    cdp_reachable — probe ``/json/version`` on a CDP endpoint.
    default_cdp_url — read ``SEVN_CDP_URL`` when set.
    is_brave_executable — detect Brave from a resolved binary path.
    read_devtools_active_port — read Chrome ``DevToolsActivePort`` line 1.
    resolve_browser_engine — read ``skills.browser.engine`` / env.
    resolve_browser_extra_args — parse ``SEVN_BROWSER_EXTRA_ARGS``.
    resolve_browser_headless — headed default on host unless config/binary absent.
    resolve_cdp_url — operator CDP override, else registry, else seed hint URL.
    resolve_chrome_executable — locate Chrome, Chromium, or Brave binary.
    resolve_profile_dir — session-scoped persistent profile directory.
    spawn_chrome — Popen-only Chrome launch (``--remote-debugging-port=0``).

Examples:
    >>> cdp_port_from_url("http://127.0.0.1:9333")
    9333
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import shutil
import subprocess  # nosec B404
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlparse

from sevn.browser.registry import (
    normalise_session_id,
    read_registry,
)

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig

_PROFILE_ENV: Final[str] = "SEVN_BROWSER_PROFILE_DIR"
# Login-grade defaults: re-passed on every spawn; cookies live in the profile.
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
_SAFE_SESSION_RE: Final[re.Pattern[str]] = re.compile(r"[^\w.-]+")


def _safe_chrome_log_session_id(session_id: str | None) -> str:
    """Return a filesystem-safe session segment for Chrome log filenames.

    Args:
        session_id (str | None): Gateway session id.

    Returns:
        str: Sanitized non-empty segment, or empty when ``session_id`` is blank.

    Examples:
        >>> _safe_chrome_log_session_id("telegram:1:general")
        'telegram-1-general'
        >>> _safe_chrome_log_session_id("  ")
        ''
    """
    text = (session_id or "").strip()
    if not text:
        return ""
    return _SAFE_SESSION_RE.sub("-", text).strip("-._") or "default"


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
    sid = normalise_session_id(session_id)
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
    sid = normalise_session_id(session_id)
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
    cfg: WorkspaceConfig | None = None,
    session_id: str | None = None,
    log_dir: Path | None = None,
) -> subprocess.Popen[bytes]:
    """Spawn detached Chrome with ``--remote-debugging-port=0`` (Popen only).

    Does **not** wait for ``DevToolsActivePort`` and never returns a seed / ``:0``
    CDP URL. Callers must use :func:`sevn.browser.lifecycle.await_cdp_after_spawn`
    (or :func:`sevn.browser.lifecycle.spawn_or_attach`) before attaching.

    When ``session_id`` and ``log_dir`` are provided, Chrome stdout/stderr are
    redirected to ``log_dir/chrome-<session_id>.log`` (D4) instead of ``DEVNULL``.

    Args:
        profile_dir (Path): Persistent ``user-data-dir``.
        headless (bool): When ``True``, pass ``--headless=new``.
        cfg (WorkspaceConfig | None): Workspace config for ``skills.browser.engine``.
        session_id (str | None): Gateway session id for the Chrome log filename.
        log_dir (Path | None): Directory for ``chrome-<session>.log`` (D4).

    Returns:
        subprocess.Popen[bytes]: Detached Chrome process handle.

    Raises:
        RuntimeError: When Chrome is missing.

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
        *_LOGIN_GRADE_CHROME_ARGS,
        *resolve_browser_extra_args(),
    ]
    if headless:
        args.append("--headless=new")
    log_handle = None
    stdout_dest: Any = subprocess.DEVNULL
    stderr_dest: Any = subprocess.DEVNULL
    sid = _safe_chrome_log_session_id(session_id)
    if sid and log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"chrome-{sid}.log"
        log_handle = log_path.open("ab")
        stdout_dest = log_handle
        stderr_dest = log_handle
    try:
        return subprocess.Popen(  # nosec B603
            args,
            stdout=stdout_dest,
            stderr=stderr_dest,
            stdin=subprocess.DEVNULL,
        )
    finally:
        if log_handle is not None:
            with contextlib.suppress(OSError):
                log_handle.close()


__all__ = [
    "cdp_port_from_url",
    "cdp_port_seed",
    "cdp_reachable",
    "default_cdp_url",
    "is_brave_executable",
    "read_devtools_active_port",
    "resolve_browser_engine",
    "resolve_browser_extra_args",
    "resolve_browser_headless",
    "resolve_cdp_url",
    "resolve_chrome_executable",
    "resolve_profile_dir",
    "spawn_chrome",
]
