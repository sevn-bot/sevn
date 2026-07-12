"""W6 tests: auth login-state, credential login, human handoff, cookie portability."""

from __future__ import annotations

import asyncio
import base64
import json
from typing import TYPE_CHECKING, Any

import pytest

from sevn.browser.auth import (
    AuthError,
    export_cookies,
    human_handoff,
    import_cookies,
    login,
    login_state,
    resolve_login_credentials,
    resume_login,
    site_profile,
)
from sevn.browser.cdp import CDPConnection, CDPSession
from sevn.browser.element import Dom
from sevn.browser.page import Page

if TYPE_CHECKING:
    from pathlib import Path

    from tests.browser.conftest import FakeCDPServer


def _eval_responder(
    *, logged_in: bool = False, login: bool = False, challenge: bool = False
) -> Any:
    """Build a Runtime.evaluate responder driven by fixture marker class names."""

    def _responder(msg: dict[str, Any]) -> dict[str, Any]:
        expr = msg.get("params", {}).get("expression", "")
        if logged_in and any(m in expr for m in ("avatar", "chatlist", "column-left", "Account")):
            return {"result": {"value": True}}
        if challenge and any(m in expr for m in ("qr", "captcha", "two-factor", "challenge")):
            return {"result": {"value": True}}
        if login and any(m in expr for m in ("password", "login-form", "identifierId")):
            return {"result": {"value": True}}
        return {"result": {"value": False}}

    return _responder


async def _page_dom(fake_cdp: FakeCDPServer) -> tuple[Page, Dom, CDPConnection]:
    conn = await CDPConnection.connect(fake_cdp.ws_url)
    session = CDPSession(conn)
    return Page(session), Dom(session), conn


async def test_login_state_logged_in(fake_cdp: FakeCDPServer) -> None:
    """login_state reports logged_in when logged-in markers match."""
    fake_cdp.on_command("Runtime.evaluate", _eval_responder(logged_in=True))
    page, _dom, conn = await _page_dom(fake_cdp)
    try:
        out = await login_state(page, "telegram")
        assert out["logged_in"] is True
        assert out["state"] == "logged_in"
    finally:
        await conn.close()


async def test_login_state_logged_out(fake_cdp: FakeCDPServer) -> None:
    """login_state reports logged_out when only login-form markers match."""
    fake_cdp.on_command("Runtime.evaluate", _eval_responder(login=True))
    page, _dom, conn = await _page_dom(fake_cdp)
    try:
        out = await login_state(page, "generic")
        assert out["logged_in"] is False
        assert out["state"] == "logged_out"
    finally:
        await conn.close()


async def test_login_state_human_challenge(fake_cdp: FakeCDPServer) -> None:
    """login_state reports human_required when challenge markers match."""
    fake_cdp.on_command("Runtime.evaluate", _eval_responder(challenge=True))
    page, _dom, conn = await _page_dom(fake_cdp)
    try:
        out = await login_state(page, "telegram")
        assert out["logged_in"] is False
        assert out["state"] == "human_required"
    finally:
        await conn.close()


