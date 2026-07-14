"""Summary-lint and INDEX status contracts (D7-D8; green after W3)."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from sevn.docs.readme.catalog import build_index_rows
from sevn.docs.readme.fingerprint import (
    compute_digest,
    load_fingerprints,
    save_fingerprints,
    upsert_entry,
)
from sevn.docs.readme.manifest import ReadmeEntry, ReadmeManifest, load_manifest
from sevn.docs.readme.render import render_readme_markdown

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "docs/readmes/manifest.toml"


def _lint_summaries(manifest: ReadmeManifest, repo_root: Path) -> list[str]:
    verify = importlib.import_module("sevn.docs.readme.verify")
    fn = getattr(verify, "lint_summaries", None)
    assert fn is not None, "lint_summaries not implemented (green after W3)"
    findings = fn(manifest, repo_root)
    if isinstance(findings, list):
        return [str(item) for item in findings]
    return [str(item) for item in getattr(findings, "errors", findings)]


def test_lint_summaries_flags_summary_with_absent_symbol(tmp_path: Path) -> None:
    """D7: ``lint_summaries`` errors when a summary cites a symbol absent from ``source_globs``."""
    (tmp_path / "src/sevn/demo").mkdir(parents=True)
    (tmp_path / "src/sevn/demo/real.py").write_text(
        "def exists() -> None:\n    pass\n", encoding="utf-8"
    )
    manifest_path = tmp_path / "manifest.toml"
    manifest_path.write_text(
        "version = 1\n"
        "[[readme]]\n"
        'slug = "demo"\n'
        'title = "Demo"\n'
        'summary = "Uses `MissingSymbol` that is not in source."\n'
        'profile = "subsystem"\n'
        'tier_owner = "docs"\n'
        'output = "docs/readmes/demo.md"\n'
        'source_globs = ["src/sevn/demo/**"]\n',
        encoding="utf-8",
    )
    manifest = load_manifest(manifest_path)
    findings = _lint_summaries(manifest, tmp_path)
    assert any("MissingSymbol" in item or "demo" in item for item in findings)


def test_lint_summaries_passes_truthful_summary(tmp_path: Path) -> None:
    """D7: ``lint_summaries`` passes when cited symbols exist under the entry globs."""
    (tmp_path / "src/sevn/demo").mkdir(parents=True)
    (tmp_path / "src/sevn/demo/real.py").write_text(
        "class Real:\n    def exists(self) -> None:\n        pass\n",
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.toml"
    manifest_path.write_text(
        "version = 1\n"
        "[[readme]]\n"
        'slug = "demo"\n'
        'title = "Demo"\n'
        'summary = "Entry point `Real.exists` lives here."\n'
        'profile = "subsystem"\n'
        'tier_owner = "docs"\n'
        'output = "docs/readmes/demo.md"\n'
        'source_globs = ["src/sevn/demo/**"]\n',
        encoding="utf-8",
    )
    manifest = load_manifest(manifest_path)
    assert _lint_summaries(manifest, tmp_path) == []


@pytest.mark.asyncio
async def test_index_status_renders_fresh_with_accuracy_note(tmp_path: Path) -> None:
    """D8: INDEX status column uses ``fresh`` and documents freshness ≠ accuracy."""
    manifest_dir = tmp_path / "docs/readmes"
    manifest_dir.mkdir(parents=True)
    demo_entry = ReadmeEntry(
        slug="demo",
        title="Demo",
        summary="Demo summary.",
        profile="freeform",
        tier_owner="docs",
        output="docs/readmes/demo.md",
        source_globs=("docs/readmes/manifest.toml",),
        specs=(),
    )
    index_entry = ReadmeEntry(
        slug="index",
        title="README catalog",
        summary="Generated catalog.",
        profile="index",
        tier_owner="docs",
        output="docs/readmes/INDEX.md",
        source_globs=("docs/readmes/manifest.toml",),
        specs=(),
    )
    manifest = ReadmeManifest(version=1, entries=(demo_entry, index_entry))
    manifest_dir.joinpath("manifest.toml").write_text(
        "version = 1\n"
        "[[readme]]\n"
        'slug = "demo"\n'
        'title = "Demo"\n'
        'summary = "Demo summary."\n'
        'profile = "freeform"\n'
        'tier_owner = "docs"\n'
        'output = "docs/readmes/demo.md"\n'
        'source_globs = ["docs/readmes/manifest.toml"]\n'
        "[[readme]]\n"
        'slug = "index"\n'
        'title = "README catalog"\n'
        'summary = "Generated catalog."\n'
        'profile = "index"\n'
        'tier_owner = "docs"\n'
        'output = "docs/readmes/INDEX.md"\n'
        'source_globs = ["docs/readmes/manifest.toml"]\n',
        encoding="utf-8",
    )
    (tmp_path / "src/sevn/demo").mkdir(parents=True)
    (tmp_path / "src/sevn/demo/a.py").write_text("x = 1\n", encoding="utf-8")
    manifest_dir.joinpath("demo.md").write_text("> **Summary.** Demo\n", encoding="utf-8")
    fp_path = manifest_dir / "_fingerprints.json"
    store = load_fingerprints(fp_path)
    upsert_entry(
        store,
        slug="demo",
        digest=compute_digest(tmp_path, demo_entry.source_globs),
        source_globs=demo_entry.source_globs,
    )
    save_fingerprints(fp_path, store)
    markdown = await render_readme_markdown(
        repo_root=tmp_path,
        entry=index_entry,
        manifest=manifest,
    )
    rows = build_index_rows(tmp_path, manifest, fingerprints_path=fp_path)
    assert rows
    assert all(row["status"] == "fresh" for row in rows if row["slug"] == "demo")
    assert "| fresh |" in markdown or " fresh " in markdown
    lowered = markdown.lower()
    assert "freshness" in lowered
    assert "accuracy" in lowered


def test_repo_manifest_summaries_pass_lint_summaries() -> None:
    """D7/D10: fixed manifest summaries pass ``lint_summaries`` (regression guard post-W4)."""
    manifest = load_manifest(MANIFEST_PATH)
    assert _lint_summaries(manifest, REPO_ROOT) == []
