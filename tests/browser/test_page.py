"""W3 tests: Page primitives — navigate, evaluate, extract, screenshot, cookies, dialogs."""

from __future__ import annotations

import asyncio
import base64
from typing import TYPE_CHECKING

import pytest

from sevn.browser.cdp import CDPConnection, CDPSession
from sevn.browser.page import Page, PageError

if TYPE_CHECKING:
    from pathlib import Path

    from tests.browser.conftest import FakeCDPServer


async def _page(fake_cdp: FakeCDPServer) -> tuple[Page, CDPConnection]:
    conn = await CDPConnection.connect(fake_cdp.ws_url)
    return Page(CDPSession(conn)), conn


async def test_goto_no_wait(fake_cdp: FakeCDPServer) -> None:
    """goto issues Page.navigate and returns the frame id."""
    fake_cdp.set_result("Page.navigate", {"frameId": "f1"})
    page, conn = await _page(fake_cdp)
    try:
        out = await page.goto("https://example.com", wait_until="none")
        assert out == {"url": "https://example.com", "frame_id": "f1"}
        nav = [m for m in fake_cdp.received if m.get("method") == "Page.navigate"]
        assert nav[0]["params"]["url"] == "https://example.com"
    finally:
        await conn.close()


async def test_goto_navigation_error(fake_cdp: FakeCDPServer) -> None:
    """goto raises PageError when Chrome reports an errorText."""
    fake_cdp.set_result("Page.navigate", {"errorText": "net::ERR_NAME_NOT_RESOLVED"})
    page, conn = await _page(fake_cdp)
    try:
        with pytest.raises(PageError):
            await page.goto("https://nope.invalid", wait_until="none")
    finally:
        await conn.close()


async def test_goto_waits_for_load(fake_cdp: FakeCDPServer) -> None:
    """goto with wait_until=load resolves once loadEventFired arrives."""
    fake_cdp.set_result("Page.navigate", {"frameId": "f1"})
    page, conn = await _page(fake_cdp)
    try:
        task = asyncio.ensure_future(page.goto("https://example.com", timeout=2.0))
        await asyncio.sleep(0.1)
        assert not task.done()
        await fake_cdp.push_event("Page.loadEventFired", {"timestamp": 1.0})
        out = await asyncio.wait_for(task, timeout=2.0)
        assert out["frame_id"] == "f1"
    finally:
        await conn.close()


async def test_evaluate_returns_value(fake_cdp: FakeCDPServer) -> None:
    """evaluate returns the JSON value from Runtime.evaluate."""
    fake_cdp.set_result("Runtime.evaluate", {"result": {"type": "string", "value": "hello"}})
    page, conn = await _page(fake_cdp)
    try:
        assert await page.evaluate("1+1") == "hello"
    finally:
        await conn.close()


async def test_evaluate_raises_on_exception(fake_cdp: FakeCDPServer) -> None:
    """evaluate raises PageError when the script throws."""
    fake_cdp.set_result(
        "Runtime.evaluate",
        {"exceptionDetails": {"text": "Uncaught", "exception": {"description": "ReferenceError"}}},
    )
    page, conn = await _page(fake_cdp)
    try:
        with pytest.raises(PageError):
            await page.evaluate("boom")
    finally:
        await conn.close()


async def test_extract_text_trims_and_caps(fake_cdp: FakeCDPServer) -> None:
    """extract_text trims whitespace and caps length."""
    fake_cdp.set_result("Runtime.evaluate", {"result": {"value": "  Hello World  "}})
    page, conn = await _page(fake_cdp)
    try:
        assert await page.extract_text() == "Hello World"
        assert await page.extract_text(max_chars=5) == "Hello"
    finally:
        await conn.close()


async def test_page_state(fake_cdp: FakeCDPServer) -> None:
    """page_state aggregates url/title/excerpt."""
    fake_cdp.set_result("Runtime.evaluate", {"result": {"value": "X"}})
    page, conn = await _page(fake_cdp)
    try:
        state = await page.page_state()
        assert state["has_content"] is True
        assert state["title"] == "X"
    finally:
        await conn.close()


async def test_wait_for_selector(fake_cdp: FakeCDPServer) -> None:
    """wait_for returns True when the selector evaluates truthy."""
    fake_cdp.set_result("Runtime.evaluate", {"result": {"value": True}})
    page, conn = await _page(fake_cdp)
    try:
        assert await page.wait_for("#main", timeout=1.0) is True
    finally:
        await conn.close()


async def test_screenshot_writes_png(fake_cdp: FakeCDPServer, tmp_path: Path) -> None:
    """screenshot decodes base64 data and writes a PNG file."""
    raw = b"\x89PNG\r\n\x1a\n-fake"
    fake_cdp.set_result("Page.captureScreenshot", {"data": base64.b64encode(raw).decode()})
    page, conn = await _page(fake_cdp)
    try:
        dest = tmp_path / "shots" / "s.png"
        out = await page.screenshot(dest)
        assert out == str(dest)
        assert dest.read_bytes() == raw
    finally:
        await conn.close()


async def test_cookies_roundtrip(fake_cdp: FakeCDPServer) -> None:
    """get_cookies returns cookie objects; set_cookies submits them."""
    fake_cdp.set_result("Network.getAllCookies", {"cookies": [{"name": "sid", "value": "1"}]})
    fake_cdp.set_result("Network.setCookies", {})
    page, conn = await _page(fake_cdp)
    try:
        cookies = await page.get_cookies()
        assert cookies == [{"name": "sid", "value": "1"}]
        assert await page.set_cookies([{"name": "a", "value": "b"}]) == 1
    finally:
        await conn.close()


async def test_dialog_auto_handler(fake_cdp: FakeCDPServer) -> None:
    """A dialog-opening event triggers Page.handleJavaScriptDialog."""
    page, conn = await _page(fake_cdp)
    try:
        await page.enable_dialog_auto_handler(accept=True)
        await fake_cdp.push_event("Page.javascriptDialogOpening", {"message": "ok?"})
        await asyncio.sleep(0.05)
        handled = [m for m in fake_cdp.received if m.get("method") == "Page.handleJavaScriptDialog"]
        assert handled
        assert handled[0]["params"]["accept"] is True
    finally:
        await conn.close()
