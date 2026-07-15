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
