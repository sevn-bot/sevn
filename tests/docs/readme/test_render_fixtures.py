"""Tests for README template offline rendering (Wave 1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sevn.docs.readme import PROFILE_TEMPLATES, render_all_fixtures, render_profile
from sevn.docs.readme.fixtures import FIXTURE_CONTEXTS
from sevn.docs.readme.render import prompts_dir, templates_dir, validate_rendered_markdown

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("profile", list(PROFILE_TEMPLATES))
def test_profile_renders_without_validation_errors(profile: str) -> None:
    """Each §C0 profile renders GitHub-safe markdown with resolvable images."""
    markdown = render_profile(profile, FIXTURE_CONTEXTS[profile])
    errors = validate_rendered_markdown(markdown, repo_root=REPO_ROOT)
    assert not errors, "; ".join(errors)


def test_root_template_has_required_sections() -> None:
    """Root profile includes STANDARD §B structural headings."""
    markdown = render_profile("root", FIXTURE_CONTEXTS["root"])
    assert "I'm Sevn. I'm more than a bot," in markdown
    for heading in (
        "## Highlights",
        "## Architecture at a glance",
        "## Subsystem map",
        "## Quick start",
        "## Install",
        "## License",
    ):
        assert heading in markdown


def test_subsystem_template_has_three_tiers() -> None:
    """Subsystem profile includes Summary and L1/L2/L3 tier headings."""
    markdown = render_profile("subsystem", FIXTURE_CONTEXTS["subsystem"])
    assert "> **Summary.**" in markdown
    assert "## Level 1 — Overview" in markdown
    assert "## Level 2 — How it works" in markdown
    assert "## Level 3 — Deep dive" in markdown
    assert "## References" in markdown


def test_shipped_templates_and_prompts_exist() -> None:
    """All template and Wave 1 prompt files are present on disk."""
    for template in PROFILE_TEMPLATES.values():
        assert (templates_dir / template).is_file()
    for prompt in (
        "summary.toml",
        "overview.toml",
        "how-it-works.toml",
        "deep-dive.toml",
        "root-valueprop.toml",
        "highlights.toml",
    ):
        assert (prompts_dir / prompt).is_file()


def test_render_all_fixtures_validates_against_repo() -> None:
    """Batch fixture render passes structural validation."""
    outputs = render_all_fixtures(repo_root=REPO_ROOT)
    assert set(outputs) == set(PROFILE_TEMPLATES)
