"""Unit tests for Triager assembly and post-processing (`specs/13-rlm-triager.md` §9)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sevn.agent.triager.context import (
    ApprovedUserTurn,
    RegistryIndexEntry,
    RegistrySnapshot,
    SessionView,
    TriagePromptContext,
)
from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
from sevn.agent.triager.prompt import GROUP_TRIAGE_INSTRUCTION_V1, build_triager_prompt_segments
from sevn.agent.triager.run import (
    StructuredOutputCallResult,
    _apply_tier_a_scope_guard,
    _tier_a_first_message_shape_overstepped,
    extract_json_payload,
    finalize_triage_result,
    triage_turn,
)
from sevn.config.workspace_config import TriagerWorkspaceConfig, parse_workspace_config
from sevn.storage import apply_migrations, connect_sqlite

_FIXTURE_TRIAGER = Path(__file__).resolve().parents[1] / "fixtures" / "triager"


def _stub_structured_output(json_payload: str) -> StructuredOutputCallResult:
    """Minimal ``StructuredOutputCallResult`` for monkeypatched ``structured_output_call``."""
    return StructuredOutputCallResult(
        json=json_payload,
        prep_ms=1.0,
        model_ms=2.0,
        serialize_ms=0.1,
        model_request_count=1,
    )


@pytest.mark.parametrize("explicit", ["0", "false", "off", None])
def test_stub_transport_toggle_respects_environment(
    monkeypatch: pytest.MonkeyPatch,
    explicit: str | None,
) -> None:
    from sevn.agent.triager import run as triager_run

    monkeypatch.delenv("SEVN_TRIAGER_STUB", raising=False)
    if explicit is not None:
        monkeypatch.setenv("SEVN_TRIAGER_STUB", explicit)
    assert triager_run._use_stub_transport() is False


def test_stub_transport_on_when_explicitly_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.agent.triager import run as triager_run

    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    assert triager_run._use_stub_transport() is True


def test_registry_block_sorted_by_sort_name_then_id() -> None:
    snapshot = RegistrySnapshot(
        registry_version=1,
        tools=[
            RegistryIndexEntry(sort_name="beta", identifier="z", display_line="tool z"),
            RegistryIndexEntry(sort_name="alfa", identifier="a", display_line="tool a-first"),
            RegistryIndexEntry(sort_name="alfa", identifier="m", display_line="tool a-second"),
        ],
        skills=[
            RegistryIndexEntry(sort_name="skillb", identifier="sb", display_line="skill b"),
        ],
        mcp_servers=[
            RegistryIndexEntry(sort_name="mcpA", identifier="m1", display_line="mcp 1"),
        ],
    )
    ctx = TriagePromptContext(current_message="hello")
    _static, registry, _personality, _suffix = build_triager_prompt_segments(
        registry_snapshot=snapshot,
        triage_context=ctx,
    )
    ai = registry.index("tool a-first")
    aii = registry.index("tool a-second")
    b_idx = registry.index("tool z")
    assert ai < aii < b_idx
    skill_b = registry.index("skill b")
    assert b_idx < skill_b


def test_group_triage_block_appended_when_flag_set() -> None:
    snapshot = RegistrySnapshot()
    ctx = TriagePromptContext(current_message="msg", inject_group_triage_block=True)
    *_segments, suf = build_triager_prompt_segments(
        registry_snapshot=snapshot,
        triage_context=ctx,
    )
    assert GROUP_TRIAGE_INSTRUCTION_V1 in suf
    assert "[current_message]" in suf


def test_extract_json_strips_fence() -> None:
    blob = '```json\n{"intent":"NEW_REQUEST"}\n```'
    out = extract_json_payload(blob)
    assert json.loads(out)["intent"] == "NEW_REQUEST"


def test_finalize_tier_b_tail_truncation_default() -> None:
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "permissions": {"scope_narrowing": {"enabled": False}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    tools = [
        RegistryIndexEntry(sort_name=str(i), identifier=f"t{i}", display_line=str(i))
        for i in range(15)
    ]
    skills = [
        RegistryIndexEntry(sort_name=str(i), identifier=f"s{i}", display_line=str(i))
        for i in range(10)
    ]
    reg = RegistrySnapshot(registry_version=0, tools=tools, skills=skills)
    tri_cfg = TriagerWorkspaceConfig(tier_b_tool_cap=10, tier_b_skill_cap=7)
    parsed = TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="ok",
        tools=[f"t{i}" for i in range(15)],
        skills=[f"s{i}" for i in range(10)],
        mcp_servers_required=[],
        confidence=1.0,
        requires_vision=False,
        requires_document=False,
        permission_scope_narrowing="admin",
        disregard=False,
    )
    out = finalize_triage_result(
        parsed=parsed,
        registry_snapshot=reg,
        session=SessionView(session_id="1"),
        workspace=ws,
        triager_cfg=tri_cfg,
    )
    assert len(out.tools) == 10
    assert out.tools[0] == "t0"
    assert len(out.skills) == 7
    assert out.permission_scope_narrowing is None


def test_finalize_default_cap_truncates_oversized_selection_to_five() -> None:
    """W6: the default tool cap (5) trims an over-long anchor list (e.g. the 8 tools

    the Triager dumped for a simple repo-root question) down to the minimal cap.
    """
    over_selected = [
        "read",
        "glob",
        "list_dir",
        "search_in_file",
        "find_file",
        "get_module_docstring",
        "get_symbol_docstring",
        "list_symbols",
    ]
    tools = [
        RegistryIndexEntry(sort_name=name, identifier=name, display_line=name)
        for name in over_selected
    ]
    reg = RegistrySnapshot(registry_version=0, tools=tools, skills=[])
    ws = parse_workspace_config(
        {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
    )
    tri_cfg = TriagerWorkspaceConfig()  # default tier_b_tool_cap == 5
    assert tri_cfg.tier_b_tool_cap == 5
    parsed = TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="ok",
        tools=over_selected,
        skills=[],
        mcp_servers_required=[],
        confidence=1.0,
        requires_vision=False,
        requires_document=False,
        disregard=False,
    )
    out = finalize_triage_result(
        parsed=parsed,
        registry_snapshot=reg,
        session=SessionView(session_id="1"),
        workspace=ws,
        triager_cfg=tri_cfg,
    )
    assert len(out.tools) == 5  # truncated from 8, not the old default of 10
    assert out.tools == over_selected[:5]


def test_static_prefix_carries_minimal_toolset_guidance() -> None:
    """W6: the Triager prompt instructs picking the smallest sufficient tool set."""
    snapshot = RegistrySnapshot()
    ctx = TriagePromptContext(current_message="what folders are in root")
    static, *_rest = build_triager_prompt_segments(
        registry_snapshot=snapshot,
        triage_context=ctx,
    )
    assert "MINIMAL_TOOLSET_RULE" in static
    assert "SMALLEST sufficient set" in static
    assert "1-3 anchor tools" in static
    assert "load_tool" in static
    assert "widened-toolkit retry" in static


def test_finalize_strips_unknown_tool_default_policy() -> None:
    ws = parse_workspace_config(
        {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
    )
    reg = RegistrySnapshot(
        tools=[
            RegistryIndexEntry(sort_name="a", identifier="known", display_line="x"),
        ],
    )
    tri_cfg = TriagerWorkspaceConfig()
    parsed = TriageResult.model_validate_json(
        json.dumps(
            {
                "intent": "NEW_REQUEST",
                "complexity": "B",
                "first_message": "x",
                "tools": ["known", "phantom"],
                "skills": [],
                "mcp_servers_required": [],
                "confidence": 0.5,
                "requires_vision": False,
                "requires_document": False,
            },
        ),
    )
    out = finalize_triage_result(
        parsed=parsed,
        registry_snapshot=reg,
        session=SessionView(session_id="1"),
        workspace=ws,
        triager_cfg=tri_cfg,
    )
    assert out.tools == ["known"]


def test_finalize_disregard_coerces_complexity_to_a() -> None:
    ws = parse_workspace_config(
        {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
    )
    reg = RegistrySnapshot()
    tri_cfg = TriagerWorkspaceConfig(disregard_non_a_complexity="coerce")
    parsed = TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="",
        tools=[],
        skills=[],
        mcp_servers_required=[],
        confidence=0.2,
        requires_vision=False,
        requires_document=False,
        disregard=True,
    )
    out = finalize_triage_result(
        parsed=parsed,
        registry_snapshot=reg,
        session=SessionView(session_id="1"),
        workspace=ws,
        triager_cfg=tri_cfg,
    )
    assert out.complexity == ComplexityTier.A
    assert out.disregard is True


@pytest.mark.asyncio
async def test_triage_turn_does_not_insert_triage_decisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Triager callable does not write ``triage_decisions`` (`specs/13` §10.2)."""
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    db_path = tmp_path / "w" / "sevn.db"
    conn = connect_sqlite(db_path)
    apply_migrations(conn)
    assert int(conn.execute("SELECT COUNT(*) FROM triage_decisions").fetchone()[0]) == 0
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "triager": {"group_scope": "all", "relax_greeting_lists": False},
            "providers": {"tier_default": {"triager": "stub/model"}},
            "permissions": {"scope_narrowing": {"enabled": False}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    await triage_turn(
        workspace=ws,
        session=SessionView(session_id="s1", chat_member_count=1),
        incoming=ApprovedUserTurn(text="hi"),
        registry_snapshot=RegistrySnapshot(),
        triage_context=TriagePromptContext(current_message="hi"),
    )
    assert int(conn.execute("SELECT COUNT(*) FROM triage_decisions").fetchone()[0]) == 0
    conn.close()


@pytest.mark.asyncio
async def test_triage_turn_stub_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "triager": {"group_scope": "all", "relax_greeting_lists": False},
            "providers": {"tier_default": {"triager": "stub/model"}},
            "permissions": {"scope_narrowing": {"enabled": False}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    registry = RegistrySnapshot()
    sess = SessionView(session_id="s1", chat_member_count=3)
    turn = ApprovedUserTurn(text="hi", member_count=3)
    ctx = TriagePromptContext(current_message="hi there")
    out = await triage_turn(
        workspace=ws,
        session=sess,
        incoming=turn,
        registry_snapshot=registry,
        triage_context=ctx,
    )
    assert out.complexity == ComplexityTier.B
    assert out.first_message


@pytest.mark.asyncio
async def test_triage_turn_fast_greeting_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "triager": {"fast_greeting_path": True},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        }
    )
    out = await triage_turn(
        workspace=ws,
        session=SessionView(session_id="s1"),
        incoming=ApprovedUserTurn(text="hello"),
        registry_snapshot=RegistrySnapshot(),
        triage_context=TriagePromptContext(current_message="hello", turn_id="g1"),
    )
    assert out.complexity == ComplexityTier.A
    assert out.intent == Intent.GREETING
    assert out.first_message.strip()
    assert out.first_message.lower() != "hello"


