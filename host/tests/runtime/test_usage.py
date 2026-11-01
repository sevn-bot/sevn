"""One usage shape: priced per response, local, subscription, unknown (phase 2)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fakes.models import function_model
from support.chat import connected, fetch_all, load_modules, mint_id, ok, poll_rows, request


def _response(model: str, provider: str | None, input_tokens: int, output_tokens: int) -> object:
    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.usage import RequestUsage

    return ModelResponse(
        parts=[TextPart(content="x")],
        model_name=model,
        provider_name=provider,
        usage=RequestUsage(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def test_priced_from_the_price_table() -> None:
    from genai_prices import Usage, calc_price
    from sevn.runtime.usage import price_responses

    cost, source = price_responses([_response("claude-haiku-4-5", "anthropic", 1000, 500)])
    expected = calc_price(
        Usage(input_tokens=1000, output_tokens=500), "claude-haiku-4-5", provider_id="anthropic"
    )
    assert source == "price_table"
    assert cost == pytest.approx(float(expected.total_price))
    assert cost is not None and cost > 0


def test_each_response_is_priced_on_its_own_size() -> None:
    from sevn.runtime.usage import price_responses

    one, _ = price_responses([_response("claude-sonnet-4-5", "anthropic", 150_000, 0)])
    two, _ = price_responses([_response("claude-sonnet-4-5", "anthropic", 150_000, 0)] * 2)
    merged, _ = price_responses([_response("claude-sonnet-4-5", "anthropic", 300_000, 0)])
    assert one is not None and two is not None and merged is not None
    assert two == pytest.approx(one * 2)
    # Sonnet 4.5 input above 200k tokens in one request costs more per token.
    assert merged > two


def test_local_and_unknown_models() -> None:
    from sevn.runtime.usage import price_responses

    assert price_responses([_response("llama3.2:3b", "ollama", 900, 100)]) == (0.0, "local")
    assert price_responses([_response("function:x", None, 900, 100)]) == (None, "unknown")
    mixed = [
        _response("claude-haiku-4-5", "anthropic", 10, 10),
        _response("function:x", None, 10, 10),
    ]
    assert price_responses(mixed) == (None, "unknown")


def test_combine_adds_runs_of_one_turn() -> None:
    from sevn.runtime.usage import combine, usage_record

    first = usage_record(
        {"requests": 1, "input_tokens": 100, "output_tokens": 10},
        cost_usd=0.5,
        cost_source="price_table",
    )
    second = usage_record(
        {"requests": 1, "input_tokens": 50, "output_tokens": 5},
        cost_usd=0.25,
        cost_source="price_table",
    )
    total = combine(first, second)
    assert total["requests"] == 2
    assert total["input_tokens"] == 150
    assert total["cost_usd"] == pytest.approx(0.75)
    assert total["cost_source"] == "price_table"
    assert combine({}, second) == second
    unknown = usage_record({}, cost_usd=None, cost_source="unknown")
    assert combine(first, unknown)["cost_usd"] is None
    assert combine(first, unknown)["cost_source"] == "unknown"
    local = usage_record({}, cost_usd=0.0, cost_source="local")
    assert combine(local, local)["cost_source"] == "local"
    assert combine(local, first)["cost_source"] == "price_table"


def test_claude_result_is_subscription_with_the_sdk_estimate() -> None:
    from sevn.runtime.runtimes.claude import _map_result

    event = _map_result(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "terminal_reason": None,
            "result": "done",
            "usage": {
                "input_tokens": 120,
                "output_tokens": 30,
                "cache_creation_input_tokens": 400,
                "cache_read_input_tokens": 900,
            },
            "total_cost_usd": 0.0123,
            "num_turns": 2,
        }
    )
    assert event.kind == "turn_finished"
    usage = event.usage
    assert usage is not None
    assert usage["cost_source"] == "subscription"
    assert usage["cost_usd"] is None
    assert usage["estimated_usd"] == pytest.approx(0.0123)
    assert usage["input_tokens"] == 120
    assert usage["output_tokens"] == 30
    assert usage["cache_write_tokens"] == 400
    assert usage["cache_read_tokens"] == 900
    assert usage["requests"] == 2


def _clear() -> None:
    from sevn.decisions.jev import use_client
    from sevn.runtime.models import use_model

    use_client(None)
    use_model(None)


async def test_pydantic_turn_stores_the_usage_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fakes.fake_jev import FakeJev
    from sevn.decisions.jev import use_client
    from sevn.runtime.models import use_model
    from sevn.runtime.worker import bind

    load_modules("sevn.api.bots", "sevn.api.messages")
    use_client(FakeJev(answers={}))
    use_model(function_model([{"kind": "text", "text": "ok"}]))
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            frame, _earlier = await request(
                client, "bots.create", {"name": "Nimbus", "op_id": mint_id("op_")}
            )
            bot = ok(frame)
            frame, _earlier = await request(
                client,
                "messages.send",
                {"bot_id": bot["id"], "text": "hi", "op_id": mint_id("op_")},
            )
            sent = ok(frame)
            await poll_rows(
                tmp_path,
                "SELECT status FROM jobs WHERE id = ?",
                (sent["job_id"],),
                lambda rows: bool(rows) and rows[0]["status"] == "done",
            )
            rows = fetch_all(
                tmp_path,
                "SELECT usage FROM turns WHERE agent_id = ? AND status = 'done'",
                (sent["agent_id"],),
            )
    finally:
        _clear()
    import json

    usage = json.loads(rows[0]["usage"])
    assert usage["requests"] == 1
    assert usage["cost_source"] == "unknown"
    assert usage["cost_usd"] is None
    assert usage["input_tokens"] > 0


async def test_auto_approved_runs_add_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from fakes.fake_jev import FakeJev
    from sevn.decisions.jev import use_client
    from sevn.runtime.models import use_model
    from sevn.runtime.worker import bind

    load_modules("sevn.api.bots", "sevn.api.messages")
    use_client(FakeJev(answers={}))
    use_model(
        function_model(
            [
                [{"kind": "tool", "name": "shell", "args": {"command": "printf hi"}}],
                [{"kind": "text", "text": "all done"}],
            ]
        )
    )
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            frame, _earlier = await request(
                client,
                "bots.create",
                {
                    "name": "Nimbus",
                    "access": "full",
                    "approval_policy": "auto",
                    "op_id": mint_id("op_"),
                },
            )
            bot = ok(frame)
            frame, _earlier = await request(
                client,
                "messages.send",
                {"bot_id": bot["id"], "text": "say hi", "op_id": mint_id("op_")},
            )
            sent = ok(frame)
            await poll_rows(
                tmp_path,
                "SELECT status FROM jobs WHERE id = ?",
                (sent["job_id"],),
                lambda rows: bool(rows) and rows[0]["status"] == "done",
            )
            rows = fetch_all(
                tmp_path,
                "SELECT usage FROM turns WHERE agent_id = ? AND status = 'done'",
                (sent["agent_id"],),
            )
    finally:
        _clear()
    usage = json.loads(rows[0]["usage"])
    assert usage["requests"] == 2
