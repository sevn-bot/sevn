"""W4 tests: element finders + synthetic-input interaction."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sevn.browser.cdp import CDPConnection, CDPSession
from sevn.browser.element import Dom, ElementError, ElementHandle

if TYPE_CHECKING:
    from tests.browser.conftest import FakeCDPServer


async def _conn(fake_cdp: FakeCDPServer) -> CDPConnection:
    return await CDPConnection.connect(fake_cdp.ws_url)


async def test_query_returns_handle(fake_cdp: FakeCDPServer) -> None:
    """Dom.query resolves a nodeId into an ElementHandle."""
    fake_cdp.set_result("DOM.getDocument", {"root": {"nodeId": 1}})
    fake_cdp.set_result("DOM.querySelector", {"nodeId": 7})
    conn = await _conn(fake_cdp)
    try:
        dom = Dom(CDPSession(conn))
        handle = await dom.query("#main")
        assert isinstance(handle, ElementHandle)
        qs = [m for m in fake_cdp.received if m.get("method") == "DOM.querySelector"]
        assert qs[0]["params"] == {"nodeId": 1, "selector": "#main"}
    finally:
        await conn.close()


async def test_query_miss_returns_none(fake_cdp: FakeCDPServer) -> None:
    """Dom.query returns None when nodeId is 0."""
    fake_cdp.set_result("DOM.getDocument", {"root": {"nodeId": 1}})
    fake_cdp.set_result("DOM.querySelector", {"nodeId": 0})
    conn = await _conn(fake_cdp)
    try:
        assert await Dom(CDPSession(conn)).query("#missing") is None
    finally:
        await conn.close()


async def test_query_all(fake_cdp: FakeCDPServer) -> None:
    """Dom.query_all returns one handle per nodeId."""
    fake_cdp.set_result("DOM.getDocument", {"root": {"nodeId": 1}})
    fake_cdp.set_result("DOM.querySelectorAll", {"nodeIds": [2, 3, 4]})
    conn = await _conn(fake_cdp)
    try:
        handles = await Dom(CDPSession(conn)).query_all("a")
        assert len(handles) == 3
    finally:
        await conn.close()


async def test_find_by_text(fake_cdp: FakeCDPServer) -> None:
    """Dom.find_by_text resolves a Runtime objectId into a handle."""
    fake_cdp.set_result("Runtime.evaluate", {"result": {"objectId": "obj-1"}})
    conn = await _conn(fake_cdp)
    try:
        handle = await Dom(CDPSession(conn)).find_by_text("Sign in")
        assert isinstance(handle, ElementHandle)
    finally:
        await conn.close()


async def test_click_dispatches_mouse_events(fake_cdp: FakeCDPServer) -> None:
    """click scrolls, reads the box model, and dispatches 3 mouse events at the centre."""
    fake_cdp.set_result("DOM.scrollIntoViewIfNeeded", {})
    fake_cdp.set_result("DOM.getBoxModel", {"model": {"content": [0, 0, 10, 0, 10, 10, 0, 10]}})
    fake_cdp.set_result("Input.dispatchMouseEvent", {})
    conn = await _conn(fake_cdp)
    try:
        handle = ElementHandle(CDPSession(conn), node_id=7)
        await handle.click()
        mouse = [m for m in fake_cdp.received if m.get("method") == "Input.dispatchMouseEvent"]
        types = [m["params"]["type"] for m in mouse]
        assert types == ["mouseMoved", "mousePressed", "mouseReleased"]
        assert mouse[1]["params"]["x"] == 5.0
        assert mouse[1]["params"]["y"] == 5.0
        assert mouse[1]["params"]["button"] == "left"
    finally:
        await conn.close()


async def test_click_falls_back_to_js(fake_cdp: FakeCDPServer) -> None:
    """click falls back to JS .click() when no box model is available."""
    fake_cdp.set_result("DOM.scrollIntoViewIfNeeded", {})
    fake_cdp.set_result("DOM.getBoxModel", {})  # no content quad
    fake_cdp.set_result("DOM.resolveNode", {"object": {"objectId": "o9"}})
    fake_cdp.set_result("Runtime.callFunctionOn", {"result": {"value": None}})
    conn = await _conn(fake_cdp)
    try:
        handle = ElementHandle(CDPSession(conn), node_id=7)
        await handle.click()
        calls = [m for m in fake_cdp.received if m.get("method") == "Runtime.callFunctionOn"]
        assert calls
        assert "this.click()" in calls[0]["params"]["functionDeclaration"]
        mouse = [m for m in fake_cdp.received if m.get("method") == "Input.dispatchMouseEvent"]
        assert mouse == []
    finally:
        await conn.close()


async def test_type_inserts_text(fake_cdp: FakeCDPServer) -> None:
    """type focuses then inserts text."""
    fake_cdp.set_result("DOM.focus", {})
    fake_cdp.set_result("Input.insertText", {})
    conn = await _conn(fake_cdp)
    try:
        await ElementHandle(CDPSession(conn), node_id=7).type("hello")
        ins = [m for m in fake_cdp.received if m.get("method") == "Input.insertText"]
        assert ins[0]["params"]["text"] == "hello"
    finally:
        await conn.close()


async def test_fill_clears_then_types(fake_cdp: FakeCDPServer) -> None:
    """fill focuses, clears via JS, inserts the value, and fires events."""
    fake_cdp.set_result("DOM.focus", {})
    fake_cdp.set_result("DOM.resolveNode", {"object": {"objectId": "o1"}})
    fake_cdp.set_result("Runtime.callFunctionOn", {"result": {"value": None}})
    fake_cdp.set_result("Input.insertText", {})
    conn = await _conn(fake_cdp)
    try:
        await ElementHandle(CDPSession(conn), node_id=7).fill("abc")
        ins = [m for m in fake_cdp.received if m.get("method") == "Input.insertText"]
        assert ins[0]["params"]["text"] == "abc"
        calls = [m for m in fake_cdp.received if m.get("method") == "Runtime.callFunctionOn"]
        assert len(calls) >= 2
    finally:
        await conn.close()


async def test_select_option(fake_cdp: FakeCDPServer) -> None:
    """select_option sets value via JS with the value argument."""
    fake_cdp.set_result("DOM.resolveNode", {"object": {"objectId": "o1"}})
    fake_cdp.set_result("Runtime.callFunctionOn", {"result": {"value": None}})
    conn = await _conn(fake_cdp)
    try:
        await ElementHandle(CDPSession(conn), node_id=7).select_option("opt-2")
        calls = [m for m in fake_cdp.received if m.get("method") == "Runtime.callFunctionOn"]
        assert calls[0]["params"]["arguments"] == [{"value": "opt-2"}]
    finally:
        await conn.close()


async def test_press_key_enter(fake_cdp: FakeCDPServer) -> None:
    """press_key dispatches keyDown + keyUp for a known key."""
    fake_cdp.set_result("DOM.focus", {})
    fake_cdp.set_result("Input.dispatchKeyEvent", {})
    conn = await _conn(fake_cdp)
    try:
        await ElementHandle(CDPSession(conn), node_id=7).press_key("Enter")
        keys = [m for m in fake_cdp.received if m.get("method") == "Input.dispatchKeyEvent"]
        assert [k["params"]["type"] for k in keys] == ["keyDown", "keyUp"]
        assert keys[0]["params"]["key"] == "Enter"
    finally:
        await conn.close()


async def test_press_key_unknown_raises(fake_cdp: FakeCDPServer) -> None:
    """press_key raises ElementError for an unsupported key."""
    conn = await _conn(fake_cdp)
    try:
        with pytest.raises(ElementError):
            await ElementHandle(CDPSession(conn), node_id=7).press_key("F13")
    finally:
        await conn.close()