@pytest.mark.asyncio
@pytest.mark.parametrize("greeting", ["helloo", "hi", "thanks", "ok", "bye"])
async def test_fast_greeting_short_circuits_before_llm(
    monkeypatch: pytest.MonkeyPatch,
    greeting: str,
) -> None:
    """Pure greetings/acks resolve via the canned tier-A path, never the triage LLM."""
    from sevn.agent.triager import run as triager_run

    monkeypatch.setenv("SEVN_TRIAGER_STUB", "0")
    monkeypatch.delenv("SEVN_TRIAGER_STUB_JSON", raising=False)

    async def boom(**_: object) -> str:
        msg = "triage LLM must not be called for a pure greeting/ack"
        raise AssertionError(msg)

    monkeypatch.setattr(triager_run, "structured_output_call", boom)
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "triager": {"fast_greeting_path": True},
            "providers": {
                "tier_default": {"triager": "anthropic:claude-3-5-haiku"},
                "models": {"anthropic:claude-3-5-haiku": {"transport": "anthropic"}},
            },
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    out = await triage_turn(
        workspace=ws,
        session=SessionView(session_id="s-fast"),
        incoming=ApprovedUserTurn(text=greeting),
        registry_snapshot=RegistrySnapshot(),
        triage_context=TriagePromptContext(current_message=greeting, turn_id="g"),
    )
    assert out.complexity == ComplexityTier.A
    assert out.intent == Intent.GREETING
    assert out.first_message.strip()


