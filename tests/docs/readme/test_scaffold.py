"""Tests for README scaffold (make readme-scaffold)."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from sevn.docs.readme.check import check_readme_tree
from sevn.docs.readme.manifest import ReadmeEntry, ReadmeManifest, get_entry
from sevn.docs.readme.render import write_readme
from sevn.docs.readme.scaffold import scaffold_readme_tree


def _subsystem_manifest() -> ReadmeManifest:
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
    manifest = _subsystem_manifest()
    entry = get_entry(manifest, "demo")
    (repo_root / "src/sevn/demo").mkdir(parents=True)
    (repo_root / "src/sevn/demo/a.py").write_text(
        "class Foo:\n    def bar(self): pass\n", encoding="utf-8"
    )
    await write_readme(repo_root=repo_root, entry=entry, manifest=manifest)


def test_scaffold_regenerates_missing_readme() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        manifest = _subsystem_manifest()
        (repo / "src/sevn/demo").mkdir(parents=True)
        (repo / "src/sevn/demo/a.py").write_text("x = 1\n", encoding="utf-8")
        count = scaffold_readme_tree(repo, manifest)
        assert count >= 1
        assert (repo / "docs/readmes/demo.md").is_file()


def test_scaffold_fixes_stale_fingerprint() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        manifest = _subsystem_manifest()
        asyncio.run(_write_demo(repo))
        (repo / "src/sevn/demo/a.py").write_text("x = 2\n", encoding="utf-8")
        assert not check_readme_tree(repo, manifest).ok
        scaffold_readme_tree(repo, manifest)
        assert check_readme_tree(repo, manifest).ok


def _curated_manifest() -> ReadmeManifest:
    entry = ReadmeEntry(
        slug="hand",
        title="Hand",
        summary="Hand-authored README.",
        profile="freeform",
        tier_owner="docs",
        output="docs/readmes/hand.md",
        source_globs=("src/sevn/hand/**",),
        specs=(),
        curated=True,
    )
    return ReadmeManifest(version=1, entries=(entry,))


def test_scaffold_curated_stamps_stale_without_body_change() -> None:
    """Curated slugs: scaffold stamps fingerprint when stale; body stays byte-identical."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        manifest = _curated_manifest()
        hand_src = repo / "src/sevn/hand"
        hand_src.mkdir(parents=True)
        hand_py = hand_src / "mod.py"
        hand_py.write_text("v = 1\n", encoding="utf-8")
        readme_path = repo / "docs/readmes/hand.md"
        readme_path.parent.mkdir(parents=True)
        body = "<!-- curated: hand-authored body -->\n> **Summary.** Hand body must stay byte-stable.\n"
        readme_path.write_text(body, encoding="utf-8")
        hand_py.write_text("v = 2\n", encoding="utf-8")
        assert not check_readme_tree(repo, manifest).ok
        count = scaffold_readme_tree(repo, manifest)
        assert count == 1
        assert readme_path.read_text(encoding="utf-8") == body
        assert check_readme_tree(repo, manifest).ok
