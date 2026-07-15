"""Unit tests for TwexAPI client allowlist and headers."""

from __future__ import annotations

import asyncio

import pytest

from sevn.integrations.twexapi.client import (
    TWEXAPI_ARRAY_BODY_OPS,
    TWEXAPI_OPS,
    TwexApiClient,
    TwexApiError,
)


def test_auth_header() -> None:
    assert TwexApiClient("sk-test")._headers()["Authorization"] == "Bearer sk-test"


def test_unknown_op_raises() -> None:
    client = TwexApiClient("sk")
    with pytest.raises(TwexApiError, match="unknown TwexAPI op"):
        asyncio.run(client.call_op("not_a_real_op"))


def test_openapi_aligned_ops() -> None:
    assert TWEXAPI_OPS["search"] == ("POST", "/twitter/advanced_search")
    assert TWEXAPI_OPS["users"] == ("POST", "/twitter/users")
    assert TWEXAPI_OPS["users_by_ids"] == ("POST", "/twitter/users/by_ids")
    assert TWEXAPI_OPS["timeline_page"] == ("POST", "/twitter/{screen_name}/timeline/page")
    assert TWEXAPI_OPS["tweet_detail"] == ("POST", "/twitter/tweets/lookup")
    assert TWEXAPI_OPS["trending_topics"] == ("GET", "/twitter/{country}/trending")
    assert TWEXAPI_OPS["balance"] == ("GET", "/balance")
    assert "users" in TWEXAPI_ARRAY_BODY_OPS
    assert "tweet_detail" in TWEXAPI_ARRAY_BODY_OPS
