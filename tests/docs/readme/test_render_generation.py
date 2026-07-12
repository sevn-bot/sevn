"""Tests for Wave 2 README generation pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from sevn.docs.readme.manifest import get_entry, load_manifest
from sevn.docs.readme.render import render_manifest_slug, validate_rendered_markdown, write_readme

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "docs/readmes/manifest.toml"


@pytest.mark.asyncio
async def test_offline_gateway_generation_is_standard_compliant() -> None:
    """Offline gateway README includes Summary and three tiers."""
    markdown = await render_manifest_slug(
        repo_root=REPO_ROOT,
        manifest_path=MANIFEST_PATH,
        slug="gateway",
    )
    assert "> **Summary.**" in markdown
    assert "## Level 1 — Overview" in markdown
    assert "## Level 2 — How it works" in markdown
    assert "## Level 3 — Deep dive" in markdown
    assert "## References" in markdown
    assert "src/sevn/gateway/" in markdown
    errors = validate_rendered_markdown(markdown, repo_root=REPO_ROOT)
    assert not errors, "; ".join(errors)


@pytest.mark.asyncio
async def test_write_readme_updates_fingerprints(tmp_path: Path) -> None:
    """write_readme stamps _fingerprints.json for the slug."""
    src = tmp_path / "src/sevn/demo"
    src.mkdir(parents=True)
    (src / "mod.py").write_text("x = 1\n", encoding="utf-8")
    manifest = tmp_path / "manifest.toml"
    manifest.write_text(
        "version = 1\n"
        "[[readme]]\n"
        'slug = "demo"\n'
        'title = "Demo"\n'
        'summary = "Demo subsystem."\n'
        'profile = "subsystem"\n'
        'tier_owner = "demo"\n'
        'output = "docs/readmes/demo.md"\n'
        'source_globs = ["src/sevn/demo/**"]\n'
        'specs = ["specs/01-system-overview.md"]\n',
        encoding="utf-8",
    )
    loaded = load_manifest(manifest)
    entry = get_entry(loaded, "demo")
    fp_path = tmp_path / "docs/readmes/_fingerprints.json"
    out = await write_readme(repo_root=tmp_path, entry=entry, fingerprints_path=fp_path)
    assert out.is_file()
    assert fp_path.is_file()
    data = fp_path.read_text(encoding="utf-8")
    assert '"demo"' in data
    assert "sha256_glob_aggregate" in data
