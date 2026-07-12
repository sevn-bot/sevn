"""W1 tests: CDP transport correlation, event bus, session demux, error mapping."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from sevn.browser.cdp import CDPConnection, CDPError, CDPSession

if TYPE_CHECKING:
    from tests.browser.conftest import FakeCDPServer


async def test_send_correlates_reply(fake_cdp: FakeCDPServer) -> None:
    """A command result is returned by id correlation."""
    fake_cdp.set_result("Browser.getVersion", {"product": "FakeChrome/1.0"})
    conn = await CDPConnection.connect(fake_cdp.ws_url)
    try:
        result = await conn.send("Browser.getVersion")
        assert result["product"] == "FakeChrome/1.0"
    finally:
        await conn.close()


async def test_concurrent_sends_match_ids(fake_cdp: FakeCDPServer) -> None:
    """Concurrent commands resolve to their own replies (echo the method)."""
    fake_cdp.on_command("Echo.a", lambda _m: {"who": "a"})
    fake_cdp.on_command("Echo.b", lambda _m: {"who": "b"})
    conn = await CDPConnection.connect(fake_cdp.ws_url)
    try:
        a, b = await asyncio.gather(conn.send("Echo.a"), conn.send("Echo.b"))
        assert a["who"] == "a"
        assert b["who"] == "b"
    finally:
        await conn.close()


async def test_error_reply_raises_cdp_error(fake_cdp: FakeCDPServer) -> None:
    """An ``error`` reply becomes a :class:`CDPError`."""
    fake_cdp.set_result("DOM.querySelector", {"__error__": {"code": -32000, "message": "no node"}})
    conn = await CDPConnection.connect(fake_cdp.ws_url)
    try:
        with pytest.raises(CDPError) as excinfo:
            await conn.send("DOM.querySelector")
        assert excinfo.value.code == -32000
        assert "no node" in excinfo.value.message
    finally:
        await conn.close()


async def test_wait_for_event(fake_cdp: FakeCDPServer) -> None:
    """``wait_for`` resolves when a matching event is pushed."""
    conn = await CDPConnection.connect(fake_cdp.ws_url)
    try:
        waiter = asyncio.ensure_future(conn.wait_for("Page.loadEventFired"))
        await asyncio.sleep(0.05)
        await fake_cdp.push_event("Page.loadEventFired", {"timestamp": 1.0})
        message = await asyncio.wait_for(waiter, timeout=2.0)
        assert message["method"] == "Page.loadEventFired"
    finally:
        await conn.close()


async def test_wait_for_timeout(fake_cdp: FakeCDPServer) -> None:
    """``wait_for`` raises TimeoutError when no event arrives."""
    conn = await CDPConnection.connect(fake_cdp.ws_url)
    try:
        with pytest.raises(TimeoutError):
            await conn.wait_for("Never.happens", timeout=0.1)
    finally:
        await conn.close()


async def test_listener_receives_events(fake_cdp: FakeCDPServer) -> None:
    """A registered ``on`` listener receives pushed events; disposer removes it."""
    seen: list[dict[str, object]] = []
    conn = await CDPConnection.connect(fake_cdp.ws_url)
    try:
        dispose = conn.on("Target.targetCreated", lambda m: seen.append(m))
        await fake_cdp.push_event("Target.targetCreated", {"targetInfo": {"targetId": "t1"}})
        await asyncio.sleep(0.05)
        assert len(seen) == 1
        dispose()
        await fake_cdp.push_event("Target.targetCreated", {"targetInfo": {"targetId": "t2"}})
        await asyncio.sleep(0.05)
        assert len(seen) == 1
    finally:
        await conn.close()


async def test_session_demux(fake_cdp: FakeCDPServer) -> None:
    """A session-scoped wait_for ignores events from other sessions."""
    conn = await CDPConnection.connect(fake_cdp.ws_url)
    try:
        session = CDPSession(conn, "S1", target_id="t1")
        waiter = asyncio.ensure_future(session.wait_for("Page.frameNavigated", timeout=2.0))
        await asyncio.sleep(0.05)
        # Event for a different session must not resolve the S1 waiter.
        await fake_cdp.push_event("Page.frameNavigated", {"frame": {}}, session_id="S2")
        await asyncio.sleep(0.05)
        assert not waiter.done()
        await fake_cdp.push_event("Page.frameNavigated", {"frame": {"id": "f1"}}, session_id="S1")
        message = await asyncio.wait_for(waiter, timeout=2.0)
        assert message["sessionId"] == "S1"
    finally:
        await conn.close()


async def test_session_send_injects_session_id(fake_cdp: FakeCDPServer) -> None:
    """``CDPSession.send`` tags the request with its session id."""
    fake_cdp.set_result("Page.navigate", {"frameId": "f1"})
    conn = await CDPConnection.connect(fake_cdp.ws_url)
    try:
        session = CDPSession(conn, "SID-9")
        await session.send("Page.navigate", {"url": "https://example.com"})
        nav = [m for m in fake_cdp.received if m.get("method") == "Page.navigate"]
        assert nav
        assert nav[0].get("sessionId") == "SID-9"
    finally:
        await conn.close()


async def test_send_after_close_raises(fake_cdp: FakeCDPServer) -> None:
    """Sending on a closed connection raises RuntimeError."""
    conn = await CDPConnection.connect(fake_cdp.ws_url)
    await conn.close()
    assert conn.closed is True
    with pytest.raises(RuntimeError):
        await conn.send("Browser.getVersion")
