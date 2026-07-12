"""Browser session lifecycle for the sevn CDP engine: attach/spawn, targets, tabs.

A :class:`CDPBrowserSession` owns one browser-level :class:`CDPConnection` plus a map
of attached page targets (``{target_id: CDPSession}``) maintained via flattened
``Target.setAutoAttach``. It reuses the shipped ``sevn.skills.browser_session``
discovery/spawn/registry layer, so ``target_id`` strings and the persisted
``active_target_id`` stay interchangeable with the rest of the codebase.

Module: sevn.browser.lifecycle
Depends: asyncio, contextlib, json, urllib, sevn.browser.cdp, sevn.skills.browser_session

Exports:
    CDPBrowserSession — attach/spawn, target tracking, tab CRUD, page-session access.
    fetch_browser_ws_url — resolve the browser-level WebSocket URL from a CDP HTTP base.
    spawn_or_attach — attach to an existing CDP endpoint or spawn host Chrome (D4).
    get_or_create_session — pooled session per gateway ``session_id``.
    release_session — disconnect + evict a pooled session.
    reset_pool_for_tests — clear the pool (unit tests only).

Examples:
    >>> import inspect
    >>> inspect.iscoroutinefunction(CDPBrowserSession.attach_ws)
    True
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any, Final

from sevn.browser.cdp import CDPConnection, CDPSession

if TYPE_CHECKING:
    from pathlib import Path

    from sevn.config.workspace_config import WorkspaceConfig

_pool: dict[str, CDPBrowserSession] = {}
_pool_lock: asyncio.Lock | None = None
_SPAWN_CDP_WAIT_STEPS: Final[int] = 50
_SPAWN_CDP_WAIT_INTERVAL: Final[float] = 0.2


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
    persistence. Never closes an operator-owned Chrome.

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
    from sevn.skills.browser_session import (
        BrowserSessionRegistry,
        cdp_port_seed,
        cdp_reachable,
        resolve_browser_headless,
        resolve_cdp_url,
        resolve_profile_dir,
        spawn_chrome,
        write_registry,
    )

    cdp_url = resolve_cdp_url(content_root, session_id, cfg)
    if cdp_reachable(cdp_url):
        return await CDPBrowserSession.attach(cdp_url)

    profile_dir = resolve_profile_dir(content_root, session_id, cfg=cfg)
    headless = resolve_browser_headless(cfg)
    seed = cdp_port_seed(session_id)
    proc, port, spawned_url = await asyncio.to_thread(
        spawn_chrome,
        profile_dir,
        headless=headless,
        seed_port=seed,
        cfg=cfg,
    )
    for _ in range(_SPAWN_CDP_WAIT_STEPS):
        if cdp_reachable(spawned_url):
            break
        await asyncio.sleep(_SPAWN_CDP_WAIT_INTERVAL)
    if not cdp_reachable(spawned_url):
        if proc.poll() is None:
            proc.terminate()
        msg = f"CDP not reachable after spawn at {spawned_url}"
        raise RuntimeError(msg)
    from datetime import UTC, datetime

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
    return await CDPBrowserSession.attach(spawned_url)


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


__all__ = [
    "CDPBrowserSession",
    "fetch_browser_ws_url",
    "get_or_create_session",
    "release_session",
    "reset_pool_for_tests",
    "spawn_or_attach",
]
