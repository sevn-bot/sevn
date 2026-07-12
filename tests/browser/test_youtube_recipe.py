"""W8 tests: YouTube recipe — fixture parsing and write kill-switch."""

from __future__ import annotations

from pathlib import Path

import pytest

from sevn.browser.cdp import CDPConnection, CDPSession
from sevn.browser.element import Dom
from sevn.browser.page import Page
from sevn.browser.recipes.base import RecipeError
from sevn.browser.recipes.youtube import (
    YouTube,
    parse_comments,
    parse_search_results,
    parse_video_info,
)

_FIXTURES = Path(__file__).parent / "recipes" / "fixtures"


def _read(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


def test_parse_youtube_search_fixture() -> None:
    """Search results parse title, url, channel, and views."""
    out = parse_search_results(_read("youtube_search.html"))
    assert out["count"] == 1
    assert out["videos"][0]["title"] == "Never Gonna Give You Up"
    assert "dQw4w9WgXcQ" in out["videos"][0]["url"]


def test_parse_youtube_watch_fixture() -> None:
    """Watch page parses metadata and comments."""
    html = _read("youtube_watch.html")
    info = parse_video_info(html)
    assert info["title"] == "Demo Video"
    assert info["likes"] == "1200"
    comments = parse_comments(html)
    assert comments["comments"][0]["author"] == "Viewer One"
    assert comments["comments"][0]["text"] == "Great video!"


async def test_youtube_reply_write_blocked(fake_cdp) -> None:  # type: ignore[no-untyped-def]
    """reply is rejected when the write kill-switch is off."""

    def _logged_in(msg):  # type: ignore[no-untyped-def]
        expr = msg.get("params", {}).get("expression", "")
        if "avatar" in expr:
            return {"result": {"value": True}}
        return {"result": {"value": False}}

    fake_cdp.on_command("Runtime.evaluate", _logged_in)
    fake_cdp.set_result("Page.navigate", {"frameId": "f1"})
    conn = await CDPConnection.connect(fake_cdp.ws_url)
    session = CDPSession(conn)
    recipe = YouTube(Page(session), Dom(session))
    try:
        with pytest.raises(RecipeError, match="write ops disabled"):
            await recipe.reply("dQw4w9WgXcQ", "Viewer One", "thanks!")
    finally:
        await conn.close()
