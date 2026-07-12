"""Tier-B harness tests (`specs/14-executor-tier-b.md` §9)."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from sevn.agent.adapters.pydantic_adapter import register_pydantic_tools
from sevn.agent.adapters.tier_b_model import _wire_tool_defs
from sevn.agent.adapters.tier_b_tools import build_pydantic_tools_for_registry
from sevn.agent.adapters.tool_part_filter import MutableToolAllowlist
from sevn.agent.executors import b_harness as b_harness_mod
from sevn.agent.executors.b_harness import run_b_turn
from sevn.agent.executors.b_types import (
    TIER_B_SELF_ESCALATION_TEMPLATE,
    ResolvedTierBModel,
    SessionHandle,
    SteerInject,
)
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import ChatCompletionsTransport
from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
from sevn.config.workspace_config import SecurityWorkspaceConfig, WorkspaceConfig
from sevn.tools.base import FunctionTool, ToolDefinition, ToolExecutor, enveloped_success
from sevn.tools.cache import LoadedBodyCache
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.meta_loaders import attach_meta_loaders
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import ToolSet, merge_skill_manifests, snapshot_tool_set


def _openai_assistant_tool(name: str, arguments: str, *, call_id: str = "call-1") -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": arguments},
                        },
                    ],
                },
            },
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


def _openai_assistant_text(text: str) -> dict[str, Any]:
    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


class _ScriptedChatTransport(ChatCompletionsTransport):
    """``ChatCompletionsTransport`` that never hits the proxy (``complete`` overridden).

    ``complete_stream`` is overridden too so the tier-B streaming path stays
    hermetic: it replays the scripted ``complete`` payload as genuine per-character
    text deltas + a terminal ``StreamFinal`` (the same shape the real SSE
    reconstruction yields), exercising real progressive deltas without a socket.
    """

    def __init__(self, fn: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]) -> None:
        super().__init__(proxy_base_url="http://tier-b-harness.test.invalid")
        self._fn = fn
        self.requests: list[dict[str, Any]] = []

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        body = dict(request)
        self.requests.append(body)
        return await self._fn(body)

    async def complete_stream(self, request: dict[str, object]) -> Any:
        from sevn.agent.providers.transport import StreamFinal, StreamTextDelta

        payload = await self.complete(request)
        choices = payload.get("choices") or [{}]
        message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
        content = message.get("content")
        if isinstance(content, str) and content:
            for ch in content:
                yield StreamTextDelta(text=ch)
        yield StreamFinal(response=payload)


def _make_tick_executor() -> tuple[ToolExecutor, Any]:
    """Minimal registry: ``tick`` + meta loaders (``load_tool`` / ``load_skill``)."""

    exe = ToolExecutor(default_timeout_seconds=30.0)

    async def _tick(_ctx: ToolContext) -> str:
        return enveloped_success({"tick": True})

    tick_def = ToolDefinition(
        name="tick",
        category="meta",
        description="Deterministic harness tick.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
    )
    exe.register(FunctionTool(tick_def, _tick))

    integ_def = ToolDefinition(
        name="integration_call",
        category="integrations",
        description="Test integration surface.",
        parameters={
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "method": {"type": "string"},
                "args": {"type": "object"},
            },
            "required": ["service", "method", "args"],
        },
        enabled=True,
    )

    async def _integ(_ctx: ToolContext, **kwargs: Any) -> str:
        _ = kwargs
        return enveloped_success({"integration": True})

    exe.register(FunctionTool(integ_def, _integ))

    merged = merge_skill_manifests(None)
    native_map = {d.name: d for d in exe.definitions()}
    attach_meta_loaders(
        exe,
        native_definitions=dict(native_map),
        mcp_definitions={},
        skill_descriptions=merged,
        mcp_tool_names=frozenset(),
    )
    ts = snapshot_tool_set(
        exe,
        registry_version=77,
        skill_descriptions=merged,
        skill_inventory={},
        mcp_definitions=(),
        mcp_names=frozenset(),
    )
    return exe, ts


def _base_triage(*, tools: list[str], narrowing: str | None = None) -> TriageResult:
    return TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="hello harness",
        tools=tools,
        skills=[],
        mcp_servers_required=[],
        permission_scope_narrowing=narrowing,
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
    )


def _workspace(tmp: Path) -> WorkspaceConfig:
    return WorkspaceConfig(
        schema_version=1,
        workspace_root=str(tmp),
        security=SecurityWorkspaceConfig(),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )


@pytest.mark.asyncio
async def test_round_budget_escalates(tmp_path: Path) -> None:
    exe, ts = _make_tick_executor()
    triage = _base_triage(tools=["tick"])

    step = 0

    async def _loop(_req: dict[str, Any]) -> dict[str, Any]:
        nonlocal step
        step += 1
        return _openai_assistant_tool("tick", "{}", call_id=f"c{step}")

    transport = _ScriptedChatTransport(_loop)
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-test",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-test", regime=BudgetRegime.FREE_LOCAL),
    )

    outcome = await run_b_turn(
        workspace=_workspace(tmp_path),
        session=SessionHandle(session_id="s1"),
        turn_id="t1",
        triage=triage,
        incoming_text="loop",
        tool_set=ts,
        body_cache=LoadedBodyCache(capacity=8),
        tool_executor=exe,
        transport_bundle=bundle,
        trace=None,
        steer_buffer=None,
        tool_context=ToolContext(
            session_id="s1",
            workspace_path=tmp_path,
            workspace_id="w",
            registry_version=ts.registry_version,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
            turn_id="t1",
        ),
        max_rounds=4,
    )
    assert outcome.status == "escalated"
    assert outcome.escalation is not None
    assert outcome.escalation.reason == "round_budget_exhausted"
    assert outcome.escalation.target_tier == "C"
    assert step == 4


@pytest.mark.asyncio
async def test_load_tool_then_tick_completes(tmp_path: Path) -> None:
    exe, ts = _make_tick_executor()
    triage = _base_triage(tools=["tick"])

    plan = iter(
        [
            _openai_assistant_tool("load_tool", '{"name":"tick"}', call_id="c1"),
            _openai_assistant_tool("tick", "{}", call_id="c2"),
            _openai_assistant_text("done."),
        ],
    )

    async def _seq(_req: dict[str, Any]) -> dict[str, Any]:
        return next(plan)

    transport = _ScriptedChatTransport(_seq)
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-test",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-test", regime=BudgetRegime.FREE_LOCAL),
    )

    outcome = await run_b_turn(
        workspace=_workspace(tmp_path),
        session=SessionHandle(session_id="s2"),
        turn_id="t2",
        triage=triage,
        incoming_text="ping",
        tool_set=ts,
        body_cache=LoadedBodyCache(capacity=8),
        tool_executor=exe,
        transport_bundle=bundle,
        trace=None,
        steer_buffer=None,
        tool_context=ToolContext(
            session_id="s2",
            workspace_path=tmp_path,
            workspace_id="w",
            registry_version=ts.registry_version,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
            turn_id="t2",
        ),
    )
    assert outcome.status == "completed"
    assert any("done." in m.text for m in outcome.final_messages)


@pytest.mark.asyncio
async def test_load_tool_round_does_not_count_toward_round_budget(tmp_path: Path) -> None:
    """``load_tool`` / ``load_skill`` must not consume ``gateway.budget.tier_b_rounds``.

    With ``max_rounds=2``, legacy counting (load + tick) would exhaust the cap before
    the final text reply; excluding meta loaders leaves one counted round for ``tick``.
    """
    exe, ts = _make_tick_executor()
    triage = _base_triage(tools=["tick"])

    plan = iter(
        [
            _openai_assistant_tool("load_tool", '{"name":"tick"}', call_id="c1"),
            _openai_assistant_tool("tick", "{}", call_id="c2"),
            _openai_assistant_text("done."),
        ],
    )

    async def _seq(_req: dict[str, Any]) -> dict[str, Any]:
        return next(plan)

    transport = _ScriptedChatTransport(_seq)
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-test",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-test", regime=BudgetRegime.FREE_LOCAL),
    )

    outcome = await run_b_turn(
        workspace=_workspace(tmp_path),
        session=SessionHandle(session_id="s2b"),
        turn_id="t2b",
        triage=triage,
        incoming_text="ping",
        tool_set=ts,
        body_cache=LoadedBodyCache(capacity=8),
        tool_executor=exe,
        transport_bundle=bundle,
        trace=None,
        steer_buffer=None,
        tool_context=ToolContext(
            session_id="s2b",
            workspace_path=tmp_path,
            workspace_id="w",
            registry_version=ts.registry_version,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
            turn_id="t2b",
        ),
        max_rounds=2,
    )
    assert outcome.status == "completed"
    assert outcome.rounds_used == 1
    assert any("done." in m.text for m in outcome.final_messages)


@pytest.mark.asyncio
async def test_request_escalation_user_visible_line(tmp_path: Path) -> None:
    exe, ts = _make_tick_executor()
    triage = _base_triage(tools=["tick"])

    calls = [0]

    async def _esc(_req: dict[str, Any]) -> dict[str, Any]:
        calls[0] += 1
        if calls[0] == 1:
            return _openai_assistant_tool(
                "request_escalation",
                '{"reason":"user_requested","target_tier":"C"}',
                call_id="ce1",
            )
        return _openai_assistant_text("OK.")

    transport = _ScriptedChatTransport(_esc)
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-test",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-test", regime=BudgetRegime.FREE_LOCAL),
    )

    outcome = await run_b_turn(
        workspace=_workspace(tmp_path),
        session=SessionHandle(session_id="s3"),
        turn_id="t3",
        triage=triage,
        incoming_text="go deeper",
        tool_set=ts,
        body_cache=LoadedBodyCache(capacity=8),
        tool_executor=exe,
        transport_bundle=bundle,
        trace=None,
        steer_buffer=None,
        tool_context=ToolContext(
            session_id="s3",
            workspace_path=tmp_path,
            workspace_id="w",
            registry_version=ts.registry_version,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
            turn_id="t3",
        ),
    )
    assert outcome.status == "escalated"
    assert outcome.escalation is not None
    assert outcome.escalation.reason == "user_requested"
    expected = TIER_B_SELF_ESCALATION_TEMPLATE.format(tier="C")
    assert any(expected in m.text for m in outcome.final_messages)


@pytest.mark.asyncio
async def test_deny_integration_blocks_integration_call(tmp_path: Path) -> None:
    exe, ts = _make_tick_executor()
    triage = _base_triage(tools=["tick", "integration_call"], narrowing="deny_integration")

    plan = iter(
        [
            _openai_assistant_tool(
                "load_tool",
                '{"name":"integration_call"}',
                call_id="i0",
            ),
            _openai_assistant_tool(
                "integration_call",
                '{"service":"x","method":"m","args":{}}',
                call_id="i1",
            ),
            _openai_assistant_text("finished after deny."),
        ],
    )

    async def _seq(_req: dict[str, Any]) -> dict[str, Any]:
        return next(plan)

    transport = _ScriptedChatTransport(_seq)
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-test",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-test", regime=BudgetRegime.FREE_LOCAL),
    )

    outcome = await run_b_turn(
        workspace=_workspace(tmp_path),
        session=SessionHandle(session_id="s4"),
        turn_id="t4",
        triage=triage,
        incoming_text="call integration",
        tool_set=ts,
        body_cache=LoadedBodyCache(capacity=8),
        tool_executor=exe,
        transport_bundle=bundle,
        trace=None,
        steer_buffer=None,
        tool_context=ToolContext(
            session_id="s4",
            workspace_path=tmp_path,
            workspace_id="w",
            registry_version=ts.registry_version,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
            turn_id="t4",
        ),
    )
    assert outcome.status == "failed"
    assert outcome.failure_detail == "triager_bound_tools_unused"
    bodies = json.dumps(transport.requests)
    assert ToolResultCode.PERMISSION_DENIED.value in bodies


@pytest.mark.asyncio
async def test_steer_injected_before_first_provider_call(tmp_path: Path) -> None:
    exe, ts = _make_tick_executor()
    triage = _base_triage(tools=["tick"])

    async def _one(_req: dict[str, Any]) -> dict[str, Any]:
        return _openai_assistant_text("ack")

    transport = _ScriptedChatTransport(_one)
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-test",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-test", regime=BudgetRegime.FREE_LOCAL),
    )
    steer = SteerInject(pending_text="priority: tests")

    await run_b_turn(
        workspace=_workspace(tmp_path),
        session=SessionHandle(session_id="s5"),
        turn_id="t5",
        triage=triage,
        incoming_text="hi",
        tool_set=ts,
        body_cache=LoadedBodyCache(capacity=8),
        tool_executor=exe,
        transport_bundle=bundle,
        trace=None,
        steer_buffer=steer,
        tool_context=ToolContext(
            session_id="s5",
            workspace_path=tmp_path,
            workspace_id="w",
            registry_version=ts.registry_version,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
            turn_id="t5",
        ),
    )
    assert transport.requests, "expected at least one provider request"
    msgs = transport.requests[0].get("messages")
    assert isinstance(msgs, list)
    dumped = json.dumps(msgs)
    assert "[Owner steer] priority: tests" in dumped


def test_instructions_exclude_json_schema_literals() -> None:
    """Regression: §9 - no full ``parameters`` JSON embedded in static instructions."""

    alpha = ToolDefinition(
        name="alpha_tool",
        category="meta",
        description="Catalog row with nested JSON schema (not inlined here).",
        parameters={
            "type": "object",
            "properties": {"inner": {"type": "object", "properties": {"x": {"type": "string"}}}},
        },
    )
    ts = ToolSet(
        registry_version=3,
        native=(alpha,),
        mcp=(),
        skill_descriptions={},
    )
    triage = _base_triage(tools=["alpha_tool"])
    reg = register_pydantic_tools(ts, triage, add_core_tools=False)
    text = b_harness_mod._description_only_instructions(reg)
    assert "inner" not in text
    assert '"properties"' not in text
    assert "alpha_tool" in text


@pytest.mark.asyncio
async def test_run_b_turn_rejects_non_b_triage(tmp_path: Path) -> None:
    exe, ts = _make_tick_executor()
    triage = TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.A,
        first_message="nope",
        tools=["tick"],
        skills=[],
        mcp_servers_required=[],
        confidence=0.5,
        requires_vision=False,
        requires_document=False,
    )
    transport = _ScriptedChatTransport(lambda _r: _openai_assistant_text("x"))
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-test",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-test", regime=BudgetRegime.FREE_LOCAL),
    )
    with pytest.raises(ValueError, match="complexity == B"):
        await run_b_turn(
            workspace=_workspace(tmp_path),
            session=SessionHandle(session_id="sx"),
            turn_id="tx",
            triage=triage,
            incoming_text="x",
            tool_set=ts,
            body_cache=LoadedBodyCache(capacity=8),
            tool_executor=exe,
            transport_bundle=bundle,
            trace=None,
            steer_buffer=None,
            tool_context=ToolContext(
                session_id="sx",
                workspace_path=tmp_path,
                workspace_id="w",
                registry_version=ts.registry_version,
                trace=None,
                permissions=AllowAllPermissionPolicy(),
                turn_id="tx",
            ),
        )


class _RecordingTrace:
    """Minimal ``TraceSink`` capturing ``emit`` calls for assertions."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    async def emit(self, event: Any) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        return None

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_tool_dispatch_emits_snapshot_checkpoints(tmp_path: Path) -> None:
    """Tier-B tool calls emit ``snapshot.checkpoint`` rows (§4.4 hook points)."""

    rec = _RecordingTrace()
    exe, ts = _make_tick_executor()
    triage = _base_triage(tools=["tick"])
    plan = iter(
        [
            _openai_assistant_tool("load_tool", '{"name":"tick"}', call_id="c1"),
            _openai_assistant_tool("tick", "{}", call_id="c2"),
            _openai_assistant_text("done."),
        ],
    )

    async def _seq(_req: dict[str, Any]) -> dict[str, Any]:
        return next(plan)

    transport = _ScriptedChatTransport(_seq)
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-test",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-test", regime=BudgetRegime.FREE_LOCAL),
    )
    outcome = await run_b_turn(
        workspace=_workspace(tmp_path),
        session=SessionHandle(session_id="s3"),
        turn_id="t3",
        triage=triage,
        incoming_text="ping",
        tool_set=ts,
        body_cache=LoadedBodyCache(capacity=8),
        tool_executor=exe,
        transport_bundle=bundle,
        trace=rec,
        steer_buffer=None,
        tool_context=ToolContext(
            session_id="s3",
            workspace_path=tmp_path,
            workspace_id="w",
            registry_version=ts.registry_version,
            trace=rec,
            permissions=AllowAllPermissionPolicy(),
            turn_id="t3",
        ),
    )
    assert outcome.status == "completed"
    kinds = [
        e.attrs.get("checkpoint_kind")
        for e in rec.events
        if getattr(e, "kind", None) == "snapshot.checkpoint"
    ]
    assert "tool.before" in kinds
    assert "tool.after" in kinds
    checkpoint_events = [e for e in rec.events if e.kind == "snapshot.checkpoint"]
    tick_before = next(
        e
        for e in checkpoint_events
        if e.attrs.get("checkpoint_kind") == "tool.before"
        and e.attrs.get("state", {}).get("name") == "tick"
    )
    assert "arguments" in tick_before.attrs["state"]


