"""Decompose-failure → tier-B degradation in ``_run_cd_dispatch`` (`prd/04-getting-things-done.md`).

A deterministic decompose parse/schema fault must answer the user with a plain
tier-B pass on the same message, never the raw planner error string.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sevn.agent.executors.b_types import BTurnOutcome, ChannelPayload, ResolvedTierBModel
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import ChatCompletionsTransport
from sevn.agent.tracing.sink import NullTraceSink
from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
from sevn.config.workspace_config import parse_workspace_config
from sevn.gateway import agent_turn as agent_turn_mod
from sevn.gateway.agent_turn import _run_b_fallback_for_cd
from sevn.workspace.layout import WorkspaceLayout


def _workspace(tmp: Path) -> Any:
    return parse_workspace_config(
        {
            "schema_version": 1,
            "workspace_root": str(tmp),
            "security": {},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )


def _triage_c() -> TriageResult:
    return TriageResult.model_construct(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.C,
        first_message="On it.",
        tools=[],
        skills=[],
        mcp_servers_required=[],
        permission_scope_narrowing=None,
        confidence=0.78,
        requires_vision=False,
        requires_document=False,
        disregard=False,
    )


def _bundle() -> ResolvedTierBModel:
    transport = ChatCompletionsTransport(proxy_base_url="http://cd-b-fallback.test.invalid")
    return ResolvedTierBModel(
        model_id="openai/gpt-b",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-b", regime=BudgetRegime.FREE_LOCAL),
    )


def _patch_collaborators(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent_turn_mod, "_resolve_tier_b_bundle", lambda *_a, **_k: _bundle())
    monkeypatch.setattr(agent_turn_mod, "load_bootstrap_markdown_cached", lambda *_a, **_k: "")
    monkeypatch.setattr(agent_turn_mod, "orientation_block_for_workspace", lambda *_a, **_k: "")
    monkeypatch.setattr(agent_turn_mod, "tier_b_repo_access_prompt", lambda *_a, **_k: "")
    monkeypatch.setattr(agent_turn_mod, "_tool_context_for_turn", lambda **_k: MagicMock())
    monkeypatch.setattr(agent_turn_mod, "_plugin_hooks_from_router", lambda _r: None)


@pytest.mark.asyncio
async def test_b_fallback_delivers_answer_and_returns_true(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[str] = []

    async def _fake_route(*args: Any, **_k: Any) -> None:
        sent.append(args[4])

    async def _fake_run_b_turn(**_kwargs: Any) -> BTurnOutcome:
        return BTurnOutcome(
            status="completed",
            final_messages=(ChannelPayload(text="Here is the direct answer."),),
            escalation=None,
            rounds_used=1,
        )

    _patch_collaborators(monkeypatch)
    monkeypatch.setattr(agent_turn_mod, "run_b_turn", _fake_run_b_turn)
    monkeypatch.setattr(agent_turn_mod, "_route_assistant_text", _fake_route)

    delivered = await _run_b_fallback_for_cd(
        router=MagicMock(),
        workspace=_workspace(tmp_path),
        layout=WorkspaceLayout(tmp_path / "sevn.json", tmp_path),
        trace=NullTraceSink(),
        session_id="s1",
        correlation_id="c1",
        turn_span_id="span1",
        sess_channel="telegram",
        sess_user_id="u1",
        triage=_triage_c(),
        user_text="all this needs to be fixed",
        route_meta={},
        process=MagicMock(),
        bindings=MagicMock(),
        exe=MagicMock(),
        tool_set=MagicMock(),
        channel_adapter=MagicMock(),
        steer_buffer=None,
        had_triager_first=False,
        finalizer=None,
        timeout_s=30.0,
    )

    assert delivered is True
    assert sent == ["Here is the direct answer."]


@pytest.mark.asyncio
async def test_b_fallback_returns_false_when_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_run_b_turn(**_kwargs: Any) -> BTurnOutcome:
        return BTurnOutcome(
            status="failed",
            final_messages=(),
            escalation=None,
            rounds_used=1,
        )

    _patch_collaborators(monkeypatch)
    monkeypatch.setattr(agent_turn_mod, "run_b_turn", _fake_run_b_turn)

    delivered = await _run_b_fallback_for_cd(
        router=MagicMock(),
        workspace=_workspace(tmp_path),
        layout=WorkspaceLayout(tmp_path / "sevn.json", tmp_path),
        trace=NullTraceSink(),
        session_id="s1",
        correlation_id="c1",
        turn_span_id="span1",
        sess_channel="telegram",
        sess_user_id="u1",
        triage=_triage_c(),
        user_text="all this needs to be fixed",
        route_meta={},
        process=MagicMock(),
        bindings=MagicMock(),
        exe=MagicMock(),
        tool_set=MagicMock(),
        channel_adapter=MagicMock(),
        steer_buffer=None,
        had_triager_first=False,
        finalizer=None,
        timeout_s=30.0,
    )

    assert delivered is False