@pytest.mark.asyncio
async def test_continuation_fast_path_replays_prior_without_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Obvious continuations replay prior routing without the triage LLM."""
    from sevn.agent.triager import run as triager_run

    monkeypatch.setenv("SEVN_TRIAGER_STUB", "0")
    calls = {"n": 0}

    async def fake_call(**_: object) -> StructuredOutputCallResult:
        calls["n"] += 1
        return _stub_structured_output("{}")

    monkeypatch.setattr(triager_run, "structured_output_call", fake_call)
    events: list[dict[str, object]] = []

    def capture(event: str, **fields: object) -> None:
        if event == "triager.output":
            events.append({"event": event, **fields})

    monkeypatch.setattr(triager_run, "debug_event", capture)
    prior = TriageResult.model_construct(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="Working.",
        tools=["read"],
        skills=["pdf"],
        mcp_servers_required=[],
        confidence=0.85,
        requires_vision=False,
        requires_document=False,
        disregard=False,
    )
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "triager": {"fast_greeting_path": True, "fast_continuation_path": True},
            "providers": {"tier_default": {"triager": "minimax/MiniMax-M3"}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    registry = RegistrySnapshot(
        tools=[
            RegistryIndexEntry(
                sort_name="read", identifier="read", display_line="read - file read"
            ),
        ],
        skills=[
            RegistryIndexEntry(sort_name="pdf", identifier="pdf", display_line="pdf - pdf skill"),
        ],
    )
    out = await triage_turn(
        workspace=ws,
        session=SessionView(session_id="s-cont"),
        incoming=ApprovedUserTurn(text="go ahead"),
        registry_snapshot=registry,
        triage_context=TriagePromptContext(
            current_message="go ahead",
            turn_id="cont-fast",
            prior_triage_result=prior,
        ),
    )
    assert calls["n"] == 0
    assert out.intent == Intent.FOLLOWUP
    assert out.complexity == ComplexityTier.B
    assert out.tools == ["read"]
    assert out.skills == ["pdf"]
    assert out.replay_provider_history is True
    assert events[-1]["fast_path"] is True


@pytest.mark.asyncio
async def test_continuation_without_prior_hits_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Continuations without prior routing still reach the triage LLM."""
    from sevn.agent.triager import run as triager_run

    monkeypatch.setenv("SEVN_TRIAGER_STUB", "0")
    calls = {"n": 0}

    async def fake_call(**_: object) -> StructuredOutputCallResult:
        calls["n"] += 1
        return _stub_structured_output(
            json.dumps(
                {
                    "intent": "FOLLOWUP",
                    "complexity": "B",
                    "first_message": "On it.",
                    "tools": [],
                    "skills": [],
                    "mcp_servers_required": [],
                    "confidence": 0.7,
                    "requires_vision": False,
                    "requires_document": False,
                    "disregard": False,
                },
            ),
        )

    monkeypatch.setattr(triager_run, "structured_output_call", fake_call)
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "triager": {"fast_greeting_path": True, "fast_continuation_path": True},
            "providers": {
                "tier_default": {"triager": "anthropic:claude-3-5-haiku"},
                "models": {"anthropic:claude-3-5-haiku": {"transport": "anthropic"}},
            },
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    out = await triage_turn(
        workspace=ws,
        session=SessionView(session_id="s-followup"),
        incoming=ApprovedUserTurn(text="so?"),
        registry_snapshot=RegistrySnapshot(),
        triage_context=TriagePromptContext(current_message="so?", turn_id="f"),
    )
    assert calls["n"] == 1
    assert out.complexity == ComplexityTier.B


