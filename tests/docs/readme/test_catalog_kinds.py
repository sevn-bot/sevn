"""Tests for catalog manifest kinds (D14; green after W5)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sevn.docs.readme.manifest import get_entry, load_manifest
from sevn.docs.readme.render import render_readme_markdown


def _write_modules_catalog_repo(repo: Path, *, module_count: int) -> Path:
    tools_dir = repo / "src/sevn/tools"
    tools_dir.mkdir(parents=True)
    for idx in range(module_count):
        mod = tools_dir / f"tool_{idx:03d}.py"
        mod.write_text(
            f'"""Docstring summary for tool {idx}."""\n\n'
            f"def run_{idx}() -> None:\n"
            f'    """Run tool {idx}."""\n'
            f"    pass\n",
            encoding="utf-8",
        )
    manifest_dir = repo / "docs/readmes"
    manifest_dir.mkdir(parents=True)
    manifest_path = manifest_dir / "manifest.toml"
    manifest_path.write_text(
        "version = 1\n"
        "[[readme]]\n"
        'slug = "tools"\n'
        'title = "Tools"\n'
        'summary = "Tool inventory."\n'
        'profile = "catalog"\n'
        'tier_owner = "tools"\n'
        'output = "docs/readmes/tools.md"\n'
        'source_globs = ["src/sevn/tools/**"]\n'
        'catalog = "modules"\n',
        encoding="utf-8",
    )
    return manifest_path


def _write_skills_catalog_repo(repo: Path) -> Path:
    bundled = repo / "src/sevn/data/bundled_skills/core/graphify"
    bundled.mkdir(parents=True)
    (bundled / "SKILL.md").write_text(
        "---\n"
        "name: graphify\n"
        "description: Build knowledge graphs from code. Extended description sentence.\n"
        "---\n\n"
        "# graphify\n",
        encoding="utf-8",
    )
    skills_runtime = repo / "src/sevn/skills"
    skills_runtime.mkdir(parents=True)
    (skills_runtime / "loader.py").write_text(
        '"""Skill loader runtime module."""\n\ndef load() -> None:\n    pass\n',
        encoding="utf-8",
    )
    manifest_dir = repo / "docs/readmes"
    manifest_dir.mkdir(parents=True)
    manifest_path = manifest_dir / "manifest.toml"
    manifest_path.write_text(
        "version = 1\n"
        "[[readme]]\n"
        'slug = "skills"\n'
        'title = "Skills"\n'
        'summary = "Skills inventory."\n'
        'profile = "catalog"\n'
        'tier_owner = "skills"\n'
        'output = "docs/readmes/skills.md"\n'
        'source_globs = ["src/sevn/data/bundled_skills/**", "src/sevn/skills/**"]\n'
        'catalog = "skills"\n',
        encoding="utf-8",
    )
    return manifest_path


@pytest.mark.asyncio
async def test_modules_catalog_lists_overflow_with_true_remainder() -> None:
    """D14: modules kind over cap emits ``+N more modules`` with the true remainder."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        manifest_path = _write_modules_catalog_repo(repo, module_count=205)
        manifest = load_manifest(manifest_path)
        markdown = await render_readme_markdown(
            repo_root=repo,
            entry=get_entry(manifest, "tools"),
            manifest=manifest,
        )
        assert "+5 more modules" in markdown


@pytest.mark.asyncio
async def test_modules_catalog_uses_docstring_first_sentence() -> None:
    """D14: catalog row summaries prefer module docstring first sentence."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        manifest_path = _write_modules_catalog_repo(repo, module_count=3)
        manifest = load_manifest(manifest_path)
        markdown = await render_readme_markdown(
            repo_root=repo,
            entry=get_entry(manifest, "tools"),
            manifest=manifest,
        )
        assert "Docstring summary for tool 0." in markdown
        assert "Module `src/sevn/tools/tool_000.py`." not in markdown


@pytest.mark.asyncio
async def test_skills_catalog_renders_frontmatter_and_runtime_tables() -> None:
    """D14: skills kind renders bundled SKILL.md table plus ``src/sevn/skills/**`` modules."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        manifest_path = _write_skills_catalog_repo(repo)
        manifest = load_manifest(manifest_path)
        markdown = await render_readme_markdown(
            repo_root=repo,
            entry=get_entry(manifest, "skills"),
            manifest=manifest,
        )
        assert "graphify" in markdown
        assert "Build knowledge graphs from code." in markdown
        assert "src/sevn/skills/loader.py" in markdown