def test_is_opener_only_output_flags_bare_openers() -> None:
    """P2: opener-only / echo-only / empty finals are classified as no-answer."""

    opener = "On it — checking now."
    is_opener_only = b_harness_mod._is_opener_only_output
    # Empty output is no answer.
    assert is_opener_only("", opener) is True
    assert is_opener_only("   ", opener) is True
    # A verbatim echo of the opener carries no body.
    assert is_opener_only(opener, opener) is True
    # A restated opener with a trailing colon and no list following.
    assert is_opener_only("Here you go — the full list of my tools:", opener) is True
    # Re-acking with new filler ("On it — re-pulling the registry list.") then nothing.
    assert is_opener_only("On it — re-pulling the registry list.", opener) is True


def test_is_opener_only_output_keeps_legitimate_short_answers() -> None:
    """A short answer that merely STARTS like an opener must NOT be flagged."""

    opener = "On it — checking now."
    is_opener_only = b_harness_mod._is_opener_only_output
    # A real list rendered after the (stripped) opener echo.
    assert (
        is_opener_only(
            "On it — checking now.\n\nTools: read, glob, list_registry, web_search.",
            opener,
        )
        is False
    )
    # A bare list with no opener at all.
    assert is_opener_only("- read\n- glob\n- list_registry", opener) is False
    # A short factual answer that happens to begin with an opener word.
    assert is_opener_only("OK — the workspace has 3 folders: src, docs, logs.", opener) is False
    # "Got it" used as a real (long-enough) sentence carrying content.
    assert (
        is_opener_only("Got the temperature in Amsterdam: it is 14C and raining.", opener) is False
    )


