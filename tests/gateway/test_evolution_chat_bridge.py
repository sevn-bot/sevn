"""Evolution chat bridge tests (`plan/full-loop-evolution-wave-plan.md` FL-4B.5)."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sevn.agent.executors.b_types import EscalationRequest
from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
from sevn.agent.triager.routing_policy import (
    _merge_evolution_tools,
    is_evolution_fix_intent_message,
)
from sevn.config.workspace_config import WorkspaceConfig
from sevn.evolution.issues import EvolutionIssue, create_issue
from sevn.gateway.agent_turn import _synthetic_escalation_triage
from sevn.gateway.channel_router import IncomingMessage
from sevn.gateway.commands.evolution_chat_bridge import (
    EvolutionChatBridge,
    _is_github_number,
    _parse_evolution_phrase,
    _repo_slug,
)
from sevn.workspace.layout import WorkspaceLayout

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _layout(tmp_path: Path) -> tuple[WorkspaceLayout, WorkspaceConfig]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    return WorkspaceLayout.from_config(sevn_json, cfg), cfg


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _bridge(
    layout: WorkspaceLayout,
    workspace: WorkspaceConfig,
    *,
    is_owner: bool = True,
) -> EvolutionChatBridge:
    router = MagicMock()
    router._resolve_owner_flag.return_value = is_owner
    router._adapters = {}
    return EvolutionChatBridge(
        workspace=workspace,
        layout=layout,
        router=router,
        conn=_conn(),
    )


# ---------------------------------------------------------------------------
# FL-4B.3 — phrase → intent detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "fix issue #42",
        "fix issue 42",
        "fix GitHub issue #7",
        "fix evolution abc-123",
        "implement feature xyz-1",
        "implement issue abc-2",
        "work on issue abc-3",
        "work on bug #10",
        "implement #99",
    ],
)
def test_is_evolution_fix_intent_positive(text: str) -> None:
    """Explicit issue-fix phrases are detected."""
    assert is_evolution_fix_intent_message(text), f"Expected True for: {text!r}"


@pytest.mark.parametrize(
    "text",
    [
        "fix the general bug in my code",
        "fix the login bug",
        "hello",
        "",
        "implement something",
        "please help me",
    ],
)
def test_is_evolution_fix_intent_negative(text: str) -> None:
    """Generic phrases and greetings are NOT matched."""
    assert not is_evolution_fix_intent_message(text), f"Expected False for: {text!r}"


# ---------------------------------------------------------------------------
# FL-4B.1 — phrase → identifier extraction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("fix issue #42", "42"),
        ("fix issue 42", "42"),
        ("fix GitHub issue #7", "7"),
        ("fix evolution abc-123", "abc-123"),
        ("implement feature xyz-1", "xyz-1"),
        ("implement issue abc-2", "abc-2"),
        ("work on issue abc-3", "abc-3"),
        ("implement #99", "99"),
    ],
)
def test_parse_evolution_phrase(text: str, expected: str) -> None:
    """Identifier extraction matches expected values."""
    assert _parse_evolution_phrase(text) == expected


def test_parse_evolution_phrase_no_match() -> None:
    """Non-matching text returns None."""
    assert _parse_evolution_phrase("hello") is None


def test_is_github_number_true() -> None:
    assert _is_github_number("42") is True
    assert _is_github_number("99") is True


def test_is_github_number_false() -> None:
    assert _is_github_number("abc-1") is False
    assert _is_github_number("xyz") is False


# ---------------------------------------------------------------------------
# FL-4B.3 — _merge_evolution_tools
# ---------------------------------------------------------------------------


def test_merge_evolution_tools_empty() -> None:
    """Starting from empty, all pinned bundle IDs are appended."""
    tools = _merge_evolution_tools([])
    expected = [
        "read",
        "edit",
        "write",
        "glob",
        "grep",
        "sandbox_exec",
        "terminal_run",
        "run_skill_script",
        "integration_call",
    ]
    assert tools == expected


def test_merge_evolution_tools_idempotent() -> None:
    """Running twice produces no duplicates."""
    once = _merge_evolution_tools([])
    twice = _merge_evolution_tools(once)
    assert once == twice


def test_merge_evolution_tools_appends_missing() -> None:
    """Only missing tools are appended; existing order is preserved."""
    tools = _merge_evolution_tools(["read", "edit"])
    assert tools[:2] == ["read", "edit"]
    assert "write" in tools
    assert "integration_call" in tools


# ---------------------------------------------------------------------------
# FL-4B.3 — apply_routing_policy wires evolution intent
# ---------------------------------------------------------------------------


def test_apply_routing_policy_coerces_evolution_intent_to_tier_b() -> None:
    """apply_routing_policy forces tier-B + evolution bundle for fix-issue phrases."""
    from sevn.agent.triager.routing_policy import apply_routing_policy

    result = TriageResult.model_construct(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.C,
        first_message="Working on it.",
        tools=[],
        skills=[],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
        disregard=False,
        permission_scope_narrowing=None,
    )
    out = apply_routing_policy(result, current_message="fix issue #42", turn_id="t1")
    assert out.complexity == ComplexityTier.B
    assert "read" in out.tools
    assert "integration_call" in out.tools


def test_apply_routing_policy_does_not_coerce_generic_phrase() -> None:
    """Generic 'fix the login bug' does NOT trigger evolution coercion."""
    from sevn.agent.triager.routing_policy import apply_routing_policy

    result = TriageResult.model_construct(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.C,
        first_message="On it.",
        tools=[],
        skills=[],
        mcp_servers_required=[],
        confidence=0.95,
        requires_vision=False,
        requires_document=False,
        disregard=False,
        permission_scope_narrowing=None,
    )
    out = apply_routing_policy(
        result,
        current_message="fix the login bug",
        turn_id="t2",
    )
    # complexity clamp may or may not fire (confidence 0.95 >= threshold) — the
    # point is evolution tools are NOT merged.
    assert "integration_call" not in out.tools


# ---------------------------------------------------------------------------
# FL-4B.4 — _synthetic_escalation_triage threads pinned tools
# ---------------------------------------------------------------------------


def test_synthetic_escalation_triage_empty_original_tools() -> None:
    """Without original_tools the tools list is empty (backward compat)."""
    esc = EscalationRequest(
        reason="r",
        target_tier="C",
        user_visible_message="m",
    )
    result = _synthetic_escalation_triage(esc)
    assert result.complexity == ComplexityTier.C
    assert result.tools == []


def test_synthetic_escalation_triage_threads_pinned_tools() -> None:
    """With original_tools the synthetic triage carries them through (FL-4B.4 / L5)."""
    pinned = ("read", "edit", "integration_call")
    esc = EscalationRequest(
        reason="evolution-escalation",
        target_tier="C",
        user_visible_message="",
        original_tools=pinned,
    )
    result = _synthetic_escalation_triage(esc)
    assert result.complexity == ComplexityTier.C
    assert set(result.tools) == set(pinned)


def test_synthetic_escalation_triage_tier_d() -> None:
    """Target tier D is respected."""
    esc = EscalationRequest(reason="r", target_tier="D", user_visible_message="")
    result = _synthetic_escalation_triage(esc)
    assert result.complexity == ComplexityTier.D


# ---------------------------------------------------------------------------
# FL-4B.1 — EvolutionChatBridge.matches_nl
# ---------------------------------------------------------------------------


def test_bridge_matches_nl_true(tmp_path: Path) -> None:
    lay, ws = _layout(tmp_path)
    bridge = _bridge(lay, ws)
    msg = IncomingMessage(channel="telegram", user_id="1", text="fix issue #42")
    assert bridge.matches_nl(msg) is True


def test_bridge_matches_nl_slash_returns_false(tmp_path: Path) -> None:
    """Slash commands are NOT matched by matches_nl (handled by EvolutionCommandHandler)."""
    lay, ws = _layout(tmp_path)
    bridge = _bridge(lay, ws)
    msg = IncomingMessage(channel="telegram", user_id="1", text="/fix abc-1")
    assert bridge.matches_nl(msg) is False


def test_bridge_matches_nl_generic_false(tmp_path: Path) -> None:
    lay, ws = _layout(tmp_path)
    bridge = _bridge(lay, ws)
    msg = IncomingMessage(channel="telegram", user_id="1", text="hello there")
    assert bridge.matches_nl(msg) is False


# ---------------------------------------------------------------------------
# FL-4B.1 — owner-check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bridge_handle_non_owner_returns_owner_only(tmp_path: Path) -> None:
    lay, ws = _layout(tmp_path)
    bridge = _bridge(lay, ws, is_owner=False)
    msg = IncomingMessage(channel="telegram", user_id="9", text="fix issue #42")
    reply = await bridge.handle(msg, session_id="s1")
    assert reply is not None
    assert "owner-only" in reply.lower()


# ---------------------------------------------------------------------------
# FL-4B.1 — local issue resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bridge_handle_local_issue(tmp_path: Path) -> None:
    """Bridge resolves a local issue by id and fires off run_pipeline."""
    lay, ws = _layout(tmp_path)
    issue = create_issue(lay, title="Test bug", kind="bug", body="")
    bridge = _bridge(lay, ws)
    msg = IncomingMessage(channel="telegram", user_id="1", text=f"fix evolution {issue.id}")

    with patch(
        "sevn.gateway.commands.evolution_chat_bridge.run_pipeline",
        new_callable=AsyncMock,
    ) as mock_run:
        mock_run.return_value = issue
        reply = await bridge.handle(msg, session_id="s1")
        # Allow the fire-and-forget task a tick to schedule.
        await asyncio.sleep(0)

    assert reply is not None
    assert issue.id in reply


# ---------------------------------------------------------------------------
# FL-4B.1 — unknown local id, not a number → not-found message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bridge_handle_unknown_id(tmp_path: Path) -> None:
    """Unknown non-numeric id → not-found message."""
    lay, ws = _layout(tmp_path)
    bridge = _bridge(lay, ws)
    msg = IncomingMessage(channel="telegram", user_id="1", text="fix evolution unknown-xyz")
    reply = await bridge.handle(msg, session_id="s1")
    assert reply is not None
    assert "not found" in reply.lower()


# ---------------------------------------------------------------------------
# FL-4B.1 — GitHub number import (number → import_github_issue path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bridge_handle_github_number_import(tmp_path: Path) -> None:
    """A bare GitHub number triggers import_github_issue when not found locally."""
    lay, ws = _layout(tmp_path)
    bridge = _bridge(lay, ws)
    msg = IncomingMessage(channel="telegram", user_id="1", text="fix issue #99")

    fake_issue = EvolutionIssue(
        id="evo-99",
        title="Imported",
        kind="bug",
        state="open",
        body="",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        source="github",
        github={"number": 99, "url": ""},
    )
    with (
        patch.object(bridge, "_import_github", new_callable=AsyncMock) as mock_import,
        patch(
            "sevn.gateway.commands.evolution_chat_bridge.run_pipeline",
            new_callable=AsyncMock,
        ) as mock_run,
    ):
        mock_import.return_value = fake_issue
        mock_run.return_value = fake_issue
        reply = await bridge.handle(msg, session_id="s1")
        await asyncio.sleep(0)
        mock_import.assert_called_once_with(99)

    assert reply is not None
    assert "evo-99" in reply


# ---------------------------------------------------------------------------
# FL-4B.2 — PlanGate gating: PipelineBlockedError is swallowed silently
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bridge_plan_gate_blocked_does_not_raise(tmp_path: Path) -> None:
    """run_pipeline raising PipelineBlockedError is swallowed; ack is still returned."""
    from sevn.evolution.pipeline_common import PipelineBlockedError

    lay, ws = _layout(tmp_path)
    issue = create_issue(lay, title="Blocked issue", kind="bug", body="")
    bridge = _bridge(lay, ws)
    msg = IncomingMessage(channel="telegram", user_id="1", text=f"fix evolution {issue.id}")

    with patch(
        "sevn.gateway.commands.evolution_chat_bridge.run_pipeline",
        new_callable=AsyncMock,
        side_effect=PipelineBlockedError("awaiting_approval"),
    ):
        reply = await bridge.handle(msg, session_id="s1")
        # Let the fire-and-forget task complete.
        await asyncio.gather(*asyncio.all_tasks() - {asyncio.current_task()})

    # The ack should have been returned before the task raised.
    assert reply is not None
    assert issue.id in reply


# ---------------------------------------------------------------------------
# Repo slug helper
# ---------------------------------------------------------------------------


def test_repo_slug_from_full_url() -> None:
    from sevn.config.workspace_config import MySevnWorkspaceConfig

    ws = WorkspaceConfig(
        schema_version=1,
        my_sevn=MySevnWorkspaceConfig(repo_url="https://github.com/owner/myrepo"),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    assert _repo_slug(ws) == "owner/myrepo"


def test_repo_slug_from_short_form() -> None:
    from sevn.config.workspace_config import MySevnWorkspaceConfig

    ws = WorkspaceConfig(
        schema_version=1,
        my_sevn=MySevnWorkspaceConfig(repo_url="owner/myrepo"),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    assert _repo_slug(ws) == "owner/myrepo"


def test_repo_slug_empty_when_unconfigured() -> None:
    ws = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    assert _repo_slug(ws) == ""
