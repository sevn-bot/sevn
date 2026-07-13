"""Tests for README manifest parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from sevn.docs.readme.manifest import get_entry, load_manifest

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "docs/readmes/manifest.toml"


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
