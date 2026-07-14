"""Tests for README manifest parsing."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import sevn.docs.readme as readme_pkg
from sevn.docs.readme.manifest import get_entry, load_manifest
from sevn.docs.readme.profile_schemas import PROFILE_SCHEMAS

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "docs/readmes/manifest.toml"
STANDARD_PATH = REPO_ROOT / "docs/readmes/STANDARD.md"

BANNED_SUMMARY_PHRASES: tuple[tuple[str, str], ...] = (
    ("secrets", "keys never in the gateway"),
    ("tools", "@sevn_tool"),
    ("proxy-egress", "session tokens"),
    ("tracing", "logfire/otel"),
    ("storage", "activerunsnapshot"),
    ("channels", "voice hooks"),
    ("second-brain", "obsidian sync"),
)


def _lint_summaries(manifest_path: Path = MANIFEST_PATH) -> list[str]:
    verify = importlib.import_module("sevn.docs.readme.verify")
    fn = getattr(verify, "lint_summaries", None)
    assert fn is not None, "lint_summaries not implemented (green after W3)"
    manifest = load_manifest(manifest_path)
    findings = fn(manifest, REPO_ROOT)
    if isinstance(findings, list):
        return [str(item) for item in findings]
    return [str(item) for item in getattr(findings, "errors", findings)]


def test_load_manifest_has_gateway_subsystem() -> None:
    """Manifest loads and gateway row uses subsystem profile."""
    manifest = load_manifest(MANIFEST_PATH)
    assert manifest.version >= 1
    gateway = get_entry(manifest, "gateway")
    assert gateway.profile == "subsystem"
    assert gateway.source_globs == ("src/sevn/gateway/**",)
    assert "about-sevn.bot/specs/17-gateway.md" in gateway.specs


def test_manifest_rejects_unknown_profile(tmp_path: Path) -> None:
    """Invalid profile names fail fast."""
    bad = tmp_path / "manifest.toml"
    bad.write_text(
        'version = 1\n[[readme]]\nslug = "x"\nprofile = "nope"\nsource_globs = ["a"]\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="profile"):
        load_manifest(bad)


def test_get_entry_missing_slug_raises() -> None:
    """Unknown slug raises KeyError."""
    manifest = load_manifest(MANIFEST_PATH)
    with pytest.raises(KeyError):
        get_entry(manifest, "not-a-real-slug")


@pytest.mark.parametrize(("slug", "phrase"), BANNED_SUMMARY_PHRASES)
def test_manifest_summary_has_no_banned_phrase(slug: str, phrase: str) -> None:
    """D10: rewritten manifest summaries must not carry audit-banned phrases."""
    entry = get_entry(load_manifest(MANIFEST_PATH), slug)
    assert phrase not in entry.summary.lower()


def test_integrations_manifest_spec_is_cursor_cloud_agent() -> None:
    """D11: ``integrations.specs`` points at ``29-cursor-cloud-agent``, not plugin hooks."""
    entry = get_entry(load_manifest(MANIFEST_PATH), "integrations")
    assert entry.specs
    joined = " ".join(entry.specs).lower()
    assert "29-cursor-cloud-agent" in joined
    assert "34-plugin-hooks" not in joined


def test_manifest_summaries_pass_lint_summaries() -> None:
    """D7/D10: fixed summaries pass ``lint_summaries`` regression guard."""
    assert _lint_summaries() == []


def test_standard_section_f_lists_live_public_exports() -> None:
    """D12: STANDARD §F documents live ``sevn.docs.readme`` public exports."""
    section_f = STANDARD_PATH.read_text(encoding="utf-8").split("## G.", maxsplit=1)[0]
    for export in readme_pkg.__all__:
        assert export in section_f
    assert "generate_index" not in section_f
    assert "render," not in section_f


def test_standard_section_c0_matches_profile_schemas_registry() -> None:
    """D12: STANDARD §C0 profile-schema block matches ``profile_schemas.py``."""
    standard = STANDARD_PATH.read_text(encoding="utf-8")
    c0_block = standard.split("## C1.", maxsplit=1)[0]
    for profile, schema in PROFILE_SCHEMAS.items():
        assert profile in c0_block
        if schema.needs_tiers:
            assert "needs_tiers" in c0_block or "needs tiers" in c0_block.lower()
        if schema.verify_symbol_refs:
            assert "verify_symbol_refs" in c0_block or "Symbol-ref check" in c0_block
        if schema.requires_table:
            assert "requires_table" in c0_block or "requires table" in c0_block.lower()
        if schema.requires_step_sections:
            assert "requires_step_sections" in c0_block or "requires step" in c0_block.lower()
        if schema.verify_path_refs:
            assert "verify_path_refs" in c0_block or "paths only" in c0_block.lower()
