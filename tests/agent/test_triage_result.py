"""Tests for `TriageResult` and triager ontology (`specs/10-schema-ontology.md` §9)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError
from scripts.export_triage_schema import build_schema, schema_path

from sevn.agent.harness.snapshots import ActiveRunSnapshotWrite
from sevn.agent.providers.budget import BudgetRegime as BudgetRegimeOrig
from sevn.agent.triager import (
    COMPLEXITY_TIERS,
    BudgetRegime,
    ComplexityTier,
    Intent,
    MessageKind,
    SessionVisibilityLiteral,
    TelegramFollowupAnchor,
    TriageResult,
    WebUIFollowupAnchor,
)
from sevn.config.defaults import (
    DEFAULT_TRIAGER_TIER_B_SKILL_CAP,
    DEFAULT_TRIAGER_TIER_B_TOOL_CAP,
)
from sevn.storage.migrate import apply_migrations

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "agent"


@pytest.mark.parametrize("intent", list(Intent))
@pytest.mark.parametrize("complexity", list(ComplexityTier))
def test_triage_result_intent_complexity_matrix(
    intent: Intent,
    complexity: ComplexityTier,
) -> None:
    if intent == Intent.GREETING:
        tools: list[str] = []
        skills: list[str] = []
    else:
        tools = ["demo_tool"]
        skills = ["demo_skill"]
    row = TriageResult(
        intent=intent,
        complexity=complexity,
        first_message="User-visible line.",
        tools=tools,
        skills=skills,
        mcp_servers_required=[],
        confidence=0.72,
        requires_vision=False,
        requires_document=False,
    )
    assert row.intent == intent
    assert row.complexity == complexity


def test_greeting_rejects_nonempty_tools() -> None:
    with pytest.raises(ValidationError, match="GREETING requires empty"):
        TriageResult(
            intent=Intent.GREETING,
            complexity=ComplexityTier.A,
            first_message="Hi!",
            tools=["any"],
            skills=[],
            mcp_servers_required=[],
            confidence=1.0,
            requires_vision=False,
            requires_document=False,
        )


def test_greeting_rejects_nonempty_skills() -> None:
    with pytest.raises(ValidationError, match="GREETING requires empty"):
        TriageResult(
            intent=Intent.GREETING,
            complexity=ComplexityTier.A,
            first_message="Hey there",
            tools=[],
            skills=["nope"],
            mcp_servers_required=[],
            confidence=1.0,
            requires_vision=False,
            requires_document=False,
        )


def test_triage_result_rejects_extra_keys() -> None:
    with pytest.raises(ValidationError):
        TriageResult.model_validate(
            {
                "intent": "NEW_REQUEST",
                "complexity": "C",
                "first_message": "Go",
                "tools": [],
                "skills": [],
                "mcp_servers_required": [],
                "confidence": 0.5,
                "requires_vision": False,
                "requires_document": False,
                "unexpected": True,
            },
        )


def test_first_message_empty_after_strip() -> None:
    with pytest.raises(ValidationError, match="first_message"):
        TriageResult(
            intent=Intent.UNKNOWN,
            complexity=ComplexityTier.A,
            first_message="   \n\t ",
            tools=[],
            skills=[],
            mcp_servers_required=[],
            confidence=0.0,
            requires_vision=False,
            requires_document=False,
        )


def test_unknown_with_disregard() -> None:
    row = TriageResult(
        intent=Intent.UNKNOWN,
        complexity=ComplexityTier.A,
        first_message="",
        tools=[],
        skills=[],
        mcp_servers_required=[],
        confidence=0.0,
        requires_vision=False,
        requires_document=False,
        disregard=True,
    )
    assert row.disregard is True
    assert row.first_message == ""


def test_greeting_allows_nonempty_lists_when_context_relaxes() -> None:
    row = TriageResult.model_validate(
        {
            "intent": "GREETING",
            "complexity": "A",
            "first_message": "Hi",
            "tools": ["t1"],
            "skills": [],
            "mcp_servers_required": [],
            "confidence": 1.0,
            "requires_vision": False,
            "requires_document": False,
        },
        context={"relax_greeting_lists": True},
    )
    assert row.tools == ["t1"]


def test_fixture_triage_result_min_roundtrip() -> None:
    path = _FIXTURE_DIR / "triage_result_min.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    row = TriageResult.model_validate(data)
    assert row.intent == Intent.NEW_REQUEST
    assert row.complexity == ComplexityTier.B


def test_fixture_triage_result_unknown_disregard_roundtrip() -> None:
    path = _FIXTURE_DIR / "triage_result_unknown_disregard.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    row = TriageResult.model_validate(data)
    assert row.intent == Intent.UNKNOWN
    assert row.disregard is True


def test_complexity_tiers_covers_all_enum_members() -> None:
    assert set(COMPLEXITY_TIERS) == set(ComplexityTier)


def test_triager_reexports_budget_regime() -> None:
    assert BudgetRegime is BudgetRegimeOrig


def test_message_kind_values() -> None:
    assert MessageKind.MESSAGE.value == "message"
    assert MessageKind.COMMAND.value == "command"
    assert MessageKind.BLOCKED.value == "blocked"


def test_session_visibility_literal_is_string_union() -> None:
    _vis: SessionVisibilityLiteral = "self"
    assert _vis == "self"


def test_default_tier_b_caps_match_spec() -> None:
    assert DEFAULT_TRIAGER_TIER_B_TOOL_CAP == 5
    assert DEFAULT_TRIAGER_TIER_B_SKILL_CAP == 7


def test_sqlite_triage_decisions_is_only_triage_prefixed_table() -> None:
    """``TriageResult`` stays Pydantic-only; audit rows live in ``triage_decisions`` (`specs/13` §3.3)."""

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%triage%'",
    ).fetchall()
    assert rows == [("triage_decisions",)]


def test_active_run_snapshot_tier_aligns_with_complexity_tier_literals() -> None:
    """Gateway snapshot ``tier`` is superset of ``ComplexityTier`` + ``triager`` sentinel."""

    ann = ActiveRunSnapshotWrite.model_fields["tier"].annotation
    literals = get_args(ann)
    assert set(literals) == {"triager", "A", "B", "C", "D"}
    assert {m.value for m in ComplexityTier} == {"A", "B", "C", "D"}


def test_followup_anchor_telegram_variant_parses() -> None:
    row = TriageResult.model_validate(
        {
            "intent": "FOLLOWUP",
            "complexity": "B",
            "first_message": "Continuing.",
            "tools": [],
            "skills": [],
            "mcp_servers_required": [],
            "confidence": 0.9,
            "requires_vision": False,
            "requires_document": False,
            "followup_anchor": {
                "channel": "telegram",
                "chat_id": 42,
                "topic_id": 7,
                "message_id": 123,
                "reply_to_message_id": 100,
            },
        },
    )
    assert isinstance(row.followup_anchor, TelegramFollowupAnchor)
    assert row.followup_anchor.chat_id == 42
    assert row.followup_anchor.reply_to_message_id == 100


def test_followup_anchor_webui_variant_parses() -> None:
    row = TriageResult.model_validate(
        {
            "intent": "FOLLOWUP",
            "complexity": "B",
            "first_message": "Same thread.",
            "tools": [],
            "skills": [],
            "mcp_servers_required": [],
            "confidence": 0.7,
            "requires_vision": False,
            "requires_document": False,
            "followup_anchor": {
                "channel": "webui",
                "session_id": "sess-abc",
                "message_id": "msg-1",
            },
        },
    )
    assert isinstance(row.followup_anchor, WebUIFollowupAnchor)
    assert row.followup_anchor.session_id == "sess-abc"


def test_followup_anchor_rejects_unknown_channel() -> None:
    with pytest.raises(ValidationError):
        TriageResult.model_validate(
            {
                "intent": "FOLLOWUP",
                "complexity": "B",
                "first_message": "Hmm.",
                "tools": [],
                "skills": [],
                "mcp_servers_required": [],
                "confidence": 0.4,
                "requires_vision": False,
                "requires_document": False,
                "followup_anchor": {"channel": "imessage", "thread": "x"},
            },
        )


def test_followup_anchor_telegram_rejects_extra_keys() -> None:
    with pytest.raises(ValidationError):
        TelegramFollowupAnchor.model_validate(
            {
                "channel": "telegram",
                "chat_id": 1,
                "unknown_field": "no",
            },
        )


def test_followup_anchor_optional_none() -> None:
    row = TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="No anchor needed.",
        tools=[],
        skills=[],
        mcp_servers_required=[],
        confidence=0.5,
        requires_vision=False,
        requires_document=False,
    )
    assert row.followup_anchor is None


def test_triage_schema_export_matches_on_disk() -> None:
    """``infra/triage_result.schema.json`` stays in sync with the Pydantic model (`specs/10` §11)."""

    on_disk = json.loads(schema_path().read_text(encoding="utf-8"))
    assert on_disk == build_schema()


def test_triage_schema_export_describes_discriminated_union() -> None:
    schema = build_schema()
    anchor = schema["properties"]["followup_anchor"]["anyOf"][0]
    assert anchor["discriminator"]["propertyName"] == "channel"
    assert set(anchor["discriminator"]["mapping"]) == {"telegram", "webui"}