@pytest.mark.asyncio
async def test_substantive_followup_hits_llm_even_with_prior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multi-word substantive follow-ups are not continuation fast-pathed."""
    from sevn.agent.triager import run as triager_run

    monkeypatch.setenv("SEVN_TRIAGER_STUB", "0")
    calls = {"n": 0}

    async def fake_call(**_: object) -> StructuredOutputCallResult:
        calls["n"] += 1
        return _stub_structured_output(
            json.dumps(
                {
                    "intent": "FOLLOWUP",
                    "complexity": "B",
                    "first_message": "On it.",
                    "tools": [],
                    "skills": [],
                    "mcp_servers_required": [],
                    "confidence": 0.7,
                    "requires_vision": False,
                    "requires_document": False,
                    "disregard": False,
                },
            ),
        )

    monkeypatch.setattr(triager_run, "structured_output_call", fake_call)
    prior = TriageResult.model_construct(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="Working.",
        tools=["read"],
        skills=[],
        mcp_servers_required=[],
        confidence=0.85,
        requires_vision=False,
        requires_document=False,
        disregard=False,
    )
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "triager": {"fast_continuation_path": True},
            "providers": {"tier_default": {"triager": "stub/model"}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    await triage_turn(
        workspace=ws,
        session=SessionView(session_id="s-sub"),
        incoming=ApprovedUserTurn(text="ok now I see it"),
        registry_snapshot=RegistrySnapshot(),
        triage_context=TriagePromptContext(
            current_message="ok now I see it",
            turn_id="sub",
            prior_triage_result=prior,
        ),
    )
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_cheap_triager_model_used_for_continuation_llm_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configured cheap_model_id routes continuation LLM triage off the main slot."""
    from sevn.agent.triager import run as triager_run

    monkeypatch.setenv("SEVN_TRIAGER_STUB", "0")
    seen: dict[str, str] = {}

    async def fake_call(*, model_id: str, **_: object) -> StructuredOutputCallResult:
        seen["model_id"] = model_id
        return _stub_structured_output(
            json.dumps(
                {
                    "intent": "FOLLOWUP",
                    "complexity": "B",
                    "first_message": "On it.",
                    "tools": [],
                    "skills": [],
                    "mcp_servers_required": [],
                    "confidence": 0.7,
                    "requires_vision": False,
                    "requires_document": False,
                    "disregard": False,
                },
            ),
        )

    monkeypatch.setattr(triager_run, "structured_output_call", fake_call)
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "triager": {
                "fast_continuation_path": True,
                "cheap_model_id": "anthropic:claude-3-5-haiku",
            },
            "providers": {
                "tier_default": {"triager": "minimax/MiniMax-M3"},
                "models": {
                    "minimax/MiniMax-M3": {"transport": "anthropic"},
                    "anthropic:claude-3-5-haiku": {"transport": "anthropic"},
                },
            },
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    await triage_turn(
        workspace=ws,
        session=SessionView(session_id="s-cheap"),
        incoming=ApprovedUserTurn(text="try again"),
        registry_snapshot=RegistrySnapshot(),
        triage_context=TriagePromptContext(current_message="try again", turn_id="cheap"),
    )
    assert seen["model_id"] == "anthropic:claude-3-5-haiku"


