"""W2 tests: CDP lifecycle — target tracking, tab CRUD, page sessions, pool."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from sevn.browser import lifecycle
from sevn.browser.cdp import CDPSession
from sevn.browser.lifecycle import (
    CDPBrowserSession,
    fetch_browser_ws_url,
    get_or_create_session,
    release_session,
    reset_pool_for_tests,
)

if TYPE_CHECKING:
    from pathlib import Path

    from tests.browser.conftest import FakeCDPServer


async def test_attach_and_auto_attach_event(fake_cdp: FakeCDPServer) -> None:
    """Auto-attach events populate the page-session map."""
    session = await CDPBrowserSession.attach_ws(fake_cdp.ws_url)
    try:
        await fake_cdp.push_event(
            "Target.attachedToTarget",
            {"sessionId": "S1", "targetInfo": {"targetId": "t1", "type": "page"}},
        )
        await asyncio.sleep(0.05)
        page = await session.session_for("t1")
        assert isinstance(page, CDPSession)
        assert page.session_id == "S1"
        assert page.target_id == "t1"
    finally:
        await session.disconnect()


async def test_detach_event_drops_session(fake_cdp: FakeCDPServer) -> None:
    """A detach event removes the tracked page session."""
    session = await CDPBrowserSession.attach_ws(fake_cdp.ws_url)
    try:
        await fake_cdp.push_event(
            "Target.attachedToTarget",
            {"sessionId": "S2", "targetInfo": {"targetId": "t2", "type": "page"}},
        )
        await asyncio.sleep(0.05)
        await fake_cdp.push_event("Target.detachedFromTarget", {"sessionId": "S2"})
        await asyncio.sleep(0.05)
        # No longer tracked: session_for must re-attach via the protocol.
        fake_cdp.set_result("Target.attachToTarget", {"sessionId": "S2-new"})
        page = await session.session_for("t2")
        assert page.session_id == "S2-new"
    finally:
        await session.disconnect()


async def test_list_tabs_filters_pages(fake_cdp: FakeCDPServer) -> None:
    """list_tabs returns only page targets in the sevn row shape."""
    fake_cdp.set_result(
        "Target.getTargets",
        {
            "targetInfos": [
                {"targetId": "p1", "type": "page", "url": "https://a", "title": "A"},
                {"targetId": "bg", "type": "background_page", "url": "x", "title": "bg"},
                {"targetId": "p2", "type": "page", "url": "https://b", "title": "B"},
            ]
        },
    )
    session = await CDPBrowserSession.attach_ws(fake_cdp.ws_url)
    try:
        tabs = await session.list_tabs(active_id="p2")
        ids = [t["target_id"] for t in tabs]
        assert ids == ["p1", "p2"]
        assert tabs[1]["active"] is True
        assert tabs[0]["active"] is False
        assert tabs[0]["title"] == "A"
    finally:
        await session.disconnect()


async def test_open_close_activate_tab(fake_cdp: FakeCDPServer) -> None:
    """Tab CRUD maps to the Target.* commands and returns rows."""
    fake_cdp.set_result("Target.createTarget", {"targetId": "new-1"})
    fake_cdp.set_result("Target.closeTarget", {"success": True})
    fake_cdp.set_result("Target.activateTarget", {})
    session = await CDPBrowserSession.attach_ws(fake_cdp.ws_url)
    try:
        opened = await session.open_tab("https://example.com")
        assert opened["target_id"] == "new-1"
        assert opened["url"] == "https://example.com"

        closed = await session.close_tab("new-1")
        assert closed == {"target_id": "new-1", "closed": True}

        activated = await session.activate_tab("p9")
        assert activated == {"target_id": "p9", "active": True}

        created = [m for m in fake_cdp.received if m.get("method") == "Target.createTarget"]
        assert created[0]["params"]["url"] == "https://example.com"
    finally:
        await session.disconnect()


async def test_session_for_attaches_on_demand(fake_cdp: FakeCDPServer) -> None:
    """session_for attaches a target not yet in the map."""
    fake_cdp.set_result("Target.attachToTarget", {"sessionId": "SX"})
    session = await CDPBrowserSession.attach_ws(fake_cdp.ws_url)
    try:
        page = await session.session_for("t-unknown")
        assert page.session_id == "SX"
        attach = [m for m in fake_cdp.received if m.get("method") == "Target.attachToTarget"]
        assert attach[0]["params"] == {"targetId": "t-unknown", "flatten": True}
        # Second call is cached (no second attach command).
        again = await session.session_for("t-unknown")
        assert again is page
        attach2 = [m for m in fake_cdp.received if m.get("method") == "Target.attachToTarget"]
        assert len(attach2) == 1
    finally:
        await session.disconnect()


def test_fetch_browser_ws_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """fetch_browser_ws_url parses webSocketDebuggerUrl from /json/version."""
    import io
    import json as _json

    payload = _json.dumps({"webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/abc"})

    class _Resp(io.BytesIO):
        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *_a: object) -> None:
            self.close()

    def _fake_urlopen(url: str, *, timeout: float = 5.0) -> _Resp:
        return _Resp(payload.encode())

    monkeypatch.setattr(lifecycle.urllib.request, "urlopen", _fake_urlopen)
    url = fetch_browser_ws_url("http://127.0.0.1:9222")
    assert url == "ws://127.0.0.1:9222/devtools/browser/abc"


def test_fetch_browser_ws_url_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """fetch_browser_ws_url raises RuntimeError on a bad endpoint."""

    def _boom(url: str, *, timeout: float = 5.0) -> object:
        raise OSError("refused")

    monkeypatch.setattr(lifecycle.urllib.request, "urlopen", _boom)
    with pytest.raises(RuntimeError):
        fetch_browser_ws_url("http://127.0.0.1:1")


async def test_pool_reuses_and_releases(
    monkeypatch: pytest.MonkeyPatch, fake_cdp: FakeCDPServer, tmp_path: Path
) -> None:
    """get_or_create_session pools per session id; release evicts it."""
    reset_pool_for_tests()
    created = 0

    async def _fake_spawn_or_attach(
        content_root: Path, session_id: str, *, cfg: object = None
    ) -> CDPBrowserSession:
        nonlocal created
        created += 1
        return await CDPBrowserSession.attach_ws(fake_cdp.ws_url)

    monkeypatch.setattr(lifecycle, "spawn_or_attach", _fake_spawn_or_attach)
    try:
        s1 = await get_or_create_session(tmp_path, "conv-1")
        s2 = await get_or_create_session(tmp_path, "conv-1")
        assert s1 is s2
        assert created == 1
        await release_session("conv-1")
        s3 = await get_or_create_session(tmp_path, "conv-1")
        assert s3 is not s1
        assert created == 2
    finally:
        await release_session("conv-1")
        reset_pool_for_tests()