@pytest.mark.asyncio
async def test_opener_only_final_is_reclassified_as_failed(tmp_path: Path) -> None:
    """An executor that ships only the triager opener is treated as a failed/empty turn.

    The harness must NOT return ``completed`` with the bare opener as the final
    message; instead it returns ``failed`` with empty ``final_messages`` so the
    gateway runs its widened-retry / typed no-answer path (`PROBLEMS.md` P2).
    """

    exe, ts = _make_tick_executor()
    # ``_base_triage`` sets first_message="hello harness" (the delivered opener).
    triage = _base_triage(tools=["tick"])
    steer = SteerInject()

    async def _opener_only(_req: dict[str, Any]) -> dict[str, Any]:
        # Model parrots/extends the opener with no substantive body.
        return _openai_assistant_text("hello harness — let me pull that now.")

    transport = _ScriptedChatTransport(_opener_only)
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-test",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-test", regime=BudgetRegime.FREE_LOCAL),
    )
    outcome = await run_b_turn(
        workspace=_workspace(tmp_path),
        session=SessionHandle(session_id="s-opener"),
        turn_id="t-opener",
        triage=triage,
        incoming_text="list all your tools",
        tool_set=ts,
        body_cache=LoadedBodyCache(capacity=8),
        tool_executor=exe,
        transport_bundle=bundle,
        trace=None,
        steer_buffer=steer,
        tool_context=ToolContext(
            session_id="s-opener",
            workspace_path=tmp_path,
            workspace_id="w",
            registry_version=ts.registry_version,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
            turn_id="t-opener",
        ),
        max_rounds=4,
    )
    assert outcome.status == "failed"
    assert outcome.final_messages == ()
    assert outcome.failure_detail is not None
    assert "opener-only" in outcome.failure_detail
    # Mode A fix: the opener-only reclassify now queues a corrective steer for the retry.
    pending = steer.pop_pending()
    assert pending is not None
    assert "opener" in pending.lower()
    assert "tick" in pending.lower()


