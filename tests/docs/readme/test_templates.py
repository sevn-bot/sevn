"""Tests for the per-README template validator (`sevn.docs.readme.templates`)."""

from __future__ import annotations

from pathlib import Path

from sevn.docs.readme.manifest import ReadmeEntry, load_manifest
from sevn.docs.readme.templates import (
    resolve_template_path,
    validate_against_template,
)

REPO = Path(__file__).resolve().parents[3]


def _entry(slug: str, *, template: str = "") -> ReadmeEntry:
    return ReadmeEntry(
        slug=slug,
        title=slug,
        summary="s",
        profile="subsystem",
        tier_owner="t",
        output=f"docs/readmes/{slug}.md",
        source_globs=("src/x/**",),
        specs=(),
        curated=True,
        template=template,
    )


def test_resolve_template_path_convention() -> None:
    """Default template path follows the slug convention."""
    path = resolve_template_path(Path("/repo"), _entry("gateway"))
    assert path == Path("/repo/docs/readmes/_templates/gateway.md")


def test_resolve_template_path_explicit_override() -> None:
    """An explicit template key wins over the slug convention."""
    path = resolve_template_path(
        Path("/repo"), _entry("g", template="docs/readmes/_templates/x.md")
    )
    assert path == Path("/repo/docs/readmes/_templates/x.md")


def test_wildcard_title_matches_any_h1() -> None:
    """A `# <Title>` wildcard matches any concrete H1."""
    template = "# <Title>\n## References\n"
    body = "# Gateway — control plane\n## References\n"
    assert validate_against_template(template, body) == []


def test_missing_heading_is_reported() -> None:
    """An absent required heading is flagged as missing-heading."""
    template = "# <T>\n## Level 2 — How it works (technical)\n## References\n"
    body = "# G\n## References\n"
    errors = validate_against_template(template, body)
    assert [e.kind for e in errors] == ["missing-heading"]
    assert "Level 2" in errors[0].detail


def test_out_of_order_heading_is_distinguished() -> None:
    """A present-but-misordered heading is flagged out-of-order, not missing."""
    template = "# <T>\n## Level 1 — Overview (non-technical)\n## References\n"
    body = "# G\n## References\n## Level 1 — Overview (non-technical)\n"
    errors = validate_against_template(template, body)
    assert any(e.kind == "out-of-order-heading" for e in errors)


def test_extra_headings_between_anchors_are_allowed() -> None:
    """Per-module `###` sections between anchors do not break the subsequence match."""
    template = "# <T>\n## Level 2 — How it works (technical)\n### Key modules\n## References\n"
    body = (
        "# G\n## Level 2 — How it works (technical)\n"
        "### Turn spine\n### Queue modes\n### Key modules\n"
        "### Extra\n## References\n"
    )
    assert validate_against_template(template, body) == []


def test_headings_inside_comments_are_ignored() -> None:
    """Headings inside `<!-- fill -->` guidance are not treated as requirements."""
    template = "# <T>\n<!-- fill:\n## Not required\n-->\n## References\n"
    body = "# G\n## References\n"
    assert validate_against_template(template, body) == []


def test_missing_summary_marker() -> None:
    """A template Summary marker requires one in the README."""
    template = "# <T>\n> **Summary.** x\n## References\n"
    body = "# G\n## References\n"
    errors = validate_against_template(template, body)
    assert any(e.kind == "missing-summary" for e in errors)


def test_every_curated_readme_matches_its_template() -> None:
    """Each curated manifest entry validates against its slug template."""
    manifest = load_manifest(REPO / "docs/readmes/manifest.toml")
    curated = [e for e in manifest.entries if e.curated]
    assert curated, "expected curated entries in the manifest"
    for entry in curated:
        template_path = resolve_template_path(REPO, entry)
        assert template_path.is_file(), f"{entry.slug}: template missing at {template_path}"
        readme = (REPO / entry.output).read_text(encoding="utf-8")
        template_text = template_path.read_text(encoding="utf-8")
        errors = validate_against_template(template_text, readme)
        assert errors == [], f"{entry.slug}: {[str(e) for e in errors]}"
