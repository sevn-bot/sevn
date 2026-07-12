"""Telegram routing footer (`plan/operator-experience-wave-plan.md` Wave 6)."""

from __future__ import annotations

from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.routing_footer import (
    append_routing_footer,
    format_routing_footer,
    strip_model_emitted_footer,
    telegram_show_routing_enabled,
)


def _sample_triage() -> TriageResult:
    return TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="hello",
        tools=[],
        skills=[],
        mcp_servers_required=[],
        confidence=0.75,
        requires_vision=False,
        requires_document=False,
    )


def test_format_routing_footer() -> None:
    line = format_routing_footer(_sample_triage())
    assert "intent=NEW_REQUEST" in line
    assert "tier=B" in line
    assert "conf=0.75" in line


def test_format_routing_footer_includes_triager_s() -> None:
    line = format_routing_footer(_sample_triage(), triager_ms=321)
    assert "triager_s=0" in line
    assert "triager_ms=" not in line


def test_append_routing_footer_when_enabled() -> None:
    out = append_routing_footer("Reply body", _sample_triage())
    assert "Reply body" in out
    assert "intent=NEW_REQUEST" in out


def test_telegram_show_routing_default_off() -> None:
    ws = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    assert telegram_show_routing_enabled(ws) is False


def test_telegram_show_routing_reads_config() -> None:
    from sevn.config.workspace_config import ChannelsWorkspaceSectionConfig, TelegramChannelConfig

    ws = WorkspaceConfig(
        schema_version=1,
        channels=ChannelsWorkspaceSectionConfig(
            telegram=TelegramChannelConfig(show_routing=True),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    assert telegram_show_routing_enabled(ws) is True


def test_strip_model_emitted_footer_removes_clean_variant() -> None:
    """The canonical italic footer shape is stripped."""
    text = "Here is my answer.\n\n_intent=NEW_REQUEST · tier=B · conf=0.95_"
    assert strip_model_emitted_footer(text) == "Here is my answer."


def test_strip_model_emitted_footer_removes_corrupted_variant() -> None:
    """The corrupted ``er=B`` variant from the 2026-05-25 transcript is stripped."""
    text = "Yes — I have access.\n\n_intent=NEW_REQUEST er=B · conf=0.95_"
    assert strip_model_emitted_footer(text) == "Yes — I have access."


def test_strip_model_emitted_footer_removes_triager_s_suffix() -> None:
    """Wave W3: the canonical footer carries ``· triager_s=N`` after ``conf=``.

    The 2026-05-30 leak: this suffix survived the persistence-time strip, so the
    footer landed in ``visible_to_llm`` history and the executor echoed it.
    """
    text = "Hello there.\n\n_intent=GREETING · tier=A · conf=1.00 · triager_s=0_"
    assert strip_model_emitted_footer(text) == "Hello there."


def test_strip_model_emitted_footer_removes_full_tools_skills_suffix() -> None:
    """The full footer (tools + skills + triager_s) is stripped, not just the prefix."""
    text = (
        "The answer.\n\n"
        "_intent=NEW_REQUEST · tier=B · conf=0.82 · "
        "tools=[read,log_query] · skills=[lcm] · triager_s=9_"
    )
    assert strip_model_emitted_footer(text) == "The answer."


def test_append_then_strip_round_trips_to_clean_body() -> None:
    """The exact footer ``append_routing_footer`` emits must strip back to the body.

    This is the W3 invariant: whatever the gateway appends for display, the
    persistence-time strip must reduce to the clean ``visible_to_llm`` body.
    """
    body = "Here is the substantive answer."
    triage = TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="On it.",
        tools=["read"],
        skills=["lcm"],
        mcp_servers_required=[],
        confidence=1.0,
        requires_vision=False,
        requires_document=False,
    )
    rendered = append_routing_footer(body, triage, triager_ms=712)
    assert "triager_s=" in rendered  # display copy carries the suffix
    assert strip_model_emitted_footer(rendered) == body


def test_strip_model_emitted_footer_leaves_plain_text_alone() -> None:
    """Text that does not contain both ``intent=`` and ``conf=`` is untouched."""
    assert strip_model_emitted_footer("plain reply") == "plain reply"
    assert strip_model_emitted_footer("see intent= in flow") == "see intent= in flow"


def test_append_routing_footer_strips_duplicate_before_adding() -> None:
    """The gateway-appended footer replaces (not duplicates) a model-emitted variant."""
    text = "Reply body.\n\n_intent=GREETING · er=A · conf=1.00_"
    out = append_routing_footer(text, _sample_triage())
    # Only one footer remains, and it is the structured (well-formed) one.
    assert out.count("intent=") == 1
    assert "tier=B" in out
    assert "er=A" not in out
