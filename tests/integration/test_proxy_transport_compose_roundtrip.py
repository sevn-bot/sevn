"""Live proxy + ``ChatCompletionsTransport`` round-trip (specs/05-llm-transports.md §10.7).

Runs when ``SEVN_CI_PROXY_URL`` points at a reachable egress proxy (GitHub ``compose-ci``
job or ``make compose-ci-smoke``).
"""

from __future__ import annotations

import os

import pytest

from sevn.agent.providers.transport import ChatCompletionsTransport

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_chat_completions_via_live_proxy() -> None:
    """POST chat completions through the containerized proxy to a mock upstream."""
    base = os.environ.get("SEVN_CI_PROXY_URL")
    if not base:
        pytest.skip("SEVN_CI_PROXY_URL unset (compose CI / make compose-ci-smoke only)")
    transport = ChatCompletionsTransport(proxy_base_url=base.rstrip("/"))
    body = await transport.complete(
        {
            "model": "openai/gpt-ci-mock",
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 8,
        },
    )
    assert body.get("id") == "ci-mock"
    choices = body.get("choices")
    assert isinstance(choices, list)
    assert len(choices) >= 1