@pytest.mark.asyncio
async def test_substantive_final_starting_like_opener_completes(tmp_path: Path) -> None:
    """A final that starts like the opener but carries the answer still completes."""

    exe, ts = _make_tick_executor()
    triage = _base_triage(tools=[])

    async def _with_body(_req: dict[str, Any]) -> dict[str, Any]:
        return _openai_assistant_text(
            "hello harness\n\nTools: read, glob, list_registry, web_search.",
        )

    transport = _ScriptedChatTransport(_with_body)
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-test",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-test", regime=BudgetRegime.FREE_LOCAL),
    )
    outcome = await run_b_turn(
        workspace=_workspace(tmp_path),
        session=SessionHandle(session_id="s-body"),
        turn_id="t-body",
        triage=triage,
        incoming_text="list all your tools",
        tool_set=ts,
        body_cache=LoadedBodyCache(capacity=8),
        tool_executor=exe,
        transport_bundle=bundle,
        trace=None,
        steer_buffer=None,
        tool_context=ToolContext(
            session_id="s-body",
            workspace_path=tmp_path,
            workspace_id="w",
            registry_version=ts.registry_version,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
            turn_id="t-body",
        ),
        max_rounds=4,
    )
    assert outcome.status == "completed"
    assert any("list_registry" in m.text for m in outcome.final_messages)


