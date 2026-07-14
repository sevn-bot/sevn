"""Tier-B executor persona instructions (`specs/17-gateway.md` §2.6)."""

from __future__ import annotations

from pathlib import Path

from sevn.agent.triager.routing_policy import is_identity_or_capability_message
from sevn.gateway.triage.triage_context import (
    load_workspace_personality,
    tier_b_personality_instructions,
)


def test_load_workspace_personality_includes_identity(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "IDENTITY.md").write_text("Name: Sevn\nRole: assistant", encoding="utf-8")
    (root / "SOUL.md").write_text("Be helpful.", encoding="utf-8")

    bundle, version = load_workspace_personality(root)

    assert bundle is not None
    assert "IDENTITY.md" in bundle
    assert "Name: Sevn" in bundle
    assert version > 0


def test_tier_b_personality_instructions_identity_turn() -> None:
    md = "## IDENTITY.md\nName: Sevn\nRole: Personal AI assistant"
    out = tier_b_personality_instructions(md, identity_turn=True)

    assert "IDENTITY_TURN" in out
    assert "MiniMax" in out
    assert "Name: Sevn" in out
    assert is_identity_or_capability_message("who are you?")


def test_tier_b_personality_instructions_without_files() -> None:
    out = tier_b_personality_instructions(None, identity_turn=True)

    assert "You are Sevn" in out
    assert "IDENTITY_TURN" in out
