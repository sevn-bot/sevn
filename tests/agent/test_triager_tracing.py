"""Triager ``triage.*`` span emission (`plan/full-tracing-eval-wave-plan.md` Wave T-1)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from sevn.agent.tracing.sink import TraceSink
from sevn.agent.triager.context import (
    ApprovedUserTurn,
    RegistrySnapshot,
    SessionView,
    TriagePromptContext,
)
from sevn.agent.triager.run import triage_turn
from sevn.config.workspace_config import WorkspaceConfig


class _RecordingTrace(TraceSink):
    """Capture ``emit`` calls for assertions."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    async def emit(self, event: Any) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        return None

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_triage_turn_emits_start_and_complete_with_attrs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.delenv("SEVN_TRIAGER_STUB_JSON", raising=False)
    trace = _RecordingTrace()
    turn_root = "turn-root-span-001"
    ws = WorkspaceConfig(
        schema_version=1,
        providers={"tier_default": {"triager": "openai:gpt-4o-mini"}},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    result = await triage_turn(
        workspace=ws,
        session=SessionView(session_id="sess-1"),
        incoming=ApprovedUserTurn(text="hello"),
        registry_snapshot=RegistrySnapshot(),
        triage_context=TriagePromptContext(current_message="hello", turn_id="turn-1"),
        trace=trace,
        turn_span_id=turn_root,
    )
    kinds = [e.kind for e in trace.events]
    assert "triage.start" in kinds
    assert "triage.complete" in kinds
    complete = next(e for e in trace.events if e.kind == "triage.complete")
    assert complete.parent_span_id == turn_root
    assert complete.attrs["intent"] == result.intent.value
    assert complete.attrs["complexity"] == result.complexity.value
    assert complete.attrs["model_id"] == "openai:gpt-4o-mini"
    assert complete.attrs["budget_regime"]
    assert complete.attrs["confidence"] == result.confidence
    blob = str(complete.attrs)
    assert "hello" not in blob
    assert "user_prompt" not in blob
    # D5: canned stub fast path bypasses ``structured_output_call`` — no segment attrs.
    assert "prep_ms" not in complete.attrs
    assert "model_ms" not in complete.attrs
    assert "serialize_ms" not in complete.attrs


@pytest.mark.asyncio
async def test_triage_turn_emits_segment_attrs_on_llm_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``triage.complete`` carries segment timings when the live LLM path runs."""
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "0")
    monkeypatch.setenv("SEVN_PROXY_URL", "http://triager-mock.test")
    trace = _RecordingTrace()
    turn_root = "turn-root-span-002"
    triage_payload = {
        "intent": "NEW_REQUEST",
        "complexity": "B",
        "first_message": "On it.",
        "tools": [],
        "skills": [],
        "mcp_servers_required": [],
        "confidence": 0.88,
        "requires_vision": False,
        "requires_document": False,
        "disregard": False,
    }

    async def fake_post(**kwargs: object) -> dict[str, object]:
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(triage_payload),
                    },
                },
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    monkeypatch.setattr(
        "sevn.agent.providers.transport.transport_http.post_llm_json",
        fake_post,
    )
    ws = WorkspaceConfig(
        schema_version=1,
        providers={
            "tier_default": {"triager": "openai:gpt-4o-mini"},
            "models": {"openai:gpt-4o-mini": {"transport": "chat_completions"}},
        },
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    result = await triage_turn(
        workspace=ws,
        session=SessionView(session_id="sess-llm"),
        incoming=ApprovedUserTurn(text="route this turn"),
        registry_snapshot=RegistrySnapshot(),
        triage_context=TriagePromptContext(
            current_message="route this turn",
            turn_id="turn-llm",
        ),
        trace=trace,
        turn_span_id=turn_root,
    )
    complete = next(e for e in trace.events if e.kind == "triage.complete")
    assert complete.parent_span_id == turn_root
    assert complete.attrs["intent"] == result.intent.value
    assert complete.attrs["complexity"] == result.complexity.value
    assert complete.attrs["model_id"] == "openai:gpt-4o-mini"
    assert complete.attrs["budget_regime"]
    assert complete.attrs["confidence"] == result.confidence
    for key in ("prep_ms", "model_ms", "serialize_ms"):
        assert key in complete.attrs
        assert isinstance(complete.attrs[key], (int, float))
    blob = str(complete.attrs)
    assert "route this turn" not in blob
    assert "user_prompt" not in blob


@pytest.mark.asyncio
async def test_triage_turn_emits_error_on_schema_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv("SEVN_TRIAGER_STUB_JSON", "{not-json")
    trace = _RecordingTrace()
    ws = WorkspaceConfig(
        schema_version=1,
        providers={"tier_default": {"triager": "openai:gpt-4o-mini"}},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    await triage_turn(
        workspace=ws,
        session=SessionView(session_id="sess-2"),
        incoming=ApprovedUserTurn(text="bad"),
        registry_snapshot=RegistrySnapshot(),
        triage_context=TriagePromptContext(current_message="bad", turn_id="turn-2"),
        trace=trace,
    )
    kinds = [e.kind for e in trace.events]
    assert "triage.error" in kinds
    assert "triage.complete" in kinds
    err = next(e for e in trace.events if e.kind == "triage.error")
    assert "error" in err.attrs