def test_motion_promise_markers_shrunk_to_core_substrings() -> None:
    """W5.2: motion-promise list is materially smaller; quote-specific one-offs removed."""

    from sevn.agent.openers import MOTION_PROMISE_MARKERS

    assert len(MOTION_PROMISE_MARKERS) <= 10
    assert "doing" in MOTION_PROMISE_MARKERS
    assert "executing" in MOTION_PROMISE_MARKERS
    assert "for real this time" not in MOTION_PROMISE_MARKERS
    assert "talking is done" not in MOTION_PROMISE_MARKERS
    assert "walk the talk" not in MOTION_PROMISE_MARKERS


def test_is_promised_but_idle_flags_motion_promises() -> None:
    """P4: zero-tool finals that only promise motion are flagged ('all talk, no walk')."""

    opener = "On it — checking now."
    is_idle = b_harness_mod._is_promised_but_idle
    # The exact live-session offenders.
    assert (
        is_idle(rounds_used=0, text="On it — rendering the markdown to PDF now.", opener=opener)
        is True
    )
    assert is_idle(rounds_used=0, text="Right. Talking is done. Doing.", opener=opener) is True
    assert is_idle(rounds_used=0, text="Fair. Executing now.", opener=opener) is True
    # A second contentless ack distinct from the opener.
    assert is_idle(rounds_used=0, text="Let me do it now.", opener=opener) is True


