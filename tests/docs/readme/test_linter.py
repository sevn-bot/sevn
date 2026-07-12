"""Tests for GitHub-safe markdown linter rules (§E)."""

from __future__ import annotations

from pathlib import Path

from sevn.docs.readme.render import validate_rendered_markdown

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_forbidden_script_tag_fails() -> None:
    """Script tags are rejected."""
    errors = validate_rendered_markdown("<script>alert(1)</script>\n", repo_root=REPO_ROOT)
    assert errors


def test_forbidden_class_attribute_fails() -> None:
    """class= attributes are rejected."""
    errors = validate_rendered_markdown('<div class="x">nope</div>\n', repo_root=REPO_ROOT)
    assert errors


def test_reference_style_badge_links_allowed() -> None:
    """Reference-style shields.io badge definitions are allowed."""
    md = (
        "[![Docs][docs-badge]][docs-link]\n\n"
        "[docs-badge]: https://img.shields.io/badge/Docs-5fb1f7?style=for-the-badge\n"
        "[docs-link]: docs/readmes/INDEX.md\n"
    )
    errors = validate_rendered_markdown(md, repo_root=REPO_ROOT)
    assert not errors


def test_details_summary_allowed() -> None:
    """Collapsible details blocks are allowed."""
    md = "<details><summary>TOC</summary>\n\n- one\n</details>\n"
    errors = validate_rendered_markdown(md, repo_root=REPO_ROOT)
    assert not errors
