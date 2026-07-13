"""Tests for curated manifest flag and stale hints (D1-D3; green after W2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sevn.docs.readme.manifest import get_entry, load_manifest


def _manifest_with_curated(tmp_path: Path, *, curated: bool | None) -> Path:
    manifest_path = tmp_path / "manifest.toml"
    curated_line = ""
    if curated is True:
        curated_line = "curated = true\n"
    manifest_path.write_text(
        "version = 1\n"
        "[[readme]]\n"
        'slug = "hand"\n'
        'title = "Hand"\n'
        'summary = "Hand-authored README."\n'
        'profile = "freeform"\n'
        'tier_owner = "docs"\n'
        'output = "docs/readmes/hand.md"\n'
        'source_globs = ["src/sevn/hand/**"]\n'
        f"{curated_line}",
        encoding="utf-8",
    )
    return manifest_path


def test_manifest_parses_curated_true(tmp_path: Path) -> None:
    """D2: ``curated = true`` maps to ``ReadmeEntry.curated``."""
    manifest_path = _manifest_with_curated(tmp_path, curated=True)
    entry = get_entry(load_manifest(manifest_path), "hand")
    assert entry.curated is True


def test_manifest_curated_defaults_false(tmp_path: Path) -> None:
    """D2: omitted ``curated`` defaults to false."""
    manifest_path = _manifest_with_curated(tmp_path, curated=None)
    entry = get_entry(load_manifest(manifest_path), "hand")
    assert entry.curated is False


def test_manifest_rejects_non_bool_curated(tmp_path: Path) -> None:
    """D2: non-boolean ``curated`` values fail manifest validation."""
    manifest_path = tmp_path / "manifest.toml"
    manifest_path.write_text(
        "version = 1\n"
        "[[readme]]\n"
        'slug = "hand"\n'
        'title = "Hand"\n'
        'summary = "Hand-authored README."\n'
        'profile = "freeform"\n'
        'tier_owner = "docs"\n'
        'output = "docs/readmes/hand.md"\n'
        'source_globs = ["src/sevn/hand/**"]\n'
        'curated = "yes"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="curated"):
        load_manifest(manifest_path)