@pytest.mark.asyncio
async def test_triager_output_emits_latency_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``triager.output`` carries ``elapsed_ms`` + ``fast_path`` keyed by model_id."""
    from sevn.agent.tracing.sink import TraceSink
    from sevn.agent.triager import run as triager_run

    class _RecordingTrace(TraceSink):
        def __init__(self) -> None:
            self.events: list[object] = []

        async def emit(self, event: object) -> None:
            self.events.append(event)

        async def flush(self) -> None:
            return None

        async def close(self) -> None:
            return None

    monkeypatch.setenv("SEVN_TRIAGER_STUB", "0")
    events: list[dict[str, object]] = []
    trace = _RecordingTrace()

    def capture(event: str, **fields: object) -> None:
        if event == "triager.output":
            events.append({"event": event, **fields})

    monkeypatch.setattr(triager_run, "debug_event", capture)
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "triager": {"fast_greeting_path": True},
            "providers": {"tier_default": {"triager": "stub/model"}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    await triage_turn(
        workspace=ws,
        session=SessionView(session_id="s-lat"),
        incoming=ApprovedUserTurn(text="helloo"),
        registry_snapshot=RegistrySnapshot(),
        triage_context=TriagePromptContext(current_message="helloo", turn_id="lat"),
        trace=trace,
    )
    assert events, "triager.output event not emitted"
    out_event = events[-1]
    assert "elapsed_ms" in out_event
    assert isinstance(out_event["elapsed_ms"], float)
    assert out_event["fast_path"] is True
    assert "model_id" in out_event
    # D5: fast greeting bypasses ``structured_output_call`` — no segment attrs on span.
    complete = next(e for e in trace.events if getattr(e, "kind", None) == "triage.complete")
    assert "prep_ms" not in complete.attrs
    assert "model_ms" not in complete.attrs
    assert "serialize_ms" not in complete.attrs


@pytest.mark.asyncio
async def test_triage_turn_group_suffix_auto_injected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§4.1 block when ``group_scope==all`` and ``chat_member_count>1``."""
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "triager": {"group_scope": "all"},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    sess = SessionView(session_id="s", chat_member_count=2)
    captured: list[TriagePromptContext] = []

    from sevn.agent.triager import run as triager_run

    _orig_build = triager_run.build_triager_prompt_segments

    def spy(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        captured.append(kwargs["triage_context"])
        return _orig_build(*args, **kwargs)

    monkeypatch.setattr(triager_run, "build_triager_prompt_segments", spy)
    ctx = TriagePromptContext(current_message="x")
    await triage_turn(
        workspace=ws,
        session=sess,
        incoming=ApprovedUserTurn(text="x"),
        registry_snapshot=RegistrySnapshot(),
        triage_context=ctx,
    )
    merged = captured[0]
    assert merged.inject_group_triage_block is True


@pytest.mark.asyncio
async def test_triage_turn_fallback_on_repeat_schema_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv("SEVN_TRIAGER_STUB_JSON", '{"broken":true}')
    ws = parse_workspace_config(
        {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
    )
    out = await triage_turn(
        workspace=ws,
        session=SessionView(session_id="s"),
        incoming=ApprovedUserTurn(text="x"),
        registry_snapshot=RegistrySnapshot(),
        triage_context=TriagePromptContext(current_message="z"),
    )
    assert out.complexity == ComplexityTier.B
    assert out.first_message.strip()
    assert out.confidence == 0.55


@pytest.mark.asyncio
async def test_triage_turn_fallback_on_agent_run_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pydantic-AI ``UnexpectedModelBehavior`` (e.g. MiniMax XML escape) falls back cleanly."""
    from pydantic_ai.exceptions import UnexpectedModelBehavior

    from sevn.agent.triager import run as triager_run

    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")

    call_count = {"n": 0}

    async def boom() -> str:
        call_count["n"] += 1
        raise UnexpectedModelBehavior("Exceeded maximum output retries (1)")

    # Replace the inner ``fetch_raw`` closure indirectly by stubbing the
    # public structured-output entry point; both paths share the same wrapper.
    async def boom_stub() -> str:
        return await boom()

    monkeypatch.setattr(triager_run, "_stub_response_json", lambda: boom_stub() and "{}")  # type: ignore[misc]

    # Easier path: monkeypatch ``structured_output_call`` so the test runs in
    # the live branch (stub is off) but the LLM call raises.
    async def raising_call(**_: object) -> str:
        raise UnexpectedModelBehavior("Exceeded maximum output retries (1)")

    monkeypatch.setenv("SEVN_TRIAGER_STUB", "0")
    monkeypatch.delenv("SEVN_TRIAGER_STUB_JSON", raising=False)
    monkeypatch.setattr(triager_run, "structured_output_call", raising_call)

    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "providers": {
                "tier_default": {"triager": "anthropic:claude-3-5-haiku"},
                "models": {"anthropic:claude-3-5-haiku": {"transport": "anthropic"}},
            },
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    out = await triage_turn(
        workspace=ws,
        session=SessionView(session_id="s-agent-err"),
        incoming=ApprovedUserTurn(text="What is the round budget?"),
        registry_snapshot=RegistrySnapshot(),
        triage_context=TriagePromptContext(current_message="What is the round budget?"),
    )
    assert out.complexity == ComplexityTier.B
    assert out.first_message.strip()
    assert out.confidence == 0.55


@pytest.mark.asyncio
async def test_triage_turn_live_mocked_chat_completions(monkeypatch: pytest.MonkeyPatch) -> None:
    """``SEVN_TRIAGER_STUB=0`` completes via pydantic-ai + mocked proxy transport."""
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "0")
    monkeypatch.setenv("SEVN_PROXY_URL", "http://triager-mock.test")
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
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "providers": {
                "tier_default": {"triager": "openai:gpt-4o-mini"},
                "models": {"openai:gpt-4o-mini": {"transport": "chat_completions"}},
            },
            "permissions": {"scope_narrowing": {"enabled": False}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    out = await triage_turn(
        workspace=ws,
        session=SessionView(session_id="s-live"),
        incoming=ApprovedUserTurn(text="route me"),
        registry_snapshot=RegistrySnapshot(),
        triage_context=TriagePromptContext(current_message="route me"),
    )
    assert out.complexity == ComplexityTier.B
    assert out.first_message == "On it."
    assert out.confidence == 0.88


def test_fixture_custom_stub_reads_from_disk(monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.agent.triager import run as triager_run

    path = _FIXTURE_TRIAGER / "custom_stub_result.json"
    monkeypatch.setenv("SEVN_TRIAGER_STUB_FIXTURE_PATH", str(path))
    blob = triager_run._stub_response_json()
    parsed = json.loads(blob)
    assert parsed["intent"] == "GREETING"


_LOAD_SKILL_XML = (
    '<minimax:tool_call><invoke name="load_skill">'
    '<parameter name="name">serp</parameter></invoke></minimax:tool_call>'
)


def _anthropic_triager_workspace() -> object:
    return parse_workspace_config(
        {
            "schema_version": 1,
            "providers": {
                "tier_default": {"triager": "minimax/MiniMax-M3"},
                "models": {"minimax/MiniMax-M3": {"transport": "anthropic"}},
            },
            "permissions": {"scope_narrowing": {"enabled": False}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )


@pytest.mark.asyncio
async def test_triage_turn_xml_load_skill_degrades_to_synthetic_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MiniMax XML ``load_skill`` inside the triager must not 400 or crash the turn."""
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "0")
    monkeypatch.setenv("SEVN_PROXY_URL", "http://triager-xml.test")
    calls = {"n": 0}

    async def fake_post(**kwargs: object) -> dict[str, object]:
        calls["n"] += 1
        return {
            "id": "msg-xml",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": _LOAD_SKILL_XML}],
            "model": "minimax/MiniMax-M3",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    monkeypatch.setattr(
        "sevn.agent.providers.transport.transport_http.post_llm_json",
        fake_post,
    )
    out = await triage_turn(
        workspace=_anthropic_triager_workspace(),
        session=SessionView(session_id="s-xml"),
        incoming=ApprovedUserTurn(text="route this"),
        registry_snapshot=RegistrySnapshot(),
        triage_context=TriagePromptContext(current_message="route this"),
    )
    assert out.complexity == ComplexityTier.B
    assert out.first_message.strip()
    assert out.confidence == 0.55
    assert calls["n"] >= 1


@pytest.mark.asyncio
async def test_triage_turn_fallback_on_proxy_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proxy HTTP 400 degrades to synthetic fallback — never ``agent_turn_unhandled_error``."""
    import httpx

    from sevn.agent.providers.transport_http import TransportBadRequest

    monkeypatch.setenv("SEVN_TRIAGER_STUB", "0")
    monkeypatch.setenv("SEVN_PROXY_URL", "http://triager-400.test")

    async def always_400(**kwargs: object) -> dict[str, object]:
        request = httpx.Request("POST", "http://triager-400.test/llm/anthropic/messages")
        response = httpx.Response(400, request=request, json={"error": "bad request"})
        raise TransportBadRequest("LLM proxy returned 400", request=request, response=response)

    monkeypatch.setattr(
        "sevn.agent.providers.transport.transport_http.post_llm_json",
        always_400,
    )
    out = await triage_turn(
        workspace=_anthropic_triager_workspace(),
        session=SessionView(session_id="s-400"),
        incoming=ApprovedUserTurn(text="will the proxy reject this?"),
        registry_snapshot=RegistrySnapshot(),
        triage_context=TriagePromptContext(current_message="will the proxy reject this?"),
    )
    assert out.complexity == ComplexityTier.B
    assert out.first_message.strip()
    assert out.confidence == 0.55


def test_tier_a_shape_detects_structured_first_message() -> None:
    assert not _tier_a_first_message_shape_overstepped("Hi! What's on your mind?")
    assert _tier_a_first_message_shape_overstepped("- one\n- two")
    assert _tier_a_first_message_shape_overstepped("See https://example.com for details")
    assert _tier_a_first_message_shape_overstepped("```python\nprint('x')\n```")
    long_line = "x" * 101
    assert _tier_a_first_message_shape_overstepped(long_line)


def test_finalize_substantive_tier_a_force_routed_to_b() -> None:
    """W4B: NEW_REQUEST + tier A on a substantive ask escalates to tier B."""
    ws = parse_workspace_config(
        {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
    )
    reg = RegistrySnapshot()
    tri_cfg = TriagerWorkspaceConfig()
    parsed = TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.A,
        first_message="Cron lives in src/sevn/tools/cron/scheduler.py with APScheduler.",
        tools=[],
        skills=[],
        mcp_servers_required=[],
        confidence=0.95,
        requires_vision=False,
        requires_document=False,
    )
    trace_attrs: dict[str, object] = {}
    out = finalize_triage_result(
        parsed=parsed,
        registry_snapshot=reg,
        session=SessionView(session_id="1"),
        workspace=ws,
        triager_cfg=tri_cfg,
        triage_context=TriagePromptContext(
            current_message="how does cron scheduling work in general?",
            turn_id="substantive-a",
        ),
        trace_attrs=trace_attrs,
    )
    assert out.complexity == ComplexityTier.B
    assert out.intent == Intent.NEW_REQUEST
    assert trace_attrs.get("triager_overstepped") is True
    assert "cron" not in out.first_message.lower()


def test_finalize_long_tier_a_first_message_escalated() -> None:
    """W4B: verbose structured first_message on tier A escalates to tier B."""
    ws = parse_workspace_config(
        {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
    )
    reg = RegistrySnapshot()
    tri_cfg = TriagerWorkspaceConfig()
    parsed = TriageResult(
        intent=Intent.GREETING,
        complexity=ComplexityTier.A,
        first_message="Here are the folders:\n- src\n- tests\n- infra",
        tools=[],
        skills=[],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
    )
    out = finalize_triage_result(
        parsed=parsed,
        registry_snapshot=reg,
        session=SessionView(session_id="1"),
        workspace=ws,
        triager_cfg=tri_cfg,
        triage_context=TriagePromptContext(current_message="hi", turn_id="long-a"),
    )
    assert out.complexity == ComplexityTier.B
    assert out.first_message.strip()
    assert "folders" not in out.first_message.lower()


def test_finalize_strict_greeting_stays_tier_a() -> None:
    """W4B: valid greeting + short first_message remains tier A."""
    ws = parse_workspace_config(
        {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
    )
    reg = RegistrySnapshot()
    tri_cfg = TriagerWorkspaceConfig()
    parsed = TriageResult(
        intent=Intent.GREETING,
        complexity=ComplexityTier.A,
        first_message="Hey — what can I help with?",
        tools=[],
        skills=[],
        mcp_servers_required=[],
        confidence=1.0,
        requires_vision=False,
        requires_document=False,
    )
    trace_attrs: dict[str, object] = {}
    out = finalize_triage_result(
        parsed=parsed,
        registry_snapshot=reg,
        session=SessionView(session_id="1"),
        workspace=ws,
        triager_cfg=tri_cfg,
        triage_context=TriagePromptContext(
            current_message="hello",
            turn_id="greet-a",
        ),
        trace_attrs=trace_attrs,
    )
    assert out.complexity == ComplexityTier.A
    assert out.intent == Intent.GREETING
    assert "triager_overstepped" not in trace_attrs


@pytest.mark.asyncio
async def test_triage_turn_stub_substantive_tier_a_emits_overstepped_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W4B: stub model tier-A overstep is force-routed and traced."""
    from sevn.agent.tracing.sink import TraceEvent, TraceSink

    class _RecordingTrace(TraceSink):
        def __init__(self) -> None:
            self.events: list[TraceEvent] = []

        async def emit(self, event: TraceEvent) -> None:
            self.events.append(event)

        async def flush(self) -> None:
            return None

        async def close(self) -> None:
            return None

    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv(
        "SEVN_TRIAGER_STUB_JSON",
        json.dumps(
            {
                "intent": "NEW_REQUEST",
                "complexity": "A",
                "first_message": "Osvaldo Pugliese was born in 1905 in Buenos Aires.",
                "tools": [],
                "skills": [],
                "mcp_servers_required": [],
                "confidence": 0.99,
                "requires_vision": False,
                "requires_document": False,
                "disregard": False,
            },
        ),
    )
    trace = _RecordingTrace()
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "triager": {"fast_greeting_path": False},
            "providers": {"tier_default": {"triager": "stub/model"}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    out = await triage_turn(
        workspace=ws,
        session=SessionView(session_id="s-over"),
        incoming=ApprovedUserTurn(text="who was Osvaldo Pugliese?"),
        registry_snapshot=RegistrySnapshot(),
        triage_context=TriagePromptContext(
            current_message="who was Osvaldo Pugliese?",
            turn_id="over-1",
        ),
        trace=trace,
    )
    assert out.complexity == ComplexityTier.B
    complete = next(e for e in trace.events if e.kind == "triage.complete")
    assert complete.attrs.get("triager_overstepped") is True
    assert "1905" not in out.first_message


def test_apply_tier_a_scope_guard_direct() -> None:
    parsed = TriageResult(
        intent=Intent.UNKNOWN,
        complexity=ComplexityTier.A,
        first_message="ok",
        tools=[],
        skills=[],
        mcp_servers_required=[],
        confidence=0.5,
        requires_vision=False,
        requires_document=False,
    )
    out, over = _apply_tier_a_scope_guard(
        parsed,
        current_message="what is the weather?",
        turn_id="direct",
    )
    assert over is True
    assert out.complexity == ComplexityTier.B
