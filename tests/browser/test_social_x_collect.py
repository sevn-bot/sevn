"""W1 RED — structured X collect + op=read (DB4/DB5; green after W3)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from sevn.browser.cdp import CDPConnection, CDPSession
from sevn.browser.element import Dom
from sevn.browser.page import Page

_FIXTURES = Path(__file__).parent / "recipes" / "fixtures"
_STATUS_RE = re.compile(r"https://x\.com/[^/]+/status/\d+$")


def _posts_from_result(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize recipe/tool payloads to a list of post dicts."""
    for key in ("posts", "tweets", "data", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    if all(k in payload for k in ("tweet_url", "author_handle", "text")):
        return [payload]
    return []


def _assert_structured_posts(posts: list[dict[str, Any]]) -> None:
    assert posts, "expected at least one structured post"
    urls = [str(p.get("tweet_url", "")) for p in posts]
    assert len(urls) == len(set(urls)), "posts must be deduped by tweet_url"
    for post in posts:
        url = str(post.get("tweet_url", ""))
        assert _STATUS_RE.fullmatch(url), f"status permalink required, got {url!r}"
        assert "/photo" not in url
        assert "analytics" not in url
        assert "?" not in url
        assert post.get("author_handle")
        text = post.get("text")
        assert isinstance(text, str)
        assert text.strip()
        # Never treat bare profile URLs as permalinks.
        assert not re.fullmatch(r"https://x\.com/[^/]+/?$", url)


@pytest.mark.asyncio
async def test_timeline_collect_returns_status_permalinks(fake_cdp: Any) -> None:
    """DB4: timeline_collect returns {tweet_url, author_handle, text} with /status/ ids."""
    html = (_FIXTURES / "x_home_feed.html").read_text(encoding="utf-8")
    fake_cdp.set_result("Page.navigate", {"frameId": "f1"})
    fake_cdp.set_result("Runtime.evaluate", {"result": {"value": html}})
    fake_cdp.set_result("DOM.getDocument", {"root": {"nodeId": 1}})
    conn = await CDPConnection.connect(fake_cdp.ws_url)
    session = CDPSession(conn)
    recipe = __import__("sevn.browser.recipes.social", fromlist=["SocialRecipe"]).SocialRecipe(
        Page(session),
        Dom(session),
    )
    try:
        payload = await recipe.run("x", "timeline_collect")
        _assert_structured_posts(_posts_from_result(payload))
        posts = _posts_from_result(payload)
        assert any("1111111111111111111" in str(p["tweet_url"]) for p in posts)
        assert any("2222222222222222222" in str(p["tweet_url"]) for p in posts)
        # Duplicate status id appears once.
        assert sum("1111111111111111111" in str(p["tweet_url"]) for p in posts) == 1
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_home_feed_returns_structured_posts(fake_cdp: Any) -> None:
    """DB4: home_feed exposes the same structured shape as timeline_collect."""
    html = (_FIXTURES / "x_home_feed.html").read_text(encoding="utf-8")
    fake_cdp.set_result("Page.navigate", {"frameId": "f1"})
    fake_cdp.set_result("Runtime.evaluate", {"result": {"value": html}})
    conn = await CDPConnection.connect(fake_cdp.ws_url)
    session = CDPSession(conn)
    recipe = __import__("sevn.browser.recipes.social", fromlist=["SocialRecipe"]).SocialRecipe(
        Page(session),
        Dom(session),
    )
    try:
        payload = await recipe.run("x", "home_feed")
        _assert_structured_posts(_posts_from_result(payload))
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_x_op_read_returns_structured_posts_not_raw_html(fake_cdp: Any) -> None:
    """DB5: X op=read returns structured posts, not stylesheet/raw HTML noise."""
    html = (_FIXTURES / "x_home_feed.html").read_text(encoding="utf-8")
    # Inject stylesheet noise that today's parse_post_html may surface.
    noisy = html.replace("<body>", "<body><style>.css{color:red}</style>")
    fake_cdp.set_result("Page.navigate", {"frameId": "f1"})
    fake_cdp.set_result("Runtime.evaluate", {"result": {"value": noisy}})
    conn = await CDPConnection.connect(fake_cdp.ws_url)
    session = CDPSession(conn)
    recipe = __import__("sevn.browser.recipes.social", fromlist=["SocialRecipe"]).SocialRecipe(
        Page(session),
        Dom(session),
    )
    try:
        payload = await recipe.run("x", "read")
        posts = _posts_from_result(payload)
        _assert_structured_posts(posts)
        blob = str(payload)
        assert ".css{color:red}" not in blob
        assert "<style>" not in blob
    finally:
        await conn.close()
