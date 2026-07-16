"""W9 tests: social recipes — fixture parsing, egress, write kill-switch."""

from __future__ import annotations

from pathlib import Path

import pytest

from sevn.browser.cdp import CDPConnection, CDPSession
from sevn.browser.element import Dom
from sevn.browser.page import Page
from sevn.browser.recipes.base import RecipeError, validate_egress
from sevn.browser.recipes.social import (
    X_EGRESS_DOMAINS,
    SocialRecipe,
    parse_comments_html,
    parse_post_html,
    social_write_allowed,
)

_FIXTURES = Path(__file__).parent / "recipes" / "fixtures"


def test_parse_x_post_fixture() -> None:
    """X post fixture parses visible text."""
    html = (_FIXTURES / "x_post.html").read_text(encoding="utf-8")
    out = parse_post_html(html)
    assert "Hello from X" in out["text"]


def test_parse_comments_empty() -> None:
    """Comments parser returns empty list for blank HTML."""
    assert parse_comments_html("<html></html>")["count"] == 0


def test_social_write_kill_switch() -> None:
    """Per-site social writes are opt-in."""
    assert social_write_allowed("x") is False
    assert social_write_allowed("x", browser_tools={"social": {"x": {"allow_write": True}}}) is True


def test_x_egress_blocks_external() -> None:
    """X recipe egress rejects off-domain URLs."""
    assert validate_egress("https://x.com/home", allowlist=X_EGRESS_DOMAINS)
    with pytest.raises(RecipeError):
        validate_egress("https://evil.example/post", allowlist=X_EGRESS_DOMAINS)


async def test_social_post_write_blocked(fake_cdp) -> None:  # type: ignore[no-untyped-def]
    """post is rejected when the per-site write kill-switch is off."""
    fake_cdp.set_result("Runtime.evaluate", {"result": {"value": False}})
    fake_cdp.set_result("Page.navigate", {"frameId": "f1"})
    conn = await CDPConnection.connect(fake_cdp.ws_url)
    session = CDPSession(conn)
    recipe = SocialRecipe(Page(session), Dom(session))
    try:
        with pytest.raises(RecipeError, match="write ops disabled"):
            await recipe.run("x", "post", text="hello")
    finally:
        await conn.close()
