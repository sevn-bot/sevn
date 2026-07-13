"""Tests for file-relative link emission in rendered READMEs (D6/D8; green after W3)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sevn.docs.readme.manifest import get_entry, load_manifest
from sevn.docs.readme.render import render_readme_markdown, write_readme


def _seed_link_repo(repo: Path) -> Path:
    """Minimal repo with root, index, gateway, and a tracked spec file."""
    (repo / "pyproject.toml").write_text('name = "sevn"\n', encoding="utf-8")
    (repo / ".git").mkdir()
    (repo / "README.md").write_text("# Root\n", encoding="utf-8")
    spec = repo / "about-sevn.bot/specs/17-gateway.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# Gateway spec\n\nGateway normative spec.\n", encoding="utf-8")
    gateway_src = repo / "src/sevn/gateway"
    gateway_src.mkdir(parents=True)
    (gateway_src / "agent_turn.py").write_text(
        '"""Gateway turn spine."""\n',
        encoding="utf-8",
    )
    manifest_dir = repo / "docs/readmes"
    manifest_dir.mkdir(parents=True)
    manifest_path = manifest_dir / "manifest.toml"
    manifest_path.write_text(
        "version = 1\n"
        "[[readme]]\n"
        'slug = "root"\n'
        'title = "sevn.bot"\n'
        'summary = "Root README."\n'
        'profile = "root"\n'
        'tier_owner = "docs"\n'
        'output = "README.md"\n'
        'source_globs = ["docs/readmes/manifest.toml"]\n'
        "[[readme]]\n"
        'slug = "gateway"\n'
        'title = "Gateway"\n'
        'summary = "Gateway subsystem."\n'
        'profile = "subsystem"\n'
        'tier_owner = "gateway"\n'
        'output = "docs/readmes/gateway.md"\n'
        'source_globs = ["src/sevn/gateway/**"]\n'
        'specs = ["about-sevn.bot/specs/17-gateway.md"]\n'
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
    return manifest_path


@pytest.mark.xfail(reason="green after W3: INDEX gateway row link", strict=False)
@pytest.mark.asyncio
async def test_index_gateway_row_links_gateway_md() -> None:
    """D6: INDEX row for ``gateway`` uses ``gateway.md`` (same directory)."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        manifest_path = _seed_link_repo(repo)
        manifest = load_manifest(manifest_path)
        await write_readme(
            repo_root=repo,
            entry=get_entry(manifest, "gateway"),
            manifest=manifest,
        )
        index_md = await render_readme_markdown(
            repo_root=repo,
            entry=get_entry(manifest, "index"),
            manifest=manifest,
        )
        assert "[gateway](gateway.md)" in index_md
        assert "docs/readmes/gateway.md" not in index_md


@pytest.mark.xfail(reason="green after W3: INDEX root row link", strict=False)
@pytest.mark.asyncio
async def test_index_root_row_links_repo_readme() -> None:
    """D6: INDEX row for ``root`` uses ``../../README.md`` from ``docs/readmes/``."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        manifest_path = _seed_link_repo(repo)
        manifest = load_manifest(manifest_path)
        await write_readme(
            repo_root=repo,
            entry=get_entry(manifest, "root"),
            manifest=manifest,
        )
        index_md = await render_readme_markdown(
            repo_root=repo,
            entry=get_entry(manifest, "index"),
            manifest=manifest,
        )
        assert "[root](../../README.md)" in index_md or "[sevn.bot](../../README.md)" in index_md


@pytest.mark.xfail(reason="green after W3: subsystem index badge link", strict=False)
@pytest.mark.asyncio
async def test_subsystem_index_badge_links_index_md() -> None:
    """D6: subsystem INDEX badge href is ``INDEX.md`` (not ``docs/readmes/INDEX.md``)."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        manifest_path = _seed_link_repo(repo)
        manifest = load_manifest(manifest_path)
        gateway_md = await render_readme_markdown(
            repo_root=repo,
            entry=get_entry(manifest, "gateway"),
            manifest=manifest,
        )
        assert "[index-link]: INDEX.md" in gateway_md
        assert "docs/readmes/INDEX.md" not in gateway_md


@pytest.mark.xfail(reason="green after W3: subsystem source badge link", strict=False)
@pytest.mark.asyncio
async def test_subsystem_source_badge_links_relative_src() -> None:
    """D6: subsystem source badge href is file-relative under ``src/sevn/``."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        manifest_path = _seed_link_repo(repo)
        manifest = load_manifest(manifest_path)
        gateway_md = await render_readme_markdown(
            repo_root=repo,
            entry=get_entry(manifest, "gateway"),
            manifest=manifest,
        )
        assert "[source-link]: ../../src/sevn/gateway/" in gateway_md


@pytest.mark.xfail(reason="green after W3: References spec links", strict=False)
@pytest.mark.asyncio
async def test_subsystem_references_use_about_specs_relative() -> None:
    """D8: References list links ``../../about-sevn.bot/specs/…`` from subsystem output dir."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        manifest_path = _seed_link_repo(repo)
        manifest = load_manifest(manifest_path)
        gateway_md = await render_readme_markdown(
            repo_root=repo,
            entry=get_entry(manifest, "gateway"),
            manifest=manifest,
        )
        assert "../../about-sevn.bot/specs/17-gateway.md" in gateway_md