async def test_human_handoff_envelope_no_secrets(
    fake_cdp: FakeCDPServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """human_handoff returns HUMAN_REQUIRED without echoing credential material."""
    secret = "super-secret-password"
    monkeypatch.setenv("browser.login.test.password", secret)
    fake_cdp.set_result("Page.captureScreenshot", {"data": base64.b64encode(b"png").decode()})
    fake_cdp.set_result("Runtime.evaluate", {"result": {"value": "https://example.com/login"}})
    page, _dom, conn = await _page_dom(fake_cdp)
    try:
        out = await human_handoff(page, "scan the QR code", tmp_path, "sess-1")
        assert out["human_required"] is True
        assert out["code"] == "HUMAN_REQUIRED"
        assert out["operator_message"] == "scan the QR code"
        blob = json.dumps(out)
        assert secret not in blob
        assert "super-secret" not in blob
    finally:
        await conn.close()


async def test_login_human_handoff_after_submit(
    fake_cdp: FakeCDPServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """login returns HUMAN_REQUIRED when challenge markers appear after submit."""

    def _state(msg: dict[str, Any]) -> dict[str, Any]:
        expr = msg.get("params", {}).get("expression", "")
        if "chatlist" in expr or "column-left" in expr:
            return {"result": {"value": False}}
        if "qr" in expr or "login-page" in expr:
            return {"result": {"value": True}}
        if "password" in expr:
            return {"result": {"value": True}}
        return {"result": {"value": False}}

    fake_cdp.on_command("Runtime.evaluate", _state)
    fake_cdp.set_result("Page.navigate", {"frameId": "f1"})
    fake_cdp.set_result("Page.captureScreenshot", {"data": base64.b64encode(b"png").decode()})
    fake_cdp.set_result("DOM.getDocument", {"root": {"nodeId": 1}})
    fake_cdp.set_result("DOM.querySelector", {"nodeId": 2})
    fake_cdp.set_result("DOM.focus", {})
    fake_cdp.set_result("DOM.resolveNode", {"object": {"objectId": "o1"}})
    fake_cdp.set_result("Input.insertText", {})
    fake_cdp.set_result("DOM.requestNode", {"nodeId": 3})
    fake_cdp.set_result("DOM.scrollIntoViewIfNeeded", {})
    fake_cdp.set_result("DOM.getBoxModel", {"model": {"content": [0, 0, 4, 0, 4, 4, 0, 4]}})
    fake_cdp.set_result("Input.dispatchMouseEvent", {})
    fake_cdp.set_result("Runtime.callFunctionOn", {"result": {"value": None}})

    creds = json.dumps({"identifier": "user@example.com", "password": "never-log-me"})
    monkeypatch.setenv("browser.login.telegram", creds)
    page, dom, conn = await _page_dom(fake_cdp)
    try:
        task = asyncio.ensure_future(
            login(page, dom, "telegram", "browser.login.telegram", tmp_path, "sess-tg")
        )
        await asyncio.sleep(0.05)
        await fake_cdp.push_event("Page.loadEventFired", {})
        out = await asyncio.wait_for(task, timeout=3.0)
        assert out["human_required"] is True
        assert out["code"] == "HUMAN_REQUIRED"
        out_blob = json.dumps(out)
        assert "never-log-me" not in out_blob
        assert "user@example.com" not in out_blob
    finally:
        await conn.close()


async def test_resume_login_logged_in(fake_cdp: FakeCDPServer, tmp_path: Path) -> None:
    """resume_login succeeds when login_state reports logged_in."""
    fake_cdp.on_command("Runtime.evaluate", _eval_responder(logged_in=True))
    page, _dom, conn = await _page_dom(fake_cdp)
    try:
        out = await resume_login(page, "telegram", tmp_path, "sess-2")
        assert out["logged_in"] is True
    finally:
        await conn.close()


async def test_cookies_export_import(fake_cdp: FakeCDPServer, tmp_path: Path) -> None:
    """export_cookies writes JSON; import_cookies loads via Network.setCookies."""
    fake_cdp.set_result("Network.getAllCookies", {"cookies": [{"name": "sid", "value": "abc"}]})
    fake_cdp.set_result("Network.setCookies", {})
    page, _dom, conn = await _page_dom(fake_cdp)
    dest = tmp_path / "cookies.json"
    try:
        exported = await export_cookies(page, dest)
        assert exported["exported"] == 1
        assert dest.is_file()
        loaded = json.loads(dest.read_text())
        assert loaded[0]["name"] == "sid"
        imported = await import_cookies(page, dest)
        assert imported["imported"] == 1
        set_calls = [m for m in fake_cdp.received if m.get("method") == "Network.setCookies"]
        assert set_calls
    finally:
        await conn.close()


async def test_resolve_credentials_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """resolve_login_credentials parses a JSON blob secret."""
    blob = json.dumps({"identifier": "a@b.c", "password": "pw"})
    monkeypatch.setenv("browser.login.demo", blob)
    ident, password = await resolve_login_credentials(tmp_path, "browser.login.demo")
    assert ident == "a@b.c"
    assert password == "pw"


async def test_resolve_credentials_missing_raises(tmp_path: Path) -> None:
    """resolve_login_credentials raises AuthError when secrets are absent."""
    with pytest.raises(AuthError):
        await resolve_login_credentials(tmp_path, "missing.ref")


def test_site_profile_telegram() -> None:
    """telegram site profile points at web.telegram.org."""
    profile = site_profile("telegram")
    assert "telegram.org" in profile.login_url
