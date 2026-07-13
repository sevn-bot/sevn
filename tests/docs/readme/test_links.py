"""Tests for README relative link validation."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sevn.docs.readme.links import validate_markdown_links


def test_relative_link_resolves() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        readme = repo / "docs/readmes/demo.md"
        readme.parent.mkdir(parents=True)
        readme.write_text("# Demo\n", encoding="utf-8")
        (repo / "README.md").write_text("# Root\n", encoding="utf-8")
        errors = validate_markdown_links("[root](../../README.md)", readme, repo)
        assert not errors


def test_broken_link_fails() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        readme = repo / "docs/readmes/demo.md"
        readme.parent.mkdir(parents=True)
        readme.write_text("# Demo\n", encoding="utf-8")
        errors = validate_markdown_links("[missing](../missing.md)", readme, repo)
        assert errors


def test_external_links_skipped() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        readme = repo / "docs/readmes/demo.md"
        readme.parent.mkdir(parents=True)
        readme.write_text("# Demo\n", encoding="utf-8")
        errors = validate_markdown_links("[ext](https://example.com)", readme, repo)
        assert not errors


@pytest.mark.xfail(reason="green after W3: repo-root fallback removed", strict=False)
def test_root_relative_link_from_nested_readme_fails() -> None:
    """D7: links resolvable only from repo root fail when emitted from nested READMEs."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        readme = repo / "docs/readmes/demo.md"
        readme.parent.mkdir(parents=True)
        readme.write_text("# Demo\n", encoding="utf-8")
        schema = repo / "infra/sevn.schema.json"
        schema.parent.mkdir(parents=True)
        schema.write_text("{}\n", encoding="utf-8")
        errors = validate_markdown_links(
            "[schema](infra/sevn.schema.json)",
            readme,
            repo,
        )
        assert errors


def test_local_only_tree_skip_when_absent() -> None:
    """D7: ``_LOCAL_ONLY_TREES`` links are skipped when the tree is absent on CI clones."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        readme = repo / "docs/readmes/demo.md"
        readme.parent.mkdir(parents=True)
        readme.write_text("# Demo\n", encoding="utf-8")
        errors = validate_markdown_links(
            "[spec](specs/17-gateway.md)",
            readme,
            repo,
        )
        assert not errors


@pytest.mark.xfail(reason="green after W3: about-sevn.bot spec paths validate", strict=False)
@pytest.mark.asyncio
async def test_manifest_about_sevn_bot_spec_path_validates(tmp_path: Path) -> None:
    """D8: rendered subsystem README with ``about-sevn.bot/specs/…`` passes check."""
    from sevn.docs.readme.check import check_readme_tree
    from sevn.docs.readme.manifest import get_entry, load_manifest
    from sevn.docs.readme.render import write_readme

    spec = tmp_path / "about-sevn.bot/specs/17-gateway.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# Gateway\n", encoding="utf-8")
    (tmp_path / "src/sevn/demo").mkdir(parents=True)
    (tmp_path / "src/sevn/demo/a.py").write_text("x = 1\n", encoding="utf-8")
    manifest_dir = tmp_path / "docs/readmes"
    manifest_dir.mkdir(parents=True)
    manifest_dir.joinpath("manifest.toml").write_text(
        "version = 1\n"
        "[[readme]]\n"
        'slug = "demo"\n'
        'title = "Demo"\n'
        'summary = "Demo summary."\n'
        'profile = "subsystem"\n'
        'tier_owner = "docs"\n'
        'output = "docs/readmes/demo.md"\n'
        'source_globs = ["src/sevn/demo/**"]\n'
        'specs = ["about-sevn.bot/specs/17-gateway.md"]\n',
        encoding="utf-8",
    )
    manifest = load_manifest(manifest_dir / "manifest.toml")
    await write_readme(repo_root=tmp_path, entry=get_entry(manifest, "demo"), manifest=manifest)
    result = check_readme_tree(tmp_path, manifest)
    assert result.ok, result.errors
