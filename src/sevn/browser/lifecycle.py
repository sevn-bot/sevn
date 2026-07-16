"""Browser session lifecycle for the sevn CDP engine: attach/spawn, targets, tabs.

A :class:`CDPBrowserSession` owns one browser-level :class:`CDPConnection` plus a map
of attached page targets (``{target_id: CDPSession}``) maintained via flattened
``Target.setAutoAttach``. It reuses the shipped ``sevn.skills.browser_session``
discovery/spawn/registry layer, so ``target_id`` strings and the persisted
``active_target_id`` stay interchangeable with the rest of the codebase.

Module: sevn.browser.lifecycle
Depends: asyncio, contextlib, json, os, signal, urllib, sevn.browser.cdp,
    sevn.skills.browser_session

Exports:
    CDPBrowserSession — attach/spawn, target tracking, tab CRUD, page-session access.
    fetch_browser_ws_url — resolve the browser-level WebSocket URL from a CDP HTTP base.
    spawn_or_attach — attach to an existing CDP endpoint or spawn host Chrome (D4).
    get_or_create_session — pooled session per gateway ``session_id``.
    release_session — disconnect + evict a pooled session.
    reset_pool_for_tests — clear the pool (unit tests only).
    clear_profile_singleton_locks — delete Chrome singleton/port lockfiles.
    reap_stale_sevn_chrome — kill sevn-spawned Chrome for one profile + clear locks.
    reap_sevn_browsers_on_shutdown — terminate all sevn-spawned browsers (D6).

Examples:
    >>> import inspect
    >>> inspect.iscoroutinefunction(CDPBrowserSession.attach_ws)
    True
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from sevn.browser.cdp import CDPConnection, CDPSession
from sevn.skills.browser_session import pid_is_alive, pid_matches_sevn_chrome_profile

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig

_pool: dict[str, CDPBrowserSession] = {}
_pool_lock: asyncio.Lock | None = None
_spawn_locks: dict[str, asyncio.Lock] = {}
_spawn_locks_mu = threading.Lock()
# ~20 s adaptive CDP wait (D3); was fixed 10 s (50 * 0.2).
_SPAWN_CDP_WAIT_STEPS: Final[int] = 100
_SPAWN_CDP_WAIT_INTERVAL: Final[float] = 0.2
_PROFILE_LOCK_FILES: Final[tuple[str, ...]] = (
    "SingletonLock",
    "SingletonSocket",
    "SingletonCookie",
    "DevToolsActivePort",
)


def _get_pool_lock() -> asyncio.Lock:
    """Return the lazily-created module pool lock.

    Returns:
        asyncio.Lock: Shared pool access lock.

    Examples:
        >>> import asyncio
        >>> isinstance(_get_pool_lock(), asyncio.Lock)
        True
    """
    global _pool_lock
    if _pool_lock is None:
        _pool_lock = asyncio.Lock()
    return _pool_lock


def _spawn_lock_for(session_id: str) -> asyncio.Lock:
    """Return the per-``session_id`` spawn lock (single-flight, D5).

    Uses a threading mutex when creating entries so concurrent asyncio tasks
    cannot race two distinct locks for the same session id.

    Args:
        session_id (str): Gateway session id.

    Returns:
        asyncio.Lock: Lock shared by concurrent spawners for this session.

    Examples:
        >>> isinstance(_spawn_lock_for("s1"), asyncio.Lock)
        True
    """
    key = (session_id or "default").strip() or "default"
    with _spawn_locks_mu:
        lock = _spawn_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _spawn_locks[key] = lock
        return lock


async def _await_attach(cdp_url: str) -> CDPBrowserSession:
    """Attach to ``cdp_url`` (always awaits :meth:`CDPBrowserSession.attach`).

    Args:
        cdp_url (str): CDP HTTP base URL.

    Returns:
        CDPBrowserSession: Connected session.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_await_attach)
        True
    """
    return await CDPBrowserSession.attach(cdp_url)


def clear_profile_singleton_locks(profile_dir: Path) -> None:
    """Delete Chrome singleton and DevTools port lockfiles under ``profile_dir``.

    Args:
        profile_dir (Path): Chrome ``user-data-dir`` for this session only.

    Returns:
        None

    Examples:
        >>> import tempfile
        >>> d = Path(tempfile.mkdtemp())
        >>> _ = (d / "SingletonLock").write_text("x", encoding="utf-8")
        >>> clear_profile_singleton_locks(d)
        >>> (d / "SingletonLock").exists()
        False
    """
    for name in _PROFILE_LOCK_FILES:
        with contextlib.suppress(OSError):
            (profile_dir / name).unlink()


def reap_stale_sevn_chrome(
    content_root: Path,
    session_id: str,
    profile_dir: Path,
) -> None:
    """Kill a sevn-spawned Chrome for this profile (if live) and clear lockfiles (D1).

    Only acts on a registry PID with ``spawned_by_sevn=True`` whose recorded
    ``profile_dir`` matches ``profile_dir`` (convention 11). Never signals
    operator Chrome or another profile's process.

    Args:
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.
        profile_dir (Path): Target profile directory about to be spawned into.

    Returns:
        None

    Examples:
        >>> import inspect
        >>> inspect.isfunction(reap_stale_sevn_chrome)
        True
    """
    from sevn.skills.browser_session import read_registry

    row = read_registry(content_root, session_id)
    if (
        row is not None
        and row.spawned_by_sevn
        and row.pid is not None
        and row.pid > 0
        and row.profile_dir
    ):
        try:
            recorded = Path(row.profile_dir).expanduser().resolve()
            target = profile_dir.expanduser().resolve()
        except OSError:
            recorded = Path(row.profile_dir)
            target = profile_dir
        if (
            recorded == target
            and pid_is_alive(row.pid)
            and pid_matches_sevn_chrome_profile(row.pid, profile_dir)
        ):
            # Convention 11: cmdline still looks like sevn Chrome for this profile.
            with contextlib.suppress(OSError):
                os.kill(row.pid, signal.SIGTERM)
            # Wait like the shutdown path before clearing lockfiles (Thermos).
            for _ in range(50):
                if not pid_is_alive(row.pid):
                    break
                time.sleep(0.1)
            if pid_is_alive(row.pid) and pid_matches_sevn_chrome_profile(row.pid, profile_dir):
                with contextlib.suppress(OSError):
                    os.kill(row.pid, signal.SIGKILL)
                for _ in range(20):
                    if not pid_is_alive(row.pid):
                        break
                    time.sleep(0.05)
    clear_profile_singleton_locks(profile_dir)


def _chrome_log_path(content_root: Path, session_id: str) -> Path:
    """Return the Chrome stderr log path for ``session_id`` (D4).

    Args:
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.

    Returns:
        Path: ``<content_root>/logs/chrome-<session_id>.log``.

    Examples:
        >>> str(_chrome_log_path(Path("/ws"), "abc")).endswith("logs/chrome-abc.log")
        True
    """
    return content_root / "logs" / f"chrome-{session_id}.log"


def _chrome_log_tail(log_path: Path, *, max_chars: int = 800) -> str:
    """Return a short tail of ``log_path`` for error messages (D4).

    Args:
        log_path (Path): Chrome log file.
        max_chars (int): Maximum characters to include.

    Returns:
        str: Tail text, or empty when unreadable / missing.

    Examples:
        >>> _chrome_log_tail(Path("/no/such/chrome.log"))
        ''
    """
    if not log_path.is_file():
        return ""
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def reap_sevn_browsers_on_shutdown(content_root: Path) -> list[int]:
    """Terminate all sevn-spawned browsers recorded under ``content_root`` (D6).

    Scans ``.sevn/browser-sessions/*.json``, signals each ``spawned_by_sevn``
    PID with ``SIGTERM`` (when alive), ``wait``-analogue via brief poll, and
    clears the registry entry. Never touches non-sevn or unmatched PIDs.

    Args:
        content_root (Path): Workspace content root.

    Returns:
        list[int]: PIDs processed from sevn-spawned registry rows.

    Examples:
        >>> import tempfile
        >>> reap_sevn_browsers_on_shutdown(Path(tempfile.mkdtemp()))
        []
    """
    from sevn.skills.browser_session import clear_registry, read_registry

    sessions_dir = content_root / ".sevn" / "browser-sessions"
    if not sessions_dir.is_dir():
        return []
    processed: list[int] = []
    for path in sorted(sessions_dir.glob("*.json")):
        session_id = path.stem
        row = read_registry(content_root, session_id)
        if row is None or not row.spawned_by_sevn or row.pid is None or row.pid <= 0:
            continue
        pid = row.pid
        processed.append(pid)
        if pid_is_alive(pid):
            profile = Path(row.profile_dir) if row.profile_dir else None
            if profile is None or not pid_matches_sevn_chrome_profile(pid, profile):
                clear_registry(content_root, session_id)
                continue
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGTERM)
            # Best-effort wait so gateway restarts do not leave orphans.
            for _ in range(50):
                if not pid_is_alive(pid):
                    break
                time.sleep(0.1)
            if pid_is_alive(pid) and pid_matches_sevn_chrome_profile(pid, profile):
                with contextlib.suppress(OSError):
                    os.kill(pid, signal.SIGKILL)
        clear_registry(content_root, session_id)
        if row.profile_dir:
            with contextlib.suppress(OSError):
                clear_profile_singleton_locks(Path(row.profile_dir))
    return processed


def fetch_browser_ws_url(cdp_url: str, *, timeout: float = 5.0) -> str:
    """Resolve the browser-level WebSocket debugger URL from a CDP HTTP base.

    Args:
        cdp_url (str): CDP base URL, for example ``http://127.0.0.1:9222``.
        timeout (float): HTTP timeout in seconds.

    Returns:
        str: ``ws://...`` browser debugger URL from ``/json/version``.

    Raises:
        RuntimeError: When the endpoint is unreachable or returns no ws URL.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(fetch_browser_ws_url)
        True
    """
    version_url = f"{cdp_url.rstrip('/')}/json/version"
    try:
        with urllib.request.urlopen(version_url, timeout=timeout) as response:  # nosec B310
            raw = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        msg = f"CDP endpoint not reachable: {version_url} ({exc})"
        raise RuntimeError(msg) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"invalid /json/version payload from {version_url}"
        raise RuntimeError(msg) from exc
    ws_url = data.get("webSocketDebuggerUrl") if isinstance(data, dict) else None
    if not isinstance(ws_url, str) or not ws_url.strip():
        msg = f"no webSocketDebuggerUrl in /json/version from {cdp_url}"
        raise RuntimeError(msg)
    return ws_url.strip()


def _target_info_row(info: dict[str, Any], *, active_id: str | None) -> dict[str, object]:
    """Normalise a CDP ``targetInfo`` into the sevn tab row shape.

    Args:
        info (dict[str, Any]): CDP ``Target.TargetInfo`` object.
        active_id (str | None): Registry active target id for the ``active`` flag.

    Returns:
        dict[str, object]: Row with ``target_id``, ``url``, ``title``, ``active``.

    Examples:
        >>> _target_info_row({"targetId": "t1", "url": "u", "title": "T"}, active_id="t1")["active"]
        True
    """
    tid = str(info.get("targetId") or "")
    return {
        "target_id": tid,
        "url": str(info.get("url") or ""),
        "title": str(info.get("title") or ""),
        "active": bool(tid and tid == active_id),
    }


class CDPBrowserSession:
    """One browser-level CDP connection with attached page-target tracking.

    Never closes the operator's Chrome — :meth:`disconnect` only drops the WebSocket.
    """

    def __init__(self, connection: CDPConnection, *, cdp_url: str | None = None) -> None:
        """Bind a connected browser-level connection.

        Args:
            connection (CDPConnection): Connected browser-level CDP connection.
            cdp_url (str | None): CDP HTTP base for diagnostics, when known.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.isfunction(CDPBrowserSession.__init__)
            True
        """
        self._conn = connection
        self._cdp_url = cdp_url
        # target_id -> CDPSession (attached page sessions, kept current by auto-attach)
        self._sessions: dict[str, CDPSession] = {}
        self._session_by_sid: dict[str, CDPSession] = {}
        self._dispose_attached: Any = None
        self._dispose_detached: Any = None

    @property
    def connection(self) -> CDPConnection:
        """Return the underlying browser-level connection.

        Returns:
            CDPConnection: The shared connection.

        Examples:
            >>> import inspect
            >>> isinstance(CDPBrowserSession.connection, property)
            True
        """
        return self._conn

    @property
    def cdp_url(self) -> str | None:
        """Return the CDP HTTP base URL, when known.

        Returns:
            str | None: CDP base URL or ``None``.

        Examples:
            >>> import inspect
            >>> isinstance(CDPBrowserSession.cdp_url, property)
            True
        """
        return self._cdp_url

    @classmethod
    async def attach_ws(cls, ws_url: str, *, cdp_url: str | None = None) -> CDPBrowserSession:
        """Connect to a browser-level WebSocket and start target auto-attach.

        Args:
            ws_url (str): Browser debugger ``ws://`` URL.
            cdp_url (str | None): CDP HTTP base for diagnostics.

        Returns:
            CDPBrowserSession: Connected, discovering session.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CDPBrowserSession.attach_ws)
            True
        """
        conn = await CDPConnection.connect(ws_url)
        session = cls(conn, cdp_url=cdp_url)
        await session._start_target_tracking()
        return session

    @classmethod
    async def attach(cls, cdp_url: str) -> CDPBrowserSession:
        """Resolve the browser WS URL from ``cdp_url`` and attach.

        Args:
            cdp_url (str): CDP HTTP base, for example ``http://127.0.0.1:9222``.

        Returns:
            CDPBrowserSession: Connected session.

        Raises:
            RuntimeError: When discovery or the socket fails.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CDPBrowserSession.attach)
            True
        """
        ws_url = await asyncio.to_thread(fetch_browser_ws_url, cdp_url)
        return await cls.attach_ws(ws_url, cdp_url=cdp_url)

    async def _start_target_tracking(self) -> None:
        """Enable target discovery + flattened auto-attach and wire listeners.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CDPBrowserSession._start_target_tracking)
            True
        """
        self._dispose_attached = self._conn.on(
            "Target.attachedToTarget", self._on_attached_to_target
        )
        self._dispose_detached = self._conn.on(
            "Target.detachedFromTarget", self._on_detached_from_target
        )
        with contextlib.suppress(Exception):
            await self._conn.send("Target.setDiscoverTargets", {"discover": True})
        with contextlib.suppress(Exception):
            await self._conn.send(
                "Target.setAutoAttach",
                {"autoAttach": True, "flatten": True, "waitForDebuggerOnStart": False},
            )

    def _on_attached_to_target(self, message: dict[str, Any]) -> None:
        """Record a page session when Chrome attaches to a target.

        Args:
            message (dict[str, Any]): ``Target.attachedToTarget`` event message.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.isfunction(CDPBrowserSession._on_attached_to_target)
            True
        """
        params = message.get("params") or {}
        sid = params.get("sessionId")
        info = params.get("targetInfo") or {}
        target_id = info.get("targetId")
        if not isinstance(sid, str) or not isinstance(target_id, str):
            return
        if info.get("type") not in (None, "page", "iframe"):
            return
        session = CDPSession(self._conn, sid, target_id=target_id)
        self._sessions[target_id] = session
        self._session_by_sid[sid] = session

    def _on_detached_from_target(self, message: dict[str, Any]) -> None:
        """Drop a page session when Chrome detaches from a target.

        Args:
            message (dict[str, Any]): ``Target.detachedFromTarget`` event message.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.isfunction(CDPBrowserSession._on_detached_from_target)
            True
        """
        params = message.get("params") or {}
        sid = params.get("sessionId")
        if not isinstance(sid, str):
            return
        session = self._session_by_sid.pop(sid, None)
        if session is not None and session.target_id:
            self._sessions.pop(session.target_id, None)

    async def get_targets(self) -> list[dict[str, Any]]:
        """Return all CDP target infos (``Target.getTargets``).

        Returns:
            list[dict[str, Any]]: ``Target.TargetInfo`` objects.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CDPBrowserSession.get_targets)
            True
        """
        result = await self._conn.send("Target.getTargets")
        infos = result.get("targetInfos")
        return [i for i in infos if isinstance(i, dict)] if isinstance(infos, list) else []

    async def page_targets(self) -> list[dict[str, Any]]:
        """Return page-type target infos only.

        Returns:
            list[dict[str, Any]]: Target infos where ``type == "page"``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CDPBrowserSession.page_targets)
            True
        """
        return [t for t in await self.get_targets() if t.get("type") == "page"]

    async def list_tabs(self, *, active_id: str | None = None) -> list[dict[str, object]]:
        """List open page tabs in the sevn tab-row shape.

        Args:
            active_id (str | None): Registry active target id for the ``active`` flag.

        Returns:
            list[dict[str, object]]: Tab rows with ``target_id``, ``url``, ``title``, ``active``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CDPBrowserSession.list_tabs)
            True
        """
        return [_target_info_row(t, active_id=active_id) for t in await self.page_targets()]

    async def open_tab(self, url: str = "about:blank") -> dict[str, object]:
        """Create a new page target navigated to ``url``.

        Args:
            url (str): Initial URL (default ``about:blank``).

        Returns:
            dict[str, object]: Tab row for the new target.

        Raises:
            RuntimeError: When Chrome does not return a target id.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CDPBrowserSession.open_tab)
            True
        """
        dest = (url or "about:blank").strip() or "about:blank"
        result = await self._conn.send("Target.createTarget", {"url": dest})
        target_id = result.get("targetId")
        if not isinstance(target_id, str) or not target_id:
            msg = "Target.createTarget returned no targetId"
            raise RuntimeError(msg)
        return {"target_id": target_id, "url": dest, "title": "", "active": False}

    async def close_tab(self, target_id: str) -> dict[str, object]:
        """Close a page target by id (``Target.closeTarget``).

        Args:
            target_id (str): CDP target id to close.

        Returns:
            dict[str, object]: ``{target_id, closed}``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CDPBrowserSession.close_tab)
            True
        """
        result = await self._conn.send("Target.closeTarget", {"targetId": target_id})
        self._sessions.pop(target_id, None)
        return {"target_id": target_id, "closed": bool(result.get("success", True))}

    async def activate_tab(self, target_id: str) -> dict[str, object]:
        """Bring a page target to the front (``Target.activateTarget``).

        Args:
            target_id (str): CDP target id to activate.

        Returns:
            dict[str, object]: ``{target_id, active: True}``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CDPBrowserSession.activate_tab)
            True
        """
        await self._conn.send("Target.activateTarget", {"targetId": target_id})
        return {"target_id": target_id, "active": True}

    async def session_for(self, target_id: str) -> CDPSession:
        """Return a :class:`CDPSession` bound to ``target_id``, attaching if needed.

        Args:
            target_id (str): CDP target id to drive.

        Returns:
            CDPSession: Attached, sessionId-bound page session.

        Raises:
            RuntimeError: When attach returns no session id.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CDPBrowserSession.session_for)
            True
        """
        existing = self._sessions.get(target_id)
        if existing is not None:
            return existing
        result = await self._conn.send(
            "Target.attachToTarget", {"targetId": target_id, "flatten": True}
        )
        sid = result.get("sessionId")
        if not isinstance(sid, str) or not sid:
            msg = f"Target.attachToTarget returned no sessionId for {target_id}"
            raise RuntimeError(msg)
        session = CDPSession(self._conn, sid, target_id=target_id)
        self._sessions[target_id] = session
        self._session_by_sid[sid] = session
        return session

    async def disconnect(self) -> None:
        """Drop the WebSocket without closing operator Chrome (idempotent).

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CDPBrowserSession.disconnect)
            True
        """
        for dispose in (self._dispose_attached, self._dispose_detached):
            if callable(dispose):
                with contextlib.suppress(Exception):
                    dispose()
        self._sessions.clear()
        self._session_by_sid.clear()
        await self._conn.close()


async def spawn_or_attach(
    content_root: Path,
    session_id: str,
    *,
    cfg: WorkspaceConfig | None = None,
) -> CDPBrowserSession:
    """Attach to an existing CDP endpoint, or spawn host Chrome and attach (D4).

    Reuses ``sevn.skills.browser_session`` for URL resolution, spawn, and registry
    persistence. Never closes an operator-owned Chrome. Spawns are single-flight
    per ``session_id`` (D5); before launch, stale sevn Chrome for this profile is
    reaped and singleton/port lockfiles cleared (D1).

    Args:
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.
        cfg (WorkspaceConfig | None): Workspace config for headless/profile overrides.

    Returns:
        CDPBrowserSession: Connected session (attached or freshly spawned).

    Raises:
        RuntimeError: When neither attach nor spawn yields a reachable endpoint.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(spawn_or_attach)
        True
    """
    lock = _spawn_lock_for(session_id)
    async with lock:
        return await _spawn_or_attach_unlocked(content_root, session_id, cfg=cfg)


async def _spawn_or_attach_unlocked(
    content_root: Path,
    session_id: str,
    *,
    cfg: WorkspaceConfig | None = None,
) -> CDPBrowserSession:
    """Attach or spawn without taking the per-session lock (caller holds it).

    Args:
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.
        cfg (WorkspaceConfig | None): Workspace config overrides.

    Returns:
        CDPBrowserSession: Connected session.

    Raises:
        RuntimeError: When CDP never becomes reachable after spawn + one retry.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_spawn_or_attach_unlocked)
        True
    """
    from datetime import UTC, datetime

    from sevn.skills.browser_session import (
        BrowserSessionRegistry,
        cdp_port_seed,
        cdp_reachable,
        clear_registry,
        default_cdp_url,
        read_devtools_active_port,
        read_registry,
        resolve_browser_headless,
        resolve_profile_dir,
        spawn_chrome,
        write_registry,
    )

    # Attach only to a real operator override or a persisted registry URL — never
    # the deterministic seed-hint URL (which is not a live browser).
    operator = default_cdp_url()
    if operator and cdp_reachable(operator):
        return await _await_attach(operator)
    row = read_registry(content_root, session_id)
    if row is not None and row.cdp_url.strip() and cdp_reachable(row.cdp_url):
        return await _await_attach(row.cdp_url.rstrip("/"))

    profile_dir = resolve_profile_dir(content_root, session_id, cfg=cfg)
    headless = resolve_browser_headless(cfg)
    seed = cdp_port_seed(session_id)
    log_path = _chrome_log_path(content_root, session_id)
    log_dir = log_path.parent

    last_error = ""
    for attempt in range(2):
        reap_stale_sevn_chrome(content_root, session_id, profile_dir)
        spawn_wall = time.time()

        def _spawn() -> tuple[Any, int, str]:
            return spawn_chrome(
                profile_dir,
                headless=headless,
                seed_port=seed,
                cfg=cfg,
                session_id=session_id,
                log_dir=log_dir,
            )

        proc, port, spawned_url = await asyncio.to_thread(_spawn)
        reachable = False
        for _ in range(_SPAWN_CDP_WAIT_STEPS):
            fresh_port = await asyncio.to_thread(
                read_devtools_active_port,
                profile_dir,
                spawned_after=spawn_wall,
            )
            if fresh_port is not None:
                spawned_url = f"http://127.0.0.1:{fresh_port}"
                port = fresh_port
            if cdp_reachable(spawned_url):
                reachable = True
                break
            if proc.poll() is not None:
                # Chrome already exited — no point burning the full CDP ceiling.
                break
            await asyncio.sleep(_SPAWN_CDP_WAIT_INTERVAL)
        if reachable:
            write_registry(
                content_root,
                session_id,
                BrowserSessionRegistry(
                    pid=proc.pid,
                    cdp_url=spawned_url,
                    cdp_port=port,
                    profile_dir=str(profile_dir),
                    headless=headless,
                    spawned_by_sevn=True,
                    last_used_at=datetime.now(tz=UTC).isoformat(),
                ),
            )
            return await _await_attach(spawned_url)

        # D3: terminate + wait(timeout=5), then exactly one clean retry.
        if proc.poll() is None:
            with contextlib.suppress(Exception):
                proc.terminate()
            with contextlib.suppress(Exception):
                await asyncio.to_thread(proc.wait, timeout=5)
        clear_registry(content_root, session_id)
        tail = _chrome_log_tail(log_path)
        last_error = (
            f"NO_CDP: CDP not reachable after spawn at {spawned_url} "
            f"(chrome log: {log_path}" + (f"; tail: {tail}" if tail else "") + ")"
        )
        if attempt == 0:
            continue
        raise RuntimeError(last_error)
    raise RuntimeError(last_error or "NO_CDP: CDP not reachable after spawn")


async def get_or_create_session(
    content_root: Path,
    session_id: str,
    *,
    cfg: WorkspaceConfig | None = None,
) -> CDPBrowserSession:
    """Return a pooled session for ``session_id`` or attach/spawn a new one.

    Args:
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id (pool key).
        cfg (WorkspaceConfig | None): Workspace config overrides.

    Returns:
        CDPBrowserSession: Pooled connected session.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(get_or_create_session)
        True
    """
    key = (session_id or "default").strip() or "default"
    async with _get_pool_lock():
        existing = _pool.get(key)
        if existing is not None and not existing.connection.closed:
            return existing
        session = await spawn_or_attach(content_root, key, cfg=cfg)
        _pool[key] = session
        return session


async def release_session(session_id: str) -> None:
    """Disconnect and evict the pooled session for ``session_id``.

    Args:
        session_id (str): Gateway session id.

    Returns:
        None

    Examples:
        >>> import asyncio
        >>> asyncio.run(release_session("missing"))
    """
    key = (session_id or "default").strip() or "default"
    async with _get_pool_lock():
        session = _pool.pop(key, None)
    if session is not None:
        await session.disconnect()


def reset_pool_for_tests() -> None:
    """Clear the session pool without disconnecting (unit tests only).

    Returns:
        None

    Examples:
        >>> reset_pool_for_tests()
        >>> True
        True
    """
    _pool.clear()
    _spawn_locks.clear()


__all__ = [
    "CDPBrowserSession",
    "clear_profile_singleton_locks",
    "fetch_browser_ws_url",
    "get_or_create_session",
    "pid_is_alive",
    "reap_sevn_browsers_on_shutdown",
    "reap_stale_sevn_chrome",
    "release_session",
    "reset_pool_for_tests",
    "spawn_or_attach",
]
