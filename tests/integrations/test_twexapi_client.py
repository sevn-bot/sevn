"""Unit tests for TwexAPI client allowlist and headers."""

from __future__ import annotations

import asyncio

import pytest

from sevn.integrations.twexapi.client import TWEXAPI_OPS, TwexApiClient, TwexApiError


def test_auth_header() -> None:
    assert TwexApiClient("sk-test")._headers()["Authorization"] == "Bearer sk-test"


def test_unknown_op_raises() -> None:
    client = TwexApiClient("sk")
    with pytest.raises(TwexApiError, match="unknown TwexAPI op"):
        asyncio.run(client.call_op("not_a_real_op"))


def test_search_op_mapped() -> None:
    method, path = TWEXAPI_OPS["search"]
    assert method == "POST"
    assert "advanced_search" in path
