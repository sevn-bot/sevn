"""One usage shape: priced per response, local, subscription, unknown (phase 2)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fakes.models import function_model
from support.chat import connected, fetch_all, load_modules, mint_id, ok, poll_rows, request


def _response(
    model: str | None,
    provider: str | None,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
) -> object:
    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.usage import RequestUsage

    return ModelResponse(
        parts=[TextPart(content="x")],
        model_name=model,
        provider_name=provider,
        usage=RequestUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
        ),
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


def test_pricing_errors_are_unknown_not_a_failed_turn() -> None:
    """``ModelResponse.cost()`` lets pricing errors through on purpose."""
    from sevn.runtime.usage import price_responses

    # genai-prices raises ValueError when cache reads exceed the input.
    broken = _response("claude-haiku-4-5", "anthropic", 10, 5, cache_read_tokens=500)
    assert price_responses([broken]) == (None, "unknown")
    # A response with no model name trips an assertion inside cost().
    nameless = _response(None, "anthropic", 10, 5)
    assert price_responses([nameless]) == (None, "unknown")
    assert price_responses([_response("", "anthropic", 10, 5)]) == (None, "unknown")


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
    # Anthropic's input_tokens leaves cache out; the shared shape counts it in.
    assert usage["input_tokens"] == 120 + 400 + 900
    assert usage["output_tokens"] == 30
    assert usage["cache_write_tokens"] == 400
    assert usage["cache_read_tokens"] == 900
    assert usage["requests"] == 2


def test_claude_tokens_count_cache_reads_and_writes() -> None:
    """A recorded spike turn: 6 uncached input, 37,923 cache reads, 3,913 writes."""
    from sevn.runtime.runtimes.claude import _map_result
    from sevn.runtime.usage import tokens_of

    event = _map_result(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "terminal_reason": None,
            "result": "done",
            "usage": {
                "input_tokens": 6,
                "output_tokens": 202,
                "cache_creation_input_tokens": 3913,
                "cache_read_input_tokens": 37923,
            },
            "total_cost_usd": 0.04,
            "num_turns": 1,
        }
    )
    assert event.usage is not None
    assert event.usage["input_tokens"] == 6 + 3913 + 37923
    assert tokens_of(event.usage) == 6 + 3913 + 37923 + 202


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


async def test_compaction_summary_is_billed_to_the_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    """The cheap-model summary is a paid request of the turn that triggered it."""
    from pydantic_ai.messages import ModelRequest, UserPromptPart
    from pydantic_ai.usage import RunUsage
    from sevn.runtime import compaction
    from sevn.runtime.runtimes.pydantic_ai import _usage
    from sevn.runtime.usage import begin_side_responses, price_responses

    summary = _response("claude-haiku-4-5", "anthropic", 2000, 100)

    class _Cheap:
        async def request(self, *_args: object) -> object:
            return summary

    async def cheap() -> object:
        return _Cheap()

    monkeypatch.setattr(compaction, "_cheap_model", cheap)
    begin_side_responses()
    messages = [
        ModelRequest(parts=[UserPromptPart(content=f"message {index} " * 40)])
        for index in range(10)
    ]
    compacted = await compaction.compact_messages(messages, model_window=100, estimated_tokens=90)
    assert len(compacted) < len(messages)
    usage = _usage(RunUsage(requests=1, input_tokens=10, output_tokens=5), [])
    expected, _ = price_responses([summary])
    assert usage["requests"] == 2
    assert usage["input_tokens"] == 2010
    assert usage["output_tokens"] == 105
    assert usage["cost_source"] == "price_table"
    assert usage["cost_usd"] == pytest.approx(expected)


def test_side_responses_start_empty_for_each_run() -> None:
    from sevn.runtime.usage import begin_side_responses, record_side_response, side_responses

    begin_side_responses()
    record_side_response(_response("claude-haiku-4-5", "anthropic", 1, 1))
    assert len(side_responses()) == 1
    begin_side_responses()
    assert side_responses() == []


def test_claude_error_results_keep_their_usage() -> None:
    from sevn.runtime.runtimes.claude import _map_result

    for native in (
        {"type": "result", "is_error": True, "subtype": "rate_limit"},
        {"type": "result", "terminal_reason": "aborted_streaming"},
    ):
        event = _map_result(
            {
                **native,
                "usage": {"input_tokens": 40, "output_tokens": 9},
                "total_cost_usd": 0.02,
                "num_turns": 2,
            }
        )
        assert event.kind == "error"
        assert event.usage is not None
        assert event.usage["requests"] == 2
        assert event.usage["output_tokens"] == 9
        assert event.usage["cost_source"] == "subscription"
        assert event.usage["estimated_usd"] == pytest.approx(0.02)


def test_a_failure_with_no_reported_usage_is_unknown() -> None:
    from sevn.runtime.errors import TurnError
    from sevn.runtime.turn_end import _failed_usage

    reported = {"requests": 1, "cost_usd": None, "cost_source": "subscription"}
    assert _failed_usage(TurnError("x", usage=reported)) is reported
    for exc in (TurnError("x"), RuntimeError("boom")):
        usage = _failed_usage(exc)
        assert usage["cost_source"] == "unknown"
        assert usage["cost_usd"] is None
