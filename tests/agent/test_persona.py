"""Persona block loader (`src/sevn/agent/persona.py`, recovery Wave A)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from pydantic_ai import Agent

from sevn.agent import persona as persona_mod
from sevn.agent.persona import (
    load_persona_block,
    tier_b_repo_access_prompt,
    tier_b_workspace_roots_prompt,
)


def test_load_persona_block_includes_agents_md(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "AGENTS.md").write_text("Use source_code/ for package reads.", encoding="utf-8")

    block = load_persona_block(root)

    assert "## AGENTS.md" in block
    assert "source_code/" in block


def test_load_persona_block_prefers_workspace_identity(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "IDENTITY.md").write_text("CustomSevn identity marker", encoding="utf-8")

    block = load_persona_block(root)

    assert "CustomSevn identity marker" in block
    assert "## IDENTITY.md" in block


def test_load_persona_block_appends_skills_section(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "IDENTITY.md").write_text("Name: Sevn", encoding="utf-8")

    block = load_persona_block(root, skill_descriptions={"tick": "Deterministic harness tick."})

    assert "## What I can do" in block
    assert "**tick**" in block


def test_load_persona_block_cache_ttl(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    path = root / "IDENTITY.md"
    path.write_text("version-one", encoding="utf-8")

    persona_mod._cache.clear()
    clock = {"t": 0.0}

    def monotonic() -> float:
        return clock["t"]

    with patch.object(persona_mod.time, "monotonic", monotonic):
        first = load_persona_block(root)
        clock["t"] = 1.0
        second = load_persona_block(root)
        assert second == first

        path.write_text("version-two", encoding="utf-8")
        clock["t"] = 7.0
        third = load_persona_block(root)
    assert "version-two" in third


def test_agent_system_prompt_receives_persona_block(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "IDENTITY.md").write_text("AgentPersonaMarker", encoding="utf-8")
    captured: dict[str, object] = {}
    original_init = Agent.__init__

    def _capture_init(self: Agent, *args: object, **kwargs: object) -> None:
        captured.update(kwargs)
        return original_init(self, *args, **kwargs)

    with patch.object(Agent, "__init__", _capture_init):
        block = load_persona_block(root)
        Agent(model="test", system_prompt=block)

    assert captured.get("system_prompt") == block
    assert "AgentPersonaMarker" in str(captured.get("system_prompt"))


def test_workspace_roots_prompt_teaches_canonical_path_scheme(tmp_path: Path) -> None:
    """The workspace-roots block teaches source_code/ + bare paths, never @repo/.

    Regression for ``plan/minimax-m3-session-bugs-plan.md`` P2: the model wasted
    rounds probing ``workspace/`` and ``@repo/`` prefixes that do not resolve.
    """
    block = tier_b_workspace_roots_prompt(tmp_path / "ws")

    assert "source_code/" in block
    assert "bare paths" in block
    # No-op prefixes are explicitly disclaimed, never advertised.
    assert "no `@repo/` prefix" in block
    assert "Do **not** prefix with `workspace/`" in block


def test_repo_access_prompt_drops_repo_prefix(tmp_path: Path) -> None:
    """The repo-access block uses source_code/ and disclaims the @repo/ prefix."""
    block = tier_b_repo_access_prompt(None, tmp_path / "ws")

    assert "source_code/" in block
    assert "no `@repo/` prefix" in block
    # Bare workspace files are taught, not a workspace/ prefix.
    assert "bare paths" in block
    assert "never prefix them with `workspace/`" in block
