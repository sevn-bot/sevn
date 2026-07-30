"""W13.1 — manifest dependency field (D7 → W14)."""

from __future__ import annotations

import textwrap

import pytest

from sevn.skills.manifest import manifest_from_mapping


def _skill_dependencies(manifest: object) -> object:
    """Lazy import of the W14 dependency accessor."""
    from sevn.skills.dependencies import SkillDependencies

    deps = getattr(manifest, "dependencies", None)
    if deps is None:
        msg = "SkillManifest.dependencies missing — implement in W14 (D7)"
        raise AssertionError(msg)
    assert isinstance(deps, SkillDependencies)
    return deps


def _skill_setup_status(manifest: object) -> str:
    """Lazy import of the W14 setup-status helper."""
    from sevn.skills.setup import skill_setup_status

    return skill_setup_status(manifest)


@pytest.mark.xfail(reason="green after W14: manifest dependencies field (D7)", strict=False)
def test_manifest_dependencies_round_trip_from_frontmatter_mapping() -> None:
    """A ``SKILL.md`` declaring dependencies round-trips through ``manifest_from_mapping``."""
    data = {
        "name": "job-ops",
        "description": "Job discovery",
        "version": "1.0.0",
        "dependencies": {
            "uv_extras": ["job-ops"],
            "executables": ["yt-dlp"],
        },
    }
    manifest = manifest_from_mapping(data, body="", provenance="user")
    deps = _skill_dependencies(manifest)
    assert deps.uv_extras == ("job-ops",)
    assert deps.executables == ("yt-dlp",)


@pytest.mark.xfail(reason="green after W14: manifest dependencies field (D7)", strict=False)
def test_manifest_dependencies_optional_fields_default_empty() -> None:
    """Partial dependency declarations default missing halves to empty tuples."""
    data = {
        "name": "yt-dlp",
        "description": "Media download",
        "version": "1.0.0",
        "dependencies": {"executables": ["yt-dlp"]},
    }
    manifest = manifest_from_mapping(data, body="", provenance="user")
    deps = _skill_dependencies(manifest)
    assert deps.uv_extras == ()
    assert deps.executables == ("yt-dlp",)


@pytest.mark.xfail(reason="green after W14: no-setup-required status (D7)", strict=False)
def test_skill_without_dependencies_reports_no_setup_required() -> None:
    """Skills omitting the field report ``no setup required``."""
    data = {
        "name": "plain",
        "description": "No deps",
        "version": "1.0.0",
    }
    manifest = manifest_from_mapping(data, body="", provenance="user")
    assert _skill_setup_status(manifest) == "no setup required"


@pytest.mark.xfail(
    reason="green after W14: parse_skill_markdown dependency round-trip", strict=False
)
def test_parse_skill_markdown_dependencies_from_full_document() -> None:
    """End-to-end ``SKILL.md`` parse preserves dependency metadata."""
    from sevn.skills.manifest import parse_skill_markdown

    raw = textwrap.dedent(
        """\
        ---
        name: demo
        description: demo
        version: 1.0.0
        scripts: []
        dependencies:
          uv_extras:
            - job-ops
        ---
        body
        """
    )
    manifest = parse_skill_markdown(raw, "user")
    deps = _skill_dependencies(manifest)
    assert deps.uv_extras == ("job-ops",)
    assert _skill_setup_status(manifest) != "no setup required"
