"""W5 tests: the sevn-native ``browser`` tool dispatch + gating + registration."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sevn.browser.lifecycle import CDPBrowserSession
from sevn.tools import browser as browser_mod
from sevn.tools.base import ToolExecutor
from sevn.tools.context import ToolContext

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from tests.browser.conftest import FakeCDPServer


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        session_id="conv-1", workspace_path=tmp_path, workspace_id="ws", registry_version=1
    )


async def _fake_session(fake_cdp: FakeCDPServer) -> CDPBrowserSession:
    return await CDPBrowserSession.attach_ws(fake_cdp.ws_url)


def _patch_session(monkeypatch: pytest.MonkeyPatch, session: CDPBrowserSession) -> None:
    async def _get(
        content_root: object, session_id: object, *, cfg: object = None
    ) -> CDPBrowserSession:
        return session

    monkeypatch.setattr(browser_mod, "_EVAL_ALLOWED", False, raising=False)
    monkeypatch.setattr("sevn.browser.lifecycle.get_or_create_session", _get)


async def test_engine_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Without the engine the tool returns ENGINE_MISSING gracefully."""
    monkeypatch.setattr(browser_mod, "HAS_CDP", False)
    out = json.loads(await browser_mod.browser_tool(_ctx(tmp_path), action="list_tabs"))
    assert out["ok"] is False
    assert "ENGINE_MISSING" in out["error"]


async def test_list_tabs(
    monkeypatch: pytest.MonkeyPatch, fake_cdp: FakeCDPServer, tmp_path: Path
) -> None:
    """list_tabs returns page targets through the tool envelope."""
    fake_cdp.set_result(
        "Target.getTargets",
        {"targetInfos": [{"targetId": "p1", "type": "page", "url": "https://a", "title": "A"}]},
    )
    session = await _fake_session(fake_cdp)
    _patch_session(monkeypatch, session)
    try:
        out = json.loads(await browser_mod.browser_tool(_ctx(tmp_path), action="list_tabs"))
        assert out["ok"] is True
        assert out["data"]["count"] == 1
        assert out["data"]["tabs"][0]["target_id"] == "p1"
    finally:
        await session.disconnect()


async def test_extract_text_active_page(
    monkeypatch: pytest.MonkeyPatch, fake_cdp: FakeCDPServer, tmp_path: Path
) -> None:
    """extract_text resolves the active page and returns text."""
    fake_cdp.set_result(
        "Target.getTargets",
        {"targetInfos": [{"targetId": "p1", "type": "page", "url": "https://a", "title": "A"}]},
    )
    fake_cdp.set_result("Target.attachToTarget", {"sessionId": "S1"})
    fake_cdp.set_result("Runtime.evaluate", {"result": {"value": "  Hi there  "}})
    session = await _fake_session(fake_cdp)
    _patch_session(monkeypatch, session)
    try:
        out = json.loads(await browser_mod.browser_tool(_ctx(tmp_path), action="extract_text"))
        assert out["ok"] is True
        assert out["data"]["text"] == "Hi there"
    finally:
        await session.disconnect()


async def test_click_via_text(
    monkeypatch: pytest.MonkeyPatch, fake_cdp: FakeCDPServer, tmp_path: Path
) -> None:
    """click resolves an element by text and dispatches the gesture."""
    fake_cdp.set_result(
        "Target.getTargets",
        {"targetInfos": [{"targetId": "p1", "type": "page"}]},
    )
    fake_cdp.set_result("Target.attachToTarget", {"sessionId": "S1"})
    fake_cdp.set_result("Runtime.evaluate", {"result": {"objectId": "obj-9"}})
    fake_cdp.set_result("DOM.requestNode", {"nodeId": 12})
    fake_cdp.set_result("DOM.scrollIntoViewIfNeeded", {})
    fake_cdp.set_result("DOM.getBoxModel", {"model": {"content": [0, 0, 8, 0, 8, 8, 0, 8]}})
    fake_cdp.set_result("Input.dispatchMouseEvent", {})
    session = await _fake_session(fake_cdp)
    _patch_session(monkeypatch, session)
    try:
        out = json.loads(
            await browser_mod.browser_tool(_ctx(tmp_path), action="click", text="Sign in")
        )
        assert out["ok"] is True
        assert out["data"]["clicked"] is True
        mouse = [m for m in fake_cdp.received if m.get("method") == "Input.dispatchMouseEvent"]
        assert [m["params"]["type"] for m in mouse] == [
            "mouseMoved",
            "mousePressed",
            "mouseReleased",
        ]
    finally:
        await session.disconnect()


async def test_eval_gated_off_by_default(tmp_path: Path) -> None:
    """eval is disabled unless the gate is set."""
    browser_mod.set_eval_allowed(False)
    out = json.loads(
        await browser_mod.browser_tool(_ctx(tmp_path), action="eval", expression="1+1")
    )
    assert out["ok"] is False
    assert "EVAL_DISABLED" in out["error"]


async def test_eval_allowed_when_gated_on(
    monkeypatch: pytest.MonkeyPatch, fake_cdp: FakeCDPServer, tmp_path: Path
) -> None:
    """eval runs when the gate is enabled."""
    fake_cdp.set_result("Target.getTargets", {"targetInfos": [{"targetId": "p1", "type": "page"}]})
    fake_cdp.set_result("Target.attachToTarget", {"sessionId": "S1"})
    fake_cdp.set_result("Runtime.evaluate", {"result": {"value": 2}})
    session = await _fake_session(fake_cdp)
    _patch_session(monkeypatch, session)
    browser_mod.set_eval_allowed(True)
    try:
        out = json.loads(
            await browser_mod.browser_tool(_ctx(tmp_path), action="eval", expression="1+1")
        )
        assert out["ok"] is True
        assert out["data"]["value"] == 2
    finally:
        browser_mod.set_eval_allowed(False)
        await session.disconnect()


def test_register_browser_tool() -> None:
    """register_browser_tool adds the tool when the engine is available."""
    exe = ToolExecutor()
    browser_mod.register_browser_tool(exe, cfg=None)
    assert exe.has("browser")


async def test_telegram_action_unknown_op(
    monkeypatch: pytest.MonkeyPatch, fake_cdp: FakeCDPServer, tmp_path: Path
) -> None:
    """The telegram action resolves a page and validates the sub-op."""
    fake_cdp.set_result("Target.getTargets", {"targetInfos": [{"targetId": "p1", "type": "page"}]})
    fake_cdp.set_result("Target.attachToTarget", {"sessionId": "S1"})
    session = await _fake_session(fake_cdp)
    _patch_session(monkeypatch, session)
    try:
        out = json.loads(
            await browser_mod.browser_tool(_ctx(tmp_path), action="telegram", op="nope")
        )
        assert out["ok"] is False
        assert "unknown telegram op" in out["error"]
    finally:
        await session.disconnect()


async def test_unknown_action(
    monkeypatch: pytest.MonkeyPatch, fake_cdp: FakeCDPServer, tmp_path: Path
) -> None:
    """An unknown action that reaches dispatch returns a validation error."""
    fake_cdp.set_result("Target.getTargets", {"targetInfos": [{"targetId": "p1", "type": "page"}]})
    fake_cdp.set_result("Target.attachToTarget", {"sessionId": "S1"})
    session = await _fake_session(fake_cdp)
    _patch_session(monkeypatch, session)
    try:
        out = json.loads(await browser_mod.browser_tool(_ctx(tmp_path), action="bogus"))
        assert out["ok"] is False
    finally:
        await session.disconnect()
