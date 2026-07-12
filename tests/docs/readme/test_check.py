"""Tests for README check and staleness gate."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from sevn.docs.readme.check import check_readme_tree
from sevn.docs.readme.fingerprint import (
    compute_digest,
    load_fingerprints,
    save_fingerprints,
    upsert_entry,
)
from sevn.docs.readme.manifest import ReadmeEntry, ReadmeManifest, get_entry
from sevn.docs.readme.render import write_readme


def _minimal_manifest() -> ReadmeManifest:
    entry = ReadmeEntry(
        slug="demo",
        title="Demo",
        summary="Demo summary for tests.",
        profile="freeform",
        tier_owner="docs",
        output="docs/readmes/demo.md",
        source_globs=("src/sevn/demo/**",),
        specs=(),
    )
    return ReadmeManifest(version=1, entries=(entry,))


async def _write_demo(repo_root: Path) -> None:
    manifest = _minimal_manifest()
    entry = get_entry(manifest, "demo")
    (repo_root / "src/sevn/demo").mkdir(parents=True)
    (repo_root / "src/sevn/demo/a.py").write_text("x = 1\n", encoding="utf-8")
    await write_readme(repo_root=repo_root, entry=entry, manifest=manifest)


def test_check_passes_after_generate() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        asyncio.run(_write_demo(repo))
        result = check_readme_tree(repo, _minimal_manifest())
        assert result.ok


def test_check_fails_on_stale_fingerprint() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        asyncio.run(_write_demo(repo))
        (repo / "src/sevn/demo/a.py").write_text("x = 2\n", encoding="utf-8")
        result = check_readme_tree(repo, _minimal_manifest())
        assert not result.ok
        assert any("stale" in err for err in result.errors)


def test_check_fails_on_missing_file() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        result = check_readme_tree(repo, _minimal_manifest())
        assert not result.ok
        assert any("missing README" in err for err in result.errors)


def test_check_fails_on_missing_subsystem_heading() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        manifest_dir = repo / "docs/readmes"
        manifest_dir.mkdir(parents=True)
        entry = ReadmeEntry(
            slug="demo",
            title="Demo",
            summary="Demo summary.",
            profile="subsystem",
            tier_owner="docs",
            output="docs/readmes/demo.md",
            source_globs=("src/sevn/demo/**",),
            specs=(),
        )
        manifest = ReadmeManifest(version=1, entries=(entry,))
        (repo / "src/sevn/demo").mkdir(parents=True)
        (repo / "src/sevn/demo/a.py").write_text("x = 1\n", encoding="utf-8")
        manifest_dir.joinpath("demo.md").write_text(
            "> **Summary.** ok\n\n## Level 1 — Overview\n\n## Level 2 — How it works\n\n## References\n",
            encoding="utf-8",
        )
        fp_path = manifest_dir / "_fingerprints.json"
        store = load_fingerprints(fp_path)
        upsert_entry(
            store,
            slug="demo",
            digest=compute_digest(repo, entry.source_globs),
            source_globs=entry.source_globs,
        )
        save_fingerprints(fp_path, store)
        result = check_readme_tree(repo, manifest)
        assert not result.ok
        assert any("Level 3" in err for err in result.errors)


def test_catalog_without_tiers_passes() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        manifest_dir = repo / "docs/readmes"
        manifest_dir.mkdir(parents=True)
        entry = ReadmeEntry(
            slug="tools",
            title="Tools",
            summary="Tool inventory.",
            profile="catalog",
            tier_owner="docs",
            output="docs/readmes/tools.md",
            source_globs=("src/sevn/tools/**",),
            specs=(),
        )
        manifest = ReadmeManifest(version=1, entries=(entry,))
        (repo / "src/sevn/tools").mkdir(parents=True)
        (repo / "src/sevn/tools/a.py").write_text("x = 1\n", encoding="utf-8")
        manifest_dir.joinpath("tools.md").write_text(
            "> **Summary.** ok\n\n| Name | Path | Summary |\n|------|------|---------|\n"
            "| `a` | [`src/sevn/tools/a.py`](src/sevn/tools/a.py) | tool |\n",
            encoding="utf-8",
        )
        fp_path = manifest_dir / "_fingerprints.json"
        store = load_fingerprints(fp_path)
        upsert_entry(
            store,
            slug="tools",
            digest=compute_digest(repo, entry.source_globs),
            source_globs=entry.source_globs,
        )
        save_fingerprints(fp_path, store)
        result = check_readme_tree(repo, manifest)
        assert result.ok, result.errors


def test_index_title_passes_with_generated_comment() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        manifest_dir = repo / "docs/readmes"
        manifest_dir.mkdir(parents=True)
        entry = ReadmeEntry(
            slug="index",
            title="README catalog",
            summary="Generated catalog.",
            profile="index",
            tier_owner="docs",
            output="docs/readmes/INDEX.md",
            source_globs=("docs/readmes/manifest.toml",),
            specs=(),
        )
        manifest = ReadmeManifest(version=1, entries=(entry,))
        manifest_dir.joinpath("demo.md").write_text(
            "> **Summary.** Demo entry.\n",
            encoding="utf-8",
        )
        manifest_dir.joinpath("INDEX.md").write_text(
            "<!-- generated: do not edit by hand -->\n"
            "# README catalog\n\n"
            "> **Summary.** Generated catalog.\n\n"
            "| Slug | Title | Profile | Summary | Status |\n"
            "|------|-------|---------|---------|--------|\n"
            "| [demo](demo.md) | Demo | `freeform` | ok | ok |\n",
            encoding="utf-8",
        )
        fp_path = manifest_dir / "_fingerprints.json"
        store = load_fingerprints(fp_path)
        upsert_entry(
            store,
            slug="index",
            digest=compute_digest(repo, entry.source_globs),
            source_globs=entry.source_globs,
        )
        save_fingerprints(fp_path, store)
        result = check_readme_tree(repo, manifest)
        assert result.ok, result.errors
