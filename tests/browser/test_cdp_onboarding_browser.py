"""W10.2 tests: CDPOnboardingBrowser contract + Tab shim over fake CDP."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sevn.browser.lifecycle import CDPBrowserSession
from sevn.onboarding.cdp_browser import CDPOnboardingBrowser

if TYPE_CHECKING:
    import pytest
    from tests.browser.conftest import FakeCDPServer


def _patch_attach(monkeypatch: pytest.MonkeyPatch, fake_cdp: FakeCDPServer) -> None:
    """Make start() attach to the fake CDP server instead of real Chrome."""

    async def _fake_attach(_url: str) -> CDPBrowserSession:
        return await CDPBrowserSession.attach_ws(fake_cdp.ws_url)

    monkeypatch.setattr("sevn.skills.browser_session.cdp_reachable", lambda *_a, **_k: True)
    monkeypatch.setattr(CDPBrowserSession, "attach", _fake_attach)


async def test_start_binds_active_tab_and_status(
    monkeypatch: pytest.MonkeyPatch, fake_cdp: FakeCDPServer
) -> None:
    """start() attaches the engine, binds the active tab, and reports engine=cdp."""
    fake_cdp.set_result("Target.getTargets", {"targetInfos": [{"targetId": "p1", "type": "page"}]})
    fake_cdp.set_result("Target.attachToTarget", {"sessionId": "S1"})
    _patch_attach(monkeypatch, fake_cdp)
    browser = CDPOnboardingBrowser()
    try:
        status = await browser.start(cdp_url="http://127.0.0.1:9222")
        assert status["running"] is True
        assert status["browser_engine"] == "cdp"
        assert browser.running is True
    finally:
        await browser.stop()
        assert browser.running is False


async def test_resolve_tab_shim_evaluate_and_select(
    monkeypatch: pytest.MonkeyPatch, fake_cdp: FakeCDPServer
) -> None:
    """_resolve_tab returns a shim supporting evaluate + select + send_keys."""
    fake_cdp.set_result("Target.getTargets", {"targetInfos": [{"targetId": "p1", "type": "page"}]})
    fake_cdp.set_result("Target.attachToTarget", {"sessionId": "S1"})
    fake_cdp.set_result("Runtime.evaluate", {"result": {"value": True}})
    fake_cdp.set_result("DOM.getDocument", {"root": {"nodeId": 1}})
    fake_cdp.set_result("DOM.querySelector", {"nodeId": 7})
    fake_cdp.set_result("DOM.focus", {})
    fake_cdp.set_result("Input.insertText", {})
    _patch_attach(monkeypatch, fake_cdp)
    browser = CDPOnboardingBrowser()
    try:
        await browser.start(cdp_url="http://127.0.0.1:9222")
        tab = browser._resolve_tab()
        assert await tab.evaluate("document.title") is True
        element = await tab.select("#composer", timeout=1.0)
        assert element is not None
        await element.send_keys("hi")
        ins = [m for m in fake_cdp.received if m.get("method") == "Input.insertText"]
        assert any(m["params"].get("text") == "hi" for m in ins)
    finally:
        await browser.stop()


async def test_press_enter_dispatches_keys(
    monkeypatch: pytest.MonkeyPatch, fake_cdp: FakeCDPServer
) -> None:
    """press_enter dispatches keyDown + keyUp for Enter on the active page."""
    fake_cdp.set_result("Target.getTargets", {"targetInfos": [{"targetId": "p1", "type": "page"}]})
    fake_cdp.set_result("Target.attachToTarget", {"sessionId": "S1"})
    fake_cdp.set_result("Input.dispatchKeyEvent", {})
    _patch_attach(monkeypatch, fake_cdp)
    browser = CDPOnboardingBrowser()
    try:
        await browser.start(cdp_url="http://127.0.0.1:9222")
        await browser.press_enter()
        keys = [m for m in fake_cdp.received if m.get("method") == "Input.dispatchKeyEvent"]
        assert [k["params"]["type"] for k in keys] == ["keyDown", "keyUp"]
        assert keys[0]["params"]["key"] == "Enter"
    finally:
        await browser.stop()


def test_get_browser_session_returns_cdp_implementation() -> None:
    """get_browser_session always returns the CDP adapter."""
    import sevn.onboarding.browser_automation as ba

    ba.reset_browser_session_for_tests()
    session = ba.get_browser_session()
    assert isinstance(session, CDPOnboardingBrowser)
    ba.reset_browser_session_for_tests()


async def test_get_browser_session_list_tabs_and_new_tab(
    monkeypatch: pytest.MonkeyPatch, fake_cdp: FakeCDPServer
) -> None:
    """Factory session supports list/new tab/extract/open_url on mocked CDP."""
    fake_cdp.set_result("Target.getTargets", {"targetInfos": [{"targetId": "p1", "type": "page"}]})
    fake_cdp.set_result("Target.attachToTarget", {"sessionId": "S1"})
    fake_cdp.set_result("Target.createTarget", {"targetId": "p2"})
    fake_cdp.set_result("Page.navigate", {})
    fake_cdp.set_result(
        "Runtime.evaluate", {"result": {"value": "<html><body>Hello world</body></html>"}}
    )
    fake_cdp.set_result("DOM.getDocument", {"root": {"nodeId": 1}})
    fake_cdp.set_result("DOM.querySelector", {"nodeId": 7})
    _patch_attach(monkeypatch, fake_cdp)
    import sevn.onboarding.browser_automation as ba

    ba.reset_browser_session_for_tests()
    session = ba.get_browser_session()
    await session.start(cdp_url="http://127.0.0.1:9222")
    try:
        tabs = session.list_tabs()
        assert len(tabs) >= 1
        opened = await session.new_tab("https://telegram.org")
        assert opened["target_id"]
        text = await session.extract_text()
        assert isinstance(text, str)
        await session.open_url("https://example.com/page")
    finally:
        await session.stop()
        ba.reset_browser_session_for_tests()


async def test_get_browser_session_context_manager(
    monkeypatch: pytest.MonkeyPatch, fake_cdp: FakeCDPServer
) -> None:
    """Async context manager starts and stops the factory CDP session."""
    fake_cdp.set_result("Target.getTargets", {"targetInfos": [{"targetId": "p1", "type": "page"}]})
    fake_cdp.set_result("Target.attachToTarget", {"sessionId": "S1"})
    _patch_attach(monkeypatch, fake_cdp)
    import sevn.onboarding.browser_automation as ba

    ba.reset_browser_session_for_tests()
    async with ba.get_browser_session() as session:
        assert session.running
    assert not session.running
    ba.reset_browser_session_for_tests()
