"""Catalog coverage resolution (D19; green after W10)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sevn.docs.readme.manifest import load_manifest

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "docs/readmes/manifest.toml"
STANDARD_PATH = REPO_ROOT / "docs/readmes/STANDARD.md"

_LOAD_BEARING_PACKAGES = ("evolution", "plugins", "browser")


def _manifest_slugs() -> set[str]:
    return {entry.slug for entry in load_manifest(MANIFEST_PATH).entries}


def _manifest_source_globs_text() -> str:
    return MANIFEST_PATH.read_text(encoding="utf-8").lower()


def _standard_text() -> str:
    return STANDARD_PATH.read_text(encoding="utf-8").lower()


@pytest.mark.parametrize("package", _LOAD_BEARING_PACKAGES)
@pytest.mark.xfail(reason="green after W10: D19 catalog coverage decision", strict=False)
def test_load_bearing_package_is_catalogued_or_documented_out_of_catalog(
    package: str,
) -> None:
    """D19: ``evolution/``, ``plugins/``, ``browser/`` resolve via manifest row or STANDARD note."""
    slugs = _manifest_slugs()
    globs = _manifest_source_globs_text()
    standard = _standard_text()
    has_row = package in slugs or f"src/sevn/{package}/" in globs
    documented_out = (
        "out-of-catalog" in standard
        or "out of catalog" in standard
        or (f"{package}/" in standard and "intentionally" in standard)
    )
    assert has_row or documented_out
