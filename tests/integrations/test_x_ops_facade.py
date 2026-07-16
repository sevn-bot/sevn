"""W1 RED - unified X ops facade (DB6-DB10; green after W4).

Imports of ``sevn.integrations.social_media.x_ops`` stay inside test bodies so
collection succeeds before W4 creates the module.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

# §4 facade ops (DB6) — one function per op in sevn.integrations.social_media.x_ops
_FACADE_OPS: tuple[str, ...] = (
    # search
    "advanced_search_page",
    "search_hashtags",
    # tweet-actions
    "like_tweet",
    "unlike_tweet",
    "retweet",
    "delete_retweet",
    "bookmark",
    "delete_bookmark",
    "create_tweet_or_reply",
    "create_quote_tweet",
    "create_tweet_thread",
    "delete_tweets",
    "post_tweet_auto_cookie",
    # users
    "get_users_by_usernames",
    "follow_user",
    # articles
    "fetch_article_markdown",
    # also
    "home_timeline_collect",
    "session_status",
)

_ENVELOPE_KEYS = frozenset({"ok", "medium", "op", "data"})


def _import_x_ops() -> Any:
    from sevn.integrations.social_media import x_ops

    return x_ops


@pytest.mark.parametrize("op_name", _FACADE_OPS)
def test_x_ops_facade_exports_every_section4_op(op_name: str) -> None:
    """DB6: each §4 op is a callable on the facade owner module."""
    x_ops = _import_x_ops()
    fn = getattr(x_ops, op_name, None)
    assert callable(fn), f"missing facade op: {op_name}"


@pytest.mark.asyncio
@pytest.mark.parametrize("medium", ["browser", "twexapi"])
async def test_x_ops_dispatch_returns_normalized_envelope(medium: str) -> None:
    """DB6: resolve_social_medium drives dispatch; envelope is {ok,medium,op,data,...}."""
    x_ops = _import_x_ops()
    with patch(
        "sevn.integrations.social_media.x_ops.resolve_social_medium",
        return_value=medium,
    ):
        result = await x_ops.home_timeline_collect(
            task={"medium": medium},
            cfg={},
            site="x",
        )
    assert isinstance(result, dict)
    assert _ENVELOPE_KEYS.issubset(result.keys())
    assert result["ok"] in (True, False)
    assert result["medium"] == medium
    assert result["op"] == "home_timeline_collect"
    assert "data" in result
    if result["ok"] is False:
        assert "error" in result or "code" in result


@pytest.mark.asyncio
async def test_browser_write_op_blocked_returns_error_envelope_not_exception() -> None:
    """DB8: browser write with allow_write=false → error envelope, never raw exception."""
    x_ops = _import_x_ops()
    cfg = {"tools": {"browser": {"social": {"x": {"allow_write": False}}}}}
    with patch(
        "sevn.integrations.social_media.x_ops.resolve_social_medium",
        return_value="browser",
    ):
        result = await x_ops.like_tweet(
            task={"medium": "browser", "tweet_id": "1"},
            cfg=cfg,
            site="x",
        )
    assert isinstance(result, dict)
    assert result["ok"] is False
    assert result["medium"] == "browser"
    assert result["op"] == "like_tweet"
    assert result.get("error") or result.get("code")


@pytest.mark.asyncio
async def test_twexapi_write_op_disabled_returns_error_envelope() -> None:
    """DB8: TwexAPI write when TwexAPI disabled → error envelope, never exception."""
    x_ops = _import_x_ops()
    cfg = {"integrations": {"twexapi": {"enabled": False}}}
    with patch(
        "sevn.integrations.social_media.x_ops.resolve_social_medium",
        return_value="twexapi",
    ):
        result = await x_ops.create_tweet_or_reply(
            task={"medium": "twexapi", "text": "hi"},
            cfg=cfg,
            site="x",
        )
    assert isinstance(result, dict)
    assert result["ok"] is False
    assert result["medium"] == "twexapi"
    assert result.get("error") or result.get("code")


def test_cookie_bridge_maps_export_cookies_without_leaking_values() -> None:
    """DB9 + convention 13: export_cookies → TwexAPI cookie; values never in returned strings."""
    x_ops = _import_x_ops()
    secret = "auth_token=SUPER_SECRET_COOKIE_VALUE; ct0=also_secret"
    export_payload = {
        "ok": True,
        "cookies": [
            {"name": "auth_token", "value": "SUPER_SECRET_COOKIE_VALUE", "domain": ".x.com"},
            {"name": "ct0", "value": "also_secret", "domain": ".x.com"},
        ],
        "cookie_header": secret,
    }
    mapped = x_ops.cookies_for_twexapi(export_payload)
    assert isinstance(mapped, str)
    assert mapped  # non-empty cookie field for TwexAPI
    # Returned mapping may contain the cookie for the API call; the *logged/serialized
    # diagnostic* path must not. Contract: helper that builds a log-safe summary omits values.
    safe = x_ops.cookie_bridge_log_safe(export_payload)
    blob = str(safe)
    assert "SUPER_SECRET_COOKIE_VALUE" not in blob
    assert "also_secret" not in blob
    assert secret not in blob


@pytest.mark.asyncio
async def test_session_status_reports_fields_without_leaking_key() -> None:
    """DB10: session_status reports reachability/profile/login/key-present; never the key."""
    x_ops = _import_x_ops()
    secret_key = "sk-twexapi-LIVE-SECRET-999"
    with (
        patch(
            "sevn.integrations.social_media.x_ops.resolve_social_medium",
            return_value="browser",
        ),
        patch.dict("os.environ", {"SEVN_SECRET_TWEXAPI": secret_key}, clear=False),
    ):
        result = await x_ops.session_status(task={}, cfg={}, site="x")
    assert isinstance(result, dict)
    assert result["op"] == "session_status"
    data = result.get("data") or {}
    assert "cdp_reachable" in data or "reachability" in data or "cdp_ok" in data
    assert "profile" in str(data).lower() or "profile_path" in data or "profile_dir" in data
    # key present as boolean, never raw secret
    key_present = data.get("twexapi_key_present", data.get("key_present"))
    assert key_present in (True, False, None) or isinstance(key_present, bool)
    blob = str(result)
    assert secret_key not in blob
