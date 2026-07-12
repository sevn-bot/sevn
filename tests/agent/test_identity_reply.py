"""IDENTITY.md resolved identity replies (live-session W8)."""

from __future__ import annotations

from pathlib import Path

from sevn.agent.identity_reply import (
    compose_identity_reply,
    identity_bootstrap_incomplete_fields,
    is_pure_identity_message,
    resolve_workspace_identity,
)
from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
from sevn.agent.triager.routing_policy import apply_routing_policy
from sevn.onboarding.seed import load_template
from sevn.prompts.tier_b import (
    _extract_identity_name,
    tier_b_identity_answer_prompt,
)


def test_pure_identity_message_detection() -> None:
    assert is_pure_identity_message("who are you?")
    assert is_pure_identity_message("What's your name?")
    assert not is_pure_identity_message("what can you do?")
    assert not is_pure_identity_message("hello")


def test_extract_identity_name_inline_and_section() -> None:
    assert _extract_identity_name("Name: testmee\n") == "testmee"
    assert _extract_identity_name("## Name\n\ntestmee\n") == "testmee"
    assert _extract_identity_name("## Name\n{{AGENT_NAME}}\n") == ""


def test_compose_identity_reply_uses_identity_name_not_product_label(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "IDENTITY.md").write_text(
        "## Name\n\ntestmee\n\n## Role\nPersonal helper for the operator.",
        encoding="utf-8",
    )
    reply = compose_identity_reply(root)
    assert reply is not None
    assert "testmee" in reply
    assert "sevn.bot" not in reply.lower()


def test_two_who_are_you_replies_same_identity_name(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "IDENTITY.md").write_text("## Name\n\ntestmee\n\n## Role\nhelper", encoding="utf-8")
    first = compose_identity_reply(root)
    second = compose_identity_reply(root)
    assert first == second
    assert first is not None
    assert "testmee" in first


def test_resolve_workspace_identity_name_role(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "IDENTITY.md").write_text("Name: Nova\nRole: analyst\n", encoding="utf-8")
    assert resolve_workspace_identity(root) == ("Nova", "analyst")


def test_identity_bootstrap_incomplete_flags_placeholder_name(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "IDENTITY.md").write_text(load_template("IDENTITY.md"), encoding="utf-8")
    fields = identity_bootstrap_incomplete_fields(root)
    assert "IDENTITY.md:Name" in fields


def test_tier_b_identity_answer_prompt_includes_resolved_name(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "IDENTITY.md").write_text("## Name\n\ntestmee", encoding="utf-8")
    block = tier_b_identity_answer_prompt(root)
    assert "testmee" in block


def test_routing_policy_still_coerces_identity_echo_to_tier_b() -> None:
    triage = TriageResult(
        intent=Intent.GREETING,
        complexity=ComplexityTier.A,
        first_message="who are you?",
        tools=[],
        skills=[],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
    )
    out = apply_routing_policy(triage, current_message="who are you?", turn_id="t1")
    assert out.complexity == ComplexityTier.B