def test_is_promised_but_idle_ignores_real_work_and_answers() -> None:
    """A turn that ran a tool, or carries real data, is never flagged."""

    opener = "On it — checking now."
    is_idle = b_harness_mod._is_promised_but_idle
    # A tool ran this turn — never a P4 hit even if the text reads like a promise.
    assert is_idle(rounds_used=1, text="Executing now.", opener=opener) is False
    # A real short answer with data.
    assert (
        is_idle(
            rounds_used=0,
            text="Done — the PDF is 3 pages and lives at out/report.pdf.",
            opener=opener,
        )
        is False
    )
    # Inline content past a colon clears the flag.
    assert is_idle(rounds_used=0, text="Doing: read, glob, list_registry.", opener=opener) is False
    # Multi-line output rendered an answer on later lines.
    assert is_idle(rounds_used=0, text="On it.\n\n- read\n- glob", opener=opener) is False
    # A long paragraph that merely mentions a promise word is not a bare promise.
    long_body = (
        "I reviewed the gateway turn spine and the executor finalize path; the "
        "rendering step is wired correctly and nothing is blocking it right now."
    )
    assert is_idle(rounds_used=0, text=long_body, opener=opener) is False


@pytest.mark.asyncio
async def test_promised_but_idle_final_is_failed_and_injects_steer(tmp_path: Path) -> None:
    """A zero-tool motion-promise finalize is reclassified failed and steers a retry.

    The harness must NOT ship the bare promise; it returns ``failed`` with empty
    ``final_messages`` (so the gateway runs its widened-retry / typed no-answer
    path) and injects a steer telling the next attempt to actually act
    (`PROBLEMS.md` P4 — "you just talk, but don't walk the talk").
    """

    exe, ts = _make_tick_executor()
    triage = _base_triage(tools=[])
    steer = SteerInject()

    async def _promise_only(_req: dict[str, Any]) -> dict[str, Any]:
        # Model promises motion but never calls a tool (rounds_used == 0).
        return _openai_assistant_text("Right. Talking is done. Doing.")

    transport = _ScriptedChatTransport(_promise_only)
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-test",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-test", regime=BudgetRegime.FREE_LOCAL),
    )
    outcome = await run_b_turn(
        workspace=_workspace(tmp_path),
        session=SessionHandle(session_id="s-p4"),
        turn_id="t-p4",
        triage=triage,
        incoming_text="render the markdown to pdf",
        tool_set=ts,
        body_cache=LoadedBodyCache(capacity=8),
        tool_executor=exe,
        transport_bundle=bundle,
        trace=None,
        steer_buffer=steer,
        tool_context=ToolContext(
            session_id="s-p4",
            workspace_path=tmp_path,
            workspace_id="w",
            registry_version=ts.registry_version,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
            turn_id="t-p4",
        ),
        max_rounds=4,
    )
    assert outcome.status == "failed"
    assert outcome.final_messages == ()
    assert outcome.failure_detail is not None
    assert "promised_but_idle" in outcome.failure_detail
    # The guard mirrors tool_unavailable_claim: a steer is queued for the retry.
    pending = steer.pop_pending()
    assert pending is not None
    assert "do not send another acknowledgement" in pending.lower()


