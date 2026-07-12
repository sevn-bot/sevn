"""Tests for proxy-backed LLM transports."""

from __future__ import annotations

import pytest

from sevn.agent.providers import AnthropicTransport, ChatCompletionsTransport, resolve_model


@pytest.mark.asyncio
async def test_anthropic_complete_calls_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_post(**kwargs: object) -> dict[str, object]:
        assert kwargs["base_url"] == "http://proxy.test"
        assert kwargs["path"] == "/llm/anthropic/messages"
        return {"id": "m1", "usage": {"input_tokens": 3, "output_tokens": 5}}

    monkeypatch.setattr(
        "sevn.agent.providers.transport.transport_http.post_llm_json",
        fake_post,
    )
    t = AnthropicTransport(proxy_base_url="http://proxy.test")
    out = await t.complete({"model": "claude-test", "max_tokens": 10})
    assert out["id"] == "m1"
    assert t.tokens_used(out) == (3, 5)


@pytest.mark.asyncio
async def test_chat_completions_openai_usage_keys() -> None:
    t = ChatCompletionsTransport(proxy_base_url="http://x")
    resp = {"usage": {"prompt_tokens": 7, "completion_tokens": 11}}
    assert t.tokens_used(resp) == (7, 11)


@pytest.mark.asyncio
async def test_resolve_model_uses_env_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    async def fake_post(**kwargs: object) -> dict[str, object]:
        seen.append(str(kwargs["base_url"]))
        return {"usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    monkeypatch.setattr(
        "sevn.agent.providers.transport.transport_http.post_llm_json",
        fake_post,
    )
    monkeypatch.setenv("SEVN_PROXY_URL", "http://from.env")
    _, t = resolve_model(model_id="openai/gpt-5-mini", transport_name="chat_completions")
    await t.complete({"model": "openai/gpt-5-mini"})
    assert seen == ["http://from.env"]
