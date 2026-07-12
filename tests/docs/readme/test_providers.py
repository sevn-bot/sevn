"""Tests for README section providers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from sevn.docs.readme.providers import (
    LlmProvider,
    OfflineProvider,
    ReadmeProviderConfig,
    build_provider,
)


@pytest.mark.asyncio
async def test_offline_provider_is_deterministic() -> None:
    """Offline provider returns stable section bodies."""
    provider = OfflineProvider()
    variables = {"title": "Gateway", "profile": "subsystem", "summary": "FastAPI control plane."}
    first = await provider.render_section("summary", variables)
    second = await provider.render_section("summary", variables)
    assert first == second == "FastAPI control plane."


@pytest.mark.asyncio
async def test_llm_provider_uses_transport_complete() -> None:
    """LLM provider routes through Transport.complete (mocked)."""
    config = ReadmeProviderConfig(offline=False, proxy_base_url="http://proxy.test")
    provider = LlmProvider(config)
    transport = MagicMock()
    transport.name = "anthropic"
    transport.complete = AsyncMock(
        return_value={"content": [{"type": "text", "text": "Polished overview."}]}
    )
    provider._transport = transport
    text = await provider.render_section(
        "overview",
        {
            "title": "Gateway",
            "summary": "s",
            "profile": "subsystem",
            "context_json": "{}",
            "source_excerpt": "- `a.py`",
        },
    )
    assert text == "Polished overview."
    transport.complete.assert_awaited_once()


def test_build_provider_offline_by_default() -> None:
    """Default config yields OfflineProvider."""
    assert isinstance(build_provider(ReadmeProviderConfig()), OfflineProvider)