@pytest.mark.asyncio
async def test_triager_bound_tools_unused_long_answer_fails(tmp_path: Path) -> None:
    """G0: zero-tool finalize with bound tools but a long fabricated answer is failed."""

    exe, ts = _make_tick_executor()
    triage = _base_triage(tools=["tick"])
    steer = SteerInject()
    long_answer = (
        "Bitcoin is trading near $67,400 on major exchanges as of this morning. "
        "Spot volume is elevated and funding rates remain positive across perpetual "
        "markets — I pulled this from the live ticker feed."
    )

    async def _fabricated(_req: dict[str, Any]) -> dict[str, Any]:
        return _openai_assistant_text(long_answer)

    transport = _ScriptedChatTransport(_fabricated)
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-test",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-test", regime=BudgetRegime.FREE_LOCAL),
    )
    outcome = await run_b_turn(
        workspace=_workspace(tmp_path),
        session=SessionHandle(session_id="s-g0"),
        turn_id="t-g0",
        triage=triage,
        incoming_text="what is the bitcoin price right now?",
        tool_set=ts,
        body_cache=LoadedBodyCache(capacity=8),
        tool_executor=exe,
        transport_bundle=bundle,
        trace=None,
        steer_buffer=steer,
        tool_context=ToolContext(
            session_id="s-g0",
            workspace_path=tmp_path,
            workspace_id="w",
            registry_version=ts.registry_version,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
            turn_id="t-g0",
        ),
        max_rounds=4,
    )
    assert outcome.status == "failed"
    assert outcome.final_messages == ()
    assert outcome.failure_detail == "triager_bound_tools_unused"
    pending = steer.pop_pending()
    assert pending is not None
    assert "tick" in pending


@pytest.mark.asyncio
async def test_identity_question_zero_tool_answer_delivered(tmp_path: Path) -> None:
    """G0 is intent-gated: an identity question answered from context is delivered, not discarded.

    transcript-review-2026-06-22: "which LLM model are you using?" bound ``read`` but the model
    answered correctly from the system prompt with zero tool rounds. G0 used to discard it into a
    canned "something went wrong"; identity/capability intents are now exempt (answerable from
    context), while live-data fabrications stay blocked (see ``..._long_answer_fails``).
    """
    exe, ts = _make_tick_executor()
    triage = _base_triage(tools=["read"])
    steer = SteerInject()

    async def _direct_answer(_req: dict[str, Any]) -> dict[str, Any]:
        return _openai_assistant_text("From the system prompt: MiniMax-M3, developed by MiniMax.")

    transport = _ScriptedChatTransport(_direct_answer)
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-test",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-test", regime=BudgetRegime.FREE_LOCAL),
    )
    outcome = await run_b_turn(
        workspace=_workspace(tmp_path),
        session=SessionHandle(session_id="s-id"),
        turn_id="t-id",
        triage=triage,
        incoming_text="which LLM model are you using?",
        tool_set=ts,
        body_cache=LoadedBodyCache(capacity=8),
        tool_executor=exe,
        transport_bundle=bundle,
        trace=None,
        steer_buffer=steer,
        tool_context=ToolContext(
            session_id="s-id",
            workspace_path=tmp_path,
            workspace_id="w",
            registry_version=ts.registry_version,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
            turn_id="t-id",
        ),
        max_rounds=4,
    )
    assert outcome.status == "completed"
    assert outcome.final_messages != ()
    assert "MiniMax-M3" in outcome.final_messages[-1].text


