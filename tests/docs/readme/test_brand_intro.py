"""Tests for root README brand intro loading."""

from __future__ import annotations

from pathlib import Path

from sevn.docs.readme.brand import load_root_intro_lines

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_load_root_intro_lines_from_brand_toml() -> None:
    """Root intro verse loads from docs/brand/root-intro.toml."""
    lines = load_root_intro_lines(REPO_ROOT)
    assert len(lines) >= 8
    assert lines[0].startswith("I'm Sevn")
    assert any("Python" in line for line in lines)


def test_root_template_renders_intro_verse() -> None:
    """Root README template renders intro lines instead of legacy title/tagline."""
    from sevn.docs.readme import render_profile
    from sevn.docs.readme.fixtures import FIXTURE_CONTEXTS

    markdown = render_profile("root", FIXTURE_CONTEXTS["root"])
    assert "Personal AI Assistant" not in markdown
    assert "One bot. Your machine. Your model. Your memory." not in markdown
    assert "I'm Sevn. I'm more than a bot," in markdown
    assert "Your gateway, your rules" in markdown
