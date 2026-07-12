"""Provider.call telemetry emission tests (lane #1 W1)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from sevn.agent.adapters.tier_b_model import ResolvedTierBModel, build_tier_b_function_model
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import ChatCompletionsTransport
from sevn.agent.tracing import SQLiteSink
from sevn.agent.tracing.provider_call import PROVIDER_CALL_KIND, emit_provider_call


class _ScriptedChatTransport(ChatCompletionsTransport):
    def __init__(self) -> None:
        super().__init__(proxy_base_url="http://provider-call-telemetry.test.invalid")

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        _ = request
        return {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7},
        }


@pytest.mark.asyncio
async def test_emit_provider_call_persists_canonical_attrs(tmp_path: Path) -> None:
    db = tmp_path / "traces.db"
    sink = SQLiteSink(db)
    await emit_provider_call(
        sink,
        span_id="pc-1",
        parent_span_id="parent",
        session_id="sess-a",
        turn_id="turn-1",
        model_id="anthropic/claude-sonnet-4-6",
        regime="SUBSCRIPTION",
        tokens_in=100,
        tokens_out=50,
        transport="anthropic",
        tier="B",
        status="ok",
        ts_start_ns=1_000,
        ts_end_ns=2_000_000,
    )
    await sink.close()
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT kind, attrs_json FROM trace_events WHERE span_id = ?",
            ("pc-1",),
        ).fetchone()
        assert row is not None
        assert row[0] == PROVIDER_CALL_KIND
        attrs = json.loads(row[1])
        assert attrs["cost.tokens_in"] == 100
        assert attrs["cost.tokens_out"] == 50
        assert attrs["model.id"] == "anthropic/claude-sonnet-4-6"
        assert attrs["regime"] == "SUBSCRIPTION"
        assert attrs["transport"] == "anthropic"
        assert attrs["tier"] == "B"
        assert attrs["status"] == "ok"
        assert attrs["latency_ms"] > 0
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_tier_b_function_model_emits_provider_call(tmp_path: Path) -> None:
    db = tmp_path / "traces.db"
    sink = SQLiteSink(db)
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-4o-mini",
        transport=_ScriptedChatTransport(),
        budget=ModelBudget(model_id="openai/gpt-4o-mini", regime=BudgetRegime.PER_TOKEN),
    )
    model = build_tier_b_function_model(
        bundle=bundle,
        steer_buffer=None,
        trace=sink,
        session_id="sess-b",
        turn_id="turn-b",
        provider_round_counter=[0],
    )
    from pydantic_ai.messages import ModelRequest, UserPromptPart
    from pydantic_ai.models.function import AgentInfo, ModelRequestParameters

    def _info() -> AgentInfo:
        return AgentInfo(
            function_tools=[],
            allow_text_output=True,
            output_tools=[],
            model_settings=None,
            model_request_parameters=ModelRequestParameters(),
            instructions=None,
        )

    response = await model.function(
        [ModelRequest(parts=[UserPromptPart(content="hello")])],
        _info(),
    )
    assert response.parts
    await sink.close()
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT kind, attrs_json FROM trace_events WHERE kind = ?",
            (PROVIDER_CALL_KIND,),
        ).fetchall()
        assert len(rows) >= 1
        attrs = json.loads(rows[0][1])
        assert attrs["cost.tokens_in"] == 11
        assert attrs["cost.tokens_out"] == 7
        assert attrs["model.id"] == "openai/gpt-4o-mini"
        assert attrs["regime"] == "PER_TOKEN"
        assert attrs["transport"] == "chat_completions"
    finally:
        conn.close()