@pytest.mark.asyncio
async def test_triager_bound_tools_unused_skips_when_bound_tool_succeeded(
    tmp_path: Path,
) -> None:
    """G0 does not fire when a bound tool returned ok=true this turn."""

    exe, ts = _make_tick_executor()
    triage = _base_triage(tools=["tick"])
    steer = SteerInject()
    step = 0

    async def _tick_then_answer(_req: dict[str, Any]) -> dict[str, Any]:
        nonlocal step
        step += 1
        if step == 1:
            return _openai_assistant_tool("tick", "{}", call_id="c-g0-ok")
        return _openai_assistant_text("Tick succeeded — price is $67,400.")

    transport = _ScriptedChatTransport(_tick_then_answer)
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-test",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-test", regime=BudgetRegime.FREE_LOCAL),
    )
    outcome = await run_b_turn(
        workspace=_workspace(tmp_path),
        session=SessionHandle(session_id="s-g0-ok"),
        turn_id="t-g0-ok",
        triage=triage,
        incoming_text="what is the bitcoin price right now?",
        tool_set=ts,
        body_cache=LoadedBodyCache(capacity=8),
        tool_executor=exe,
        transport_bundle=bundle,
        trace=None,
        steer_buffer=steer,
        tool_context=ToolContext(
            session_id="s-g0-ok",
            workspace_path=tmp_path,
            workspace_id="w",
            registry_version=ts.registry_version,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
            turn_id="t-g0-ok",
        ),
        max_rounds=4,
    )
    assert outcome.status == "completed"
    assert steer.pop_pending() is None


def test_triager_bound_tools_unused_gateway_retry_warranted() -> None:
    """Failed G0 outcomes with empty finals warrant the widened-retry path."""

    from types import SimpleNamespace

    from sevn.gateway.agent_turn import _tier_b_full_index_retry_warranted

    failed = SimpleNamespace(
        status="failed",
        final_messages=(),
        had_tool_failures=False,
        failure_detail="triager_bound_tools_unused",
    )
    assert _tier_b_full_index_retry_warranted(no_answer_reason=None, outcome=failed) is True


def test_triager_bound_tools_satisfied_counts_skills_and_codemode() -> None:
    """D0b counting: skills via load/run_skill_script; CodeMode lenient trace."""

    from sevn.agent.grounding import triager_bound_tools_satisfied

    assert (
        triager_bound_tools_satisfied(
            bound_tools=(),
            bound_skills=("pdf",),
            successful_tools_called=frozenset({"load_skill"}),
            successful_skills_called=frozenset({"pdf"}),
            codemode_bound_tools_called=frozenset(),
        )
        is True
    )
    assert (
        triager_bound_tools_satisfied(
            bound_tools=("serp",),
            bound_skills=(),
            successful_tools_called=frozenset({"run_code"}),
            successful_skills_called=frozenset(),
            codemode_bound_tools_called=frozenset({"serp"}),
        )
        is True
    )
    assert (
        triager_bound_tools_satisfied(
            bound_tools=("list_registry", "read"),
            bound_skills=(),
            successful_tools_called=frozenset({"list_registry"}),
            successful_skills_called=frozenset(),
            codemode_bound_tools_called=frozenset(),
        )
        is True
    )


def test_build_pydantic_tools_for_registry_includes_unbound_tools(tmp_path: Path) -> None:
    """P3: full-registry agent tools enable auto-grant dispatch without rebuild."""
    exe, ts = _make_tick_executor()
    reg = register_pydantic_tools(ts, _base_triage(tools=["tick"]))
    names = [t.name for t in build_pydantic_tools_for_registry(exe, reg)]
    assert "tick" in names
    assert "load_tool" in names


def test_wire_tool_defs_honors_mutable_allowlist() -> None:
    """P3: provider wire exposes only triager-bound tools until auto-grant widens."""
    from pydantic_ai.tools import ToolDefinition as PAToolDefinition

    defs = [
        PAToolDefinition(name="read", description="", parameters_json_schema={}),
        PAToolDefinition(name="glob", description="", parameters_json_schema={}),
    ]
    allow = MutableToolAllowlist(
        base=frozenset({"read"}),
        registry_names=frozenset({"read", "glob"}),
    )
    allow.grant_registry_tool("glob")
    out = _wire_tool_defs(defs, allow)
    assert [d.name for d in out] == ["read", "glob"]
