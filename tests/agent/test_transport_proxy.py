"""Tests for proxy-backed LLM transports."""

from __future__ import annotations

from pathlib import Path

import pytest

from sevn.agent.providers import AnthropicTransport, ChatCompletionsTransport, resolve_model
from sevn.proxy.bootstrap_secret import ensure_proxy_shared_secret_file

_TRANSPORT_SECRET = "transport-test-proxy-secret-32chars!!"


@pytest.mark.asyncio
async def test_anthropic_complete_calls_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_post(**kwargs: object) -> dict[str, object]:
        assert kwargs["base_url"] == "http://proxy.test"
        assert kwargs["path"] == "/llm/anthropic/messages"
        headers = kwargs.get("headers")
        assert isinstance(headers, dict)
        assert headers.get("X-Sevn-Proxy-Token") == _TRANSPORT_SECRET
        return {"id": "m1", "usage": {"input_tokens": 3, "output_tokens": 5}}

    monkeypatch.setattr(
        "sevn.agent.providers.transport.transport_http.post_llm_json",
        fake_post,
    )
    monkeypatch.setenv("SEVN_PROXY_SHARED_SECRET", _TRANSPORT_SECRET)
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
    monkeypatch.setenv("SEVN_PROXY_SHARED_SECRET", _TRANSPORT_SECRET)
    _, t = resolve_model(model_id="openai/gpt-5-mini", transport_name="chat_completions")
    await t.complete({"model": "openai/gpt-5-mini"})
    assert seen == ["http://from.env"]


def test_auth_header_raises_without_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail-closed: auth_header must not omit X-Sevn-Proxy-Token (Thermos T1)."""
    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    t = AnthropicTransport(proxy_base_url="http://proxy.test")
    with pytest.raises(RuntimeError, match="SEVN_PROXY_SHARED_SECRET"):
        t.auth_header("claude-test")


def test_auth_header_reads_generate_once_file_when_env_blank(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compose default: blank ProcessSettings env + file under SEVN_HOME (T1)."""
    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    ensure_proxy_shared_secret_file(tmp_path, secret=_TRANSPORT_SECRET)
    t = AnthropicTransport(proxy_base_url="http://proxy.test")
    headers = t.auth_header("claude-test")
    assert headers.get("X-Sevn-Proxy-Token") == _TRANSPORT_SECRET


def test_auth_header_honors_extra_headers_without_resolving(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caller-supplied token wins; no env/file required."""
    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    t = AnthropicTransport(
        proxy_base_url="http://proxy.test",
        extra_headers={"X-Sevn-Proxy-Token": "injected-header-secret"},
    )
    headers = t.auth_header("claude-test")
    assert headers.get("X-Sevn-Proxy-Token") == "injected-header-secret"
