"""W7 tests: Google Search, Gmail, and Maps recipes — fixture HTML parsing + tool dispatch."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from sevn.browser.cdp import CDPConnection, CDPSession
from sevn.browser.element import Dom
from sevn.browser.lifecycle import CDPBrowserSession
from sevn.browser.page import Page
from sevn.browser.recipes.base import RecipeError, recipe_write_allowed, validate_egress
from sevn.browser.recipes.gmail import (
    GMAIL_EGRESS,
    Gmail,
    parse_inbox,
    parse_message,
)
from sevn.browser.recipes.google_maps import (
    GOOGLE_MAPS_EGRESS,
    parse_directions,
    parse_place,
    parse_places,
    parse_reviews,
)
from sevn.browser.recipes.google_search import (
    GOOGLE_SEARCH_EGRESS,
    GoogleSearch,
    parse_ai_overview,
    parse_gemini_answer,
    parse_search_results,
)
from sevn.tools import browser as browser_mod
from sevn.tools.context import ToolContext

if TYPE_CHECKING:
    from tests.browser.conftest import FakeCDPServer

_FIXTURES = Path(__file__).parent / "recipes" / "fixtures"


def _read(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


def test_parse_search_results_fixture() -> None:
    """Organic results and People-Also-Ask parse from saved Google HTML."""
    out = parse_search_results(_read("google_search_results.html"))
    assert out["count"] == 2
    assert out["results"][0]["title"] == "Python Programming Language"
    assert out["results"][0]["url"] == "https://www.python.org/"
    assert "Python" in out["results"][0]["snippet"]
    assert out["people_also_ask"] == ["What is Python used for?"]


def test_parse_ai_overview_fixture() -> None:
    """AI Overview answer and citations parse from saved Google HTML."""
    out = parse_ai_overview(_read("google_ai_overview.html"))
    assert out is not None
    assert "Python is a high-level" in out["answer"]
    assert out["source"] == "ai_overview"
    assert any(c["url"].startswith("https://") for c in out["citations"])


def test_parse_gemini_answer_fixture() -> None:
    """Gemini fallback answer parses from saved HTML."""
    out = parse_gemini_answer(_read("gemini_answer.html"))
    assert "Python is widely used" in out["answer"]
    assert out["source"] == "gemini"
    assert out["citations"][0]["url"] == "https://realpython.com/"


def test_parse_gmail_inbox_fixture() -> None:
    """Gmail inbox rows parse from saved HTML."""
    out = parse_inbox(_read("gmail_inbox.html"))
    assert out["count"] == 2
    assert out["messages"][0]["from"] == "Alice Example"
    assert out["messages"][0]["subject"] == "Weekly update"
    assert out["messages"][1]["time"] == "Yesterday"


def test_parse_gmail_message_fixture() -> None:
    """Gmail message view parses subject, body, and attachments."""
    out = parse_message(_read("gmail_message.html"))
    assert out["subject"] == "Weekly update"
    assert "Full message body" in out["body"]
    assert out["attachments"] == ["report.pdf"]


def test_parse_maps_fixtures() -> None:
    """Maps search, place, directions, and reviews parse from saved HTML."""
    places = parse_places(_read("maps_search.html"))
    assert places["count"] == 2
    assert places["places"][0]["name"] == "Blue Bottle Coffee"

    place = parse_place(_read("maps_place.html"))
    assert place["name"] == "Golden Gate Park"
    assert place["rating"] == "4.8"
    assert place["website"] == "https://goldengatepark.com"

    directions = parse_directions(_read("maps_directions.html"))
    assert directions["duration"] == "25 min"
    assert directions["distance"] == "8.2 mi"

    reviews = parse_reviews(_read("maps_reviews.html"))
    assert reviews["count"] == 2
    assert reviews["reviews"][0]["author"] == "Jane Visitor"
    assert reviews["reviews"][0]["rating"] == "5"


def test_egress_allowlists() -> None:
    """Each recipe permits its hosts and rejects outsiders."""
    assert validate_egress("https://www.google.com/search?q=x", allowlist=GOOGLE_SEARCH_EGRESS)
    assert validate_egress("https://gemini.google.com/app", allowlist=GOOGLE_SEARCH_EGRESS)
    assert validate_egress("https://mail.google.com/mail/u/0/", allowlist=GMAIL_EGRESS)
    assert validate_egress(
        "https://www.google.com/maps/search/coffee", allowlist=GOOGLE_MAPS_EGRESS
    )
    with pytest.raises(RecipeError):
        validate_egress("https://evil.example/", allowlist=GOOGLE_SEARCH_EGRESS)


def test_write_kill_switch_default_off() -> None:
    """Gmail write ops are opt-in per D8."""
    assert recipe_write_allowed("gmail") is False
    assert recipe_write_allowed("gmail", browser_tools={"gmail": {"allow_write": True}}) is True


async def _recipe_page(fake_cdp: FakeCDPServer) -> tuple[Page, Dom, CDPConnection]:
    conn = await CDPConnection.connect(fake_cdp.ws_url)
    session = CDPSession(conn)
    return Page(session), Dom(session), conn


def _html_responder(html: str) -> Any:
    """Return a Runtime.evaluate responder that yields fixture HTML."""

    def _responder(msg: dict[str, Any]) -> dict[str, Any]:
        expr = msg.get("params", {}).get("expression", "")
        if "documentElement.outerHTML" in expr or "outerHTML" in expr:
            return {"result": {"value": html}}
        if "location.href" in expr:
            return {"result": {"value": "https://www.google.com/"}}
        return {"result": {"value": ""}}

    return _responder


async def test_google_search_ask_ai_overview(fake_cdp: FakeCDPServer) -> None:
    """mode=ask returns AI Overview text from a fixture page."""
    html = _read("google_ai_overview.html")
    fake_cdp.on_command("Runtime.evaluate", _html_responder(html))
    fake_cdp.set_result("Page.navigate", {"frameId": "f1"})
    page, dom, conn = await _recipe_page(fake_cdp)
    try:
        out = await GoogleSearch(page, dom).search("what is python", mode="ask")
        assert out["source"] == "ai_overview"
        assert "Python is a high-level" in out["answer"]
    finally:
        await conn.close()


async def test_gmail_compose_write_blocked(fake_cdp: FakeCDPServer) -> None:
    """compose is rejected when the write kill-switch is off."""

    def _logged_in(msg: dict[str, Any]) -> dict[str, Any]:
        expr = msg.get("params", {}).get("expression", "")
        if "Account" in expr or "gb_d" in expr:
            return {"result": {"value": True}}
        return {"result": {"value": False}}

    fake_cdp.on_command("Runtime.evaluate", _logged_in)
    fake_cdp.set_result("Page.navigate", {"frameId": "f1"})
    page, dom, conn = await _recipe_page(fake_cdp)
    try:
        with pytest.raises(RecipeError, match="write ops disabled"):
            await Gmail(page, dom).compose("a@example.com", "Hi", "Body")
    finally:
        await conn.close()


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


async def test_tool_google_search_unknown_mode(
    monkeypatch: pytest.MonkeyPatch, fake_cdp: FakeCDPServer, tmp_path: Path
) -> None:
    """google_search validates mode through the tool envelope."""
    fake_cdp.set_result("Target.getTargets", {"targetInfos": [{"targetId": "p1", "type": "page"}]})
    fake_cdp.set_result("Target.attachToTarget", {"sessionId": "S1"})
    session = await _fake_session(fake_cdp)
    _patch_session(monkeypatch, session)
    try:
        out = json.loads(
            await browser_mod.browser_tool(
                _ctx(tmp_path),
                action="google_search",
                query="test",
                mode="nope",
            )
        )
        assert out["ok"] is False
        assert "google_search failed" in out["error"]
    finally:
        await session.disconnect()


async def test_tool_maps_unknown_op(
    monkeypatch: pytest.MonkeyPatch, fake_cdp: FakeCDPServer, tmp_path: Path
) -> None:
    """maps validates the sub-op through the tool envelope."""
    fake_cdp.set_result("Target.getTargets", {"targetInfos": [{"targetId": "p1", "type": "page"}]})
    fake_cdp.set_result("Target.attachToTarget", {"sessionId": "S1"})
    session = await _fake_session(fake_cdp)
    _patch_session(monkeypatch, session)
    try:
        out = json.loads(await browser_mod.browser_tool(_ctx(tmp_path), action="maps", op="nope"))
        assert out["ok"] is False
        assert "unknown maps op" in out["error"]
    finally:
        await session.disconnect()
