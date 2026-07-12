"""Routing footer ``triager_s`` whole-second display (gateway operator-recovery W7)."""

from __future__ import annotations

from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
from sevn.gateway.routing_footer import append_routing_footer, format_routing_footer
from sevn.gateway.turn_metadata import TurnMetadata, format_intent_footer_from_metadata


def _sample_triage() -> TriageResult:
    return TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="hello",
        tools=["read"],
        skills=["lcm"],
        mcp_servers_required=[],
        confidence=0.82,
        requires_vision=False,
        requires_document=False,
    )


def test_format_routing_footer_triager_s_rounds_ms_to_seconds() -> None:
    line = format_routing_footer(_sample_triage(), triager_ms=8635)
    assert "triager_s=9" in line
    assert "triager_ms=" not in line


def test_format_routing_footer_triager_s_subsecond_rounds_to_zero() -> None:
    line = format_routing_footer(_sample_triage(), triager_ms=499)
    assert "triager_s=0" in line
    assert "triager_ms=" not in line


def test_append_routing_footer_uses_triager_s() -> None:
    out = append_routing_footer("Reply", _sample_triage(), triager_ms=1500)
    assert "triager_s=2" in out
    assert "triager_ms=" not in out


def test_turn_metadata_footer_mirrors_triager_s() -> None:
    meta = TurnMetadata(
        turn_id="t1",
        session_id="s1",
        intent="GREETING",
        tier="A",
        confidence=0.95,
        model_id=None,
        started_at="2026-01-01T00:00:00+00:00",
        finished_at=None,
        status="in_flight",
    )
    line = format_intent_footer_from_metadata(meta, triager_ms=8635)
    assert "triager_s=9" in line
    assert "triager_ms=" not in line
