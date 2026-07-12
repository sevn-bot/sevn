"""Wave W4.2: ``SESSIONS.md`` recall guide is loaded into tier-B context."""

from __future__ import annotations

from pathlib import Path

from sevn.prompts.tier_b import tier_b_sessions_context_prompt


def test_sessions_template_loaded_from_packaged_fallback() -> None:
    block = tier_b_sessions_context_prompt(Path("/nonexistent/workspace"))
    assert "## SESSIONS.md" in block
    assert "history" in block.lower()
    assert "sessions/" in block


def test_sessions_template_prefers_workspace_overlay(tmp_path: Path) -> None:
    custom = "# Custom recall\nUse the history tool first."
    _ = (tmp_path / "SESSIONS.md").write_text(custom, encoding="utf-8")
    block = tier_b_sessions_context_prompt(tmp_path)
    assert "Custom recall" in block
    assert "Use the history tool first." in block


def test_b_harness_prompt_blocks_include_w4_playbook(tmp_path: Path) -> None:
    """Tier-B W4 playbook blocks compose into one system-prompt slice."""
    _ = (tmp_path / "SESSIONS.md").write_text("Operator recall guide.", encoding="utf-8")
    from sevn.prompts.tier_b import tier_b_log_query_playbook_prompt, tier_b_persistence_prompt

    assembled = "\n\n".join(
        p
        for p in (
            tier_b_sessions_context_prompt(tmp_path),
            tier_b_log_query_playbook_prompt(),
            tier_b_persistence_prompt(),
        )
        if p.strip()
    )
    assert "Operator recall guide." in assembled
    assert "log_query playbook" in assembled.lower()
    assert "tool-error persistence" in assembled.lower()
