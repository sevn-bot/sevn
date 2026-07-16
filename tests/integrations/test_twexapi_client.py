"""Unit tests for TwexAPI client allowlist, headers, and X-only guard contracts."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest


def _import_client_module() -> Any:
    from sevn.integrations.twexapi import client as mod

    return mod


def test_auth_header() -> None:
    client_mod = _import_client_module()
    assert client_mod.TwexApiClient("sk-test")._headers()["Authorization"] == "Bearer sk-test"


def test_unknown_op_raises() -> None:
    client_mod = _import_client_module()
    client = client_mod.TwexApiClient("sk")
    with pytest.raises(client_mod.TwexApiError, match="unknown TwexAPI op"):
        asyncio.run(client.call_op("not_a_real_op"))


def test_openapi_aligned_ops() -> None:
    client_mod = _import_client_module()
    ops = client_mod.TWEXAPI_OPS
    assert ops["search"] == ("POST", "/twitter/advanced_search")
    assert ops["users"] == ("POST", "/twitter/users")
    assert ops["users_by_ids"] == ("POST", "/twitter/users/by_ids")
    assert ops["timeline_page"] == ("POST", "/twitter/{screen_name}/timeline/page")
    assert ops["tweet_detail"] == ("POST", "/twitter/tweets/lookup")
    assert ops["trending_topics"] == ("GET", "/twitter/{country}/trending")
    assert ops["balance"] == ("GET", "/balance")
    assert "users" in client_mod.TWEXAPI_ARRAY_BODY_OPS
    assert "tweet_detail" in client_mod.TWEXAPI_ARRAY_BODY_OPS


@pytest.mark.asyncio
async def test_client_call_op_has_no_site_parameter() -> None:
    """TwexAPI client is X/Twitter API only; site guard lives in worker/medium layer."""
    client_mod = _import_client_module()
    client = client_mod.TwexApiClient("sk-test")
    http_mock = AsyncMock(return_value={"status": 200, "body": "{}"})
    with patch.object(client, "_request", http_mock):
        await client.call_op("search", body={"searchTerms": ["test"]})
    http_mock.assert_called_once()


# --- W1 RED (playwright-removal / X parity): DB7 TWEXAPI_OPS expand (green after W4) ---

# §4 TwexAPI paths that must be *added* in W4 (beyond the pre-W4 baseline allowlist).
_SECTION4_NEW_TWEXAPI_OPS: tuple[str, ...] = (
    "hashtags",
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
    "follow_user",
    "fetch_article_markdown",
)


@pytest.mark.parametrize("op_key", _SECTION4_NEW_TWEXAPI_OPS)
def test_twexapi_ops_registers_section4_paths(op_key: str) -> None:
    """DB7: TWEXAPI_OPS allowlist includes every §4 TwexAPI endpoint key."""
    client_mod = _import_client_module()
    assert op_key in client_mod.TWEXAPI_OPS
    method, path = client_mod.TWEXAPI_OPS[op_key]
    assert method in {"GET", "POST", "PUT", "DELETE", "PATCH"}
    assert isinstance(path, str)
    assert path.startswith("/")


def test_twexapi_write_helpers_accept_cookie_without_logging_it() -> None:
    """DB7 + convention 13: write helpers take cookie/proxy; never embed them in errors."""
    client_mod = _import_client_module()
    client = client_mod.TwexApiClient("sk-test")
    secret = "auth_token=LEAK_ME_NEVER"
    assert hasattr(client, "call_write_op"), "expected call_write_op for cookie writes"
    with pytest.raises(client_mod.TwexApiError) as exc_info:
        asyncio.run(
            client.call_write_op(
                "like_tweet",
                path_params={"tweet_id": "1"},
                cookie=secret,
                proxy="http://user:pass@proxy:1",
            )
        )
    err = str(exc_info.value)
    assert secret not in err
    assert "user:pass" not in err
    write_ops = getattr(client_mod, "TWEXAPI_WRITE_OPS", None)
    assert write_ops is not None
    assert "like_tweet" in write_ops
