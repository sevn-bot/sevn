"""Transport-aware request body adapter (`specs/05-llm-transports.md` §2.3)."""

from __future__ import annotations

from sevn.agent.providers.transport import AnthropicTransport, ChatCompletionsTransport
from sevn.agent.providers.wire import adapt_request_for_transport
from sevn.proxy.anthropic_body import normalize_anthropic_request_body


def test_chat_completions_passthrough_strips_minimax_prefix() -> None:
    req = {
        "model": "minimax/MiniMax-M2.7",
        "messages": [{"role": "user", "content": "hi"}],
    }
    out = adapt_request_for_transport(ChatCompletionsTransport(), req)
    assert out["model"] == "MiniMax-M2.7"
    assert out["messages"] == [{"role": "user", "content": "hi"}]
    assert "system" not in out


def test_anthropic_lifts_system_and_floors_max_tokens() -> None:
    req = {
        "model": "minimax/MiniMax-M2.7",
        "messages": [
            {"role": "system", "content": "be terse"},
            {"role": "user", "content": "hi"},
        ],
        "temperature": 0.0,
    }
    out = adapt_request_for_transport(AnthropicTransport(), req)
    assert out["model"] == "MiniMax-M2.7"
    assert out["system"] == "be terse"
    assert out["messages"] == [{"role": "user", "content": "hi"}]
    assert isinstance(out["max_tokens"], int)
    assert out["max_tokens"] >= 1024


def test_anthropic_preserves_explicit_max_tokens_above_floor() -> None:
    req = {
        "model": "claude-3-5-sonnet",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 4096,
    }
    out = adapt_request_for_transport(AnthropicTransport(), req)
    assert out["max_tokens"] == 4096


def test_anthropic_merges_top_level_system_with_message_system() -> None:
    req = {
        "model": "minimax/MiniMax-M2.7",
        "system": "persona",
        "messages": [
            {"role": "system", "content": "task"},
            {"role": "user", "content": "hi"},
        ],
    }
    out = adapt_request_for_transport(AnthropicTransport(), req)
    assert out["system"] == "persona\n\ntask"
    assert out["messages"] == [{"role": "user", "content": "hi"}]


def test_normalize_adds_user_when_messages_empty_after_lift() -> None:
    out = normalize_anthropic_request_body(
        {
            "model": "MiniMax-M2.7",
            "messages": [{"role": "system", "content": "rank these"}],
        },
    )
    assert out["system"] == "rank these"
    assert out["messages"] == [{"role": "user", "content": "."}]


def test_anthropic_merges_multiple_system_blocks() -> None:
    req = {
        "model": "minimax/M",
        "messages": [
            {"role": "system", "content": "a"},
            {"role": "system", "content": "b"},
            {"role": "user", "content": "u"},
        ],
    }
    out = adapt_request_for_transport(AnthropicTransport(), req)
    assert out["system"] == "a\n\nb"


def test_anthropic_no_system_when_none_present() -> None:
    req = {
        "model": "claude",
        "messages": [{"role": "user", "content": "hi"}],
    }
    out = adapt_request_for_transport(AnthropicTransport(), req)
    assert "system" not in out


def test_does_not_mutate_input() -> None:
    req: dict[str, object] = {
        "model": "minimax/M",
        "messages": [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "u"},
        ],
    }
    original = {
        "model": req["model"],
        "messages": list(req["messages"]),  # type: ignore[arg-type]
    }
    adapt_request_for_transport(AnthropicTransport(), req)
    assert req["model"] == original["model"]
    assert req["messages"] == original["messages"]
