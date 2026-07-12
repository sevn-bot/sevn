"""W10.1 tests: Telegram Web recipe — token extraction, login state, send, BotFather."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest

from sevn.browser.cdp import CDPConnection, CDPSession
from sevn.browser.element import Dom
from sevn.browser.page import Page
from sevn.browser.recipes.base import RecipeError, validate_egress
from sevn.browser.recipes.telegram_web import (
    TELEGRAM_EGRESS,
    TelegramWeb,
    extract_bot_token,
)

if TYPE_CHECKING:
    from tests.browser.conftest import FakeCDPServer


def test_extract_bot_token() -> None:
    """A well-formed token is extracted; noise is ignored."""
    token = "123456789:" + "A" * 35
    assert extract_bot_token(f"Use this token to access the HTTP API:\n{token}") == token
    assert extract_bot_token("no token here") is None
    assert extract_bot_token("123:short") is None


def test_egress_allowlist() -> None:
    """Telegram egress permits telegram.org and rejects other hosts."""
    assert validate_egress("https://web.telegram.org/k/", allowlist=TELEGRAM_EGRESS)
    with pytest.raises(RecipeError):
        validate_egress("https://evil.example/", allowlist=TELEGRAM_EGRESS)


async def _recipe(fake_cdp: FakeCDPServer) -> tuple[TelegramWeb, CDPConnection]:
    conn = await CDPConnection.connect(fake_cdp.ws_url)
    session = CDPSession(conn)
    return TelegramWeb(Page(session), Dom(session)), conn


def _eval_branch(value_for_true: Any) -> Any:
    """Build a Runtime.evaluate responder: objectId when returnByValue is False."""

    def _responder(msg: dict[str, Any]) -> dict[str, Any]:
        if msg.get("params", {}).get("returnByValue") is False:
            return {"result": {"objectId": "obj-el"}}
        return {"result": {"value": value_for_true}}

    return _responder


async def test_logged_in_true(fake_cdp: FakeCDPServer) -> None:
    """logged_in returns True when a logged-in marker evaluates truthy."""
    fake_cdp.set_result("Runtime.evaluate", {"result": {"value": True}})
    recipe, conn = await _recipe(fake_cdp)
    try:
        assert await recipe.logged_in() is True
    finally:
        await conn.close()


async def test_login_human_required(fake_cdp: FakeCDPServer) -> None:
    """login returns a HUMAN_REQUIRED handoff when a QR marker is present."""

    def _responder(msg: dict[str, Any]) -> dict[str, Any]:
        expr = msg.get("params", {}).get("expression", "")
        # logged-in markers absent; QR login marker present.
        return {"result": {"value": "qr" in expr or "login-page" in expr}}

    fake_cdp.on_command("Runtime.evaluate", _responder)
    fake_cdp.set_result("Page.navigate", {"frameId": "f1"})
    recipe, conn = await _recipe(fake_cdp)
    try:
        task = asyncio.ensure_future(recipe.login())
        await asyncio.sleep(0.1)
        await fake_cdp.push_event("Page.loadEventFired", {})
        out = await asyncio.wait_for(task, timeout=3.0)
        assert out["human_required"] is True
        assert out["code"] == "HUMAN_REQUIRED"
    finally:
        await conn.close()


async def test_send_types_and_presses_enter(fake_cdp: FakeCDPServer) -> None:
    """send opens the chat, types into the composer, and presses Enter."""
    fake_cdp.on_command("Runtime.evaluate", _eval_branch(True))
    fake_cdp.set_result("DOM.getDocument", {"root": {"nodeId": 1}})
    fake_cdp.set_result("DOM.querySelector", {"nodeId": 5})
    fake_cdp.set_result("DOM.focus", {})
    fake_cdp.set_result("DOM.resolveNode", {"object": {"objectId": "o1"}})
    fake_cdp.set_result("DOM.requestNode", {"nodeId": 9})
    fake_cdp.set_result("DOM.scrollIntoViewIfNeeded", {})
    fake_cdp.set_result("DOM.getBoxModel", {"model": {"content": [0, 0, 4, 0, 4, 4, 0, 4]}})
    fake_cdp.set_result("Runtime.callFunctionOn", {"result": {"value": None}})
    fake_cdp.set_result("Input.insertText", {})
    fake_cdp.set_result("Input.dispatchMouseEvent", {})
    fake_cdp.set_result("Input.dispatchKeyEvent", {})
    recipe, conn = await _recipe(fake_cdp)
    try:
        out = await recipe.send("Alice", "hello there")
        assert out == {"chat": "Alice", "sent": True}
        ins = [m for m in fake_cdp.received if m.get("method") == "Input.insertText"]
        assert any(m["params"].get("text") == "hello there" for m in ins)
        keys = [m for m in fake_cdp.received if m.get("method") == "Input.dispatchKeyEvent"]
        assert any(k["params"].get("key") == "Enter" for k in keys)
    finally:
        await conn.close()


async def test_botfather_token(fake_cdp: FakeCDPServer) -> None:
    """botfather_token opens @BotFather and extracts the token from the transcript."""
    token = "987654321:" + "B" * 35
    transcript = f"Done! Congratulations. Use this token to access the HTTP API:\n{token}"

    def _responder(msg: dict[str, Any]) -> dict[str, Any]:
        if msg.get("params", {}).get("returnByValue") is False:
            return {"result": {"objectId": "obj-el"}}
        return {"result": {"value": transcript}}

    fake_cdp.on_command("Runtime.evaluate", _responder)
    fake_cdp.set_result("DOM.getDocument", {"root": {"nodeId": 1}})
    fake_cdp.set_result("DOM.querySelector", {"nodeId": 5})
    fake_cdp.set_result("DOM.focus", {})
    fake_cdp.set_result("DOM.resolveNode", {"object": {"objectId": "o1"}})
    fake_cdp.set_result("DOM.requestNode", {"nodeId": 9})
    fake_cdp.set_result("DOM.scrollIntoViewIfNeeded", {})
    fake_cdp.set_result("DOM.getBoxModel", {"model": {"content": [0, 0, 4, 0, 4, 4, 0, 4]}})
    fake_cdp.set_result("Runtime.callFunctionOn", {"result": {"value": None}})
    fake_cdp.set_result("Input.insertText", {})
    fake_cdp.set_result("Input.dispatchMouseEvent", {})
    recipe, conn = await _recipe(fake_cdp)
    try:
        out = await recipe.botfather_token()
        assert out["token"] == token
    finally:
        await conn.close()
