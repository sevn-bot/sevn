"""Tests for scaffold quality floor (D10-D13; green after W4)."""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import tempfile
from pathlib import Path

import pytest

from sevn.docs.readme.check import check_readme_tree
from sevn.docs.readme.manifest import ReadmeEntry, ReadmeManifest, get_entry, load_manifest
from sevn.docs.readme.model import format_path_list
from sevn.docs.readme.render import render_readme_markdown
from sevn.docs.readme.scanner import _primary_source_dir

_TURN_SPINE_SNIPPET = "sits in the sevn.bot turn spine"


def _import_truncate_at_sentence():
    for module_name in ("sevn.docs.readme.model", "sevn.docs.readme.scanner"):
        spec = importlib.util.find_spec(module_name)
        if spec is None:
            continue
        module = importlib.import_module(module_name)
        fn = getattr(module, "truncate_at_sentence", None)
        if fn is not None:
            return fn
    pytest.fail("truncate_at_sentence not implemented (green after W4)")


def _subsystem_manifest(
    *,
    slug: str = "storage",
    turn_spine: bool | None = None,
) -> str:
    turn_line = ""
    if turn_spine is True:
        turn_line = "turn_spine = true\n"
    return (
        "version = 1\n"
        "[[readme]]\n"
        f'slug = "{slug}"\n'
        f'title = "{slug.title()}"\n'
        'summary = "Supporting subsystem summary."\n'
        'profile = "subsystem"\n'
        'tier_owner = "docs"\n'
        f'output = "docs/readmes/{slug}.md"\n'
        'source_globs = ["src/sevn/demo/**"]\n'
        f"{turn_line}"
    )


@pytest.mark.xfail(reason="green after W4: turn_spine gate", strict=False)
@pytest.mark.asyncio
async def test_non_turn_spine_entry_omits_turn_spine_paragraph(tmp_path: Path) -> None:
    """D10: non-``turn_spine`` subsystems get the neutral one-liner, not turn-spine prose."""
    manifest_path = tmp_path / "manifest.toml"
    manifest_path.write_text(_subsystem_manifest(turn_spine=None), encoding="utf-8")
    (tmp_path / "src/sevn/demo").mkdir(parents=True)
    (tmp_path / "src/sevn/demo/mod.py").write_text('"""Demo module."""\n', encoding="utf-8")
    manifest = load_manifest(manifest_path)
    markdown = await render_readme_markdown(
        repo_root=tmp_path,
        entry=get_entry(manifest, "storage"),
        manifest=manifest,
    )
    assert _TURN_SPINE_SNIPPET not in markdown
    assert "supporting subsystem" in markdown.lower()


@pytest.mark.xfail(reason="green after W4: turn_spine paragraph present", strict=False)
@pytest.mark.asyncio
async def test_turn_spine_entry_includes_turn_spine_paragraph(tmp_path: Path) -> None:
    """D10: ``turn_spine = true`` retains the turn-spine paragraph."""
    manifest_path = tmp_path / "manifest.toml"
    manifest_path.write_text(_subsystem_manifest(turn_spine=True), encoding="utf-8")
    (tmp_path / "src/sevn/demo").mkdir(parents=True)
    (tmp_path / "src/sevn/demo/mod.py").write_text('"""Demo module."""\n', encoding="utf-8")
    manifest = load_manifest(manifest_path)
    entry = get_entry(manifest, "storage")
    assert getattr(entry, "turn_spine", False) is True
    markdown = await render_readme_markdown(
        repo_root=tmp_path,
        entry=entry,
        manifest=manifest,
    )
    assert _TURN_SPINE_SNIPPET in markdown


@pytest.mark.xfail(reason="green after W4: truncate_at_sentence helper", strict=False)
@pytest.mark.parametrize(
    ("text", "limit", "expected"),
    [
        ("Hello world. More text here.", 15, "Hello world."),
        ("No sentence boundary at all", 12, ""),
        (
            "Covers items (incl. foo, bar) and more. Extra.",
            40,
            "Covers items (incl. foo, bar) and more.",
        ),
    ],
)
def test_truncate_at_sentence(text: str, limit: int, expected: str) -> None:
    """D11: sentence-boundary truncation with abbreviation-safe ``(incl.`` handling."""
    truncate_at_sentence = _import_truncate_at_sentence()
    assert truncate_at_sentence(text, limit) == expected


@pytest.mark.xfail(reason="green after W4: format_path_list true remainder", strict=False)
def test_format_path_list_true_remainder_for_114_paths() -> None:
    """D12: ``format_path_list`` reports ``and 110 more`` for 114 paths at cap 4."""
    paths = [f"src/sevn/gateway/m{i}.py" for i in range(114)]
    rendered = format_path_list(paths, max_items=4)
    assert "and 110 more" in rendered


@pytest.mark.xfail(reason="green after W4: multi-root primary source dir", strict=False)
def test_primary_source_dir_multi_root_deepest_common() -> None:
    """D12: multi-root globs derive deepest common directory across all roots."""
    result = _primary_source_dir(("src/sevn/gateway/**", "infra/**"))
    assert result in {"src/sevn/", "src/"}


@pytest.mark.xfail(reason="green after W4: docstring inventory without quotes", strict=False)
@pytest.mark.asyncio
async def test_inventory_lines_exclude_raw_docstring_quotes(tmp_path: Path) -> None:
    """D12: module inventory uses docstring first sentence without raw ``\"\"\"``."""
    manifest_path = tmp_path / "manifest.toml"
    manifest_path.write_text(_subsystem_manifest(), encoding="utf-8")
    mod = tmp_path / "src/sevn/demo/mod.py"
    mod.parent.mkdir(parents=True)
    mod.write_text('"""First sentence only."""\n\nclass Foo: pass\n', encoding="utf-8")
    manifest = load_manifest(manifest_path)
    markdown = await render_readme_markdown(
        repo_root=tmp_path,
        entry=get_entry(manifest, "storage"),
        manifest=manifest,
    )
    assert '"""' not in markdown
    assert "First sentence only." in markdown


@pytest.mark.xfail(reason="green after W4: Package init heading", strict=False)
@pytest.mark.asyncio
async def test_init_module_heading_renders_package_init(tmp_path: Path) -> None:
    """D12: ``__init__.py`` sections render as ``Package init``."""
    manifest_path = tmp_path / "manifest.toml"
    manifest_path.write_text(_subsystem_manifest(), encoding="utf-8")
    pkg = tmp_path / "src/sevn/demo"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text('"""Package docstring sentence."""\n', encoding="utf-8")
    manifest = load_manifest(manifest_path)
    markdown = await render_readme_markdown(
        repo_root=tmp_path,
        entry=get_entry(manifest, "storage"),
        manifest=manifest,
    )
    assert "Package init" in markdown
    assert "__init__.py" in markdown


@pytest.mark.xfail(reason="green after W4: PLACEHOLDER narrowed for symbols", strict=False)
def test_check_no_placeholder_warning_for_transcribe_symbol() -> None:
    """D13: symbol names like ``transcribe_placeholder`` must not trigger PLACEHOLDER warnings."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        manifest_dir = repo / "docs/readmes"
        manifest_dir.mkdir(parents=True)
        entry = ReadmeEntry(
            slug="voice",
            title="Voice",
            summary="Voice subsystem.",
            profile="subsystem",
            tier_owner="voice",
            output="docs/readmes/voice.md",
            source_globs=("src/sevn/voice/**",),
            specs=(),
        )
        manifest = ReadmeManifest(version=1, entries=(entry,))
        (repo / "src/sevn/voice").mkdir(parents=True)
        (repo / "src/sevn/voice/stt.py").write_text(
            "async def transcribe_placeholder() -> str:\n    return ''\n",
            encoding="utf-8",
        )
        body = (
            "> **Summary.** Voice.\n\n"
            "## Level 1 — Overview\n\nok\n\n"
            "## Level 2 — How it works\n\nok\n\n"
            "## Level 3 — Deep dive\n\n"
            "- `transcribe_placeholder` — see `src/sevn/voice/stt.py`\n\n"
            "## References\n"
        )
        manifest_dir.joinpath("voice.md").write_text(body, encoding="utf-8")
        asyncio.run(_stamp_fingerprint(repo, entry))
        result = check_readme_tree(repo, manifest)
        assert not any("PLACEHOLDER" in w for w in result.warnings)


def test_check_warns_on_image_line_placeholder() -> None:
    """D13: image/asset lines containing PLACEHOLDER still warn."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        manifest_dir = repo / "docs/readmes"
        manifest_dir.mkdir(parents=True)
        entry = ReadmeEntry(
            slug="root",
            title="Root",
            summary="Root README.",
            profile="root",
            tier_owner="docs",
            output="README.md",
            source_globs=("docs/readmes/manifest.toml",),
            specs=(),
        )
        manifest = ReadmeManifest(version=1, entries=(entry,))
        repo.joinpath("README.md").write_text(
            "> **Summary.** Root.\n\n![hero PLACEHOLDER](docs/brand/assets/hero.png)\n",
            encoding="utf-8",
        )
        asyncio.run(_stamp_fingerprint(repo, entry))
        result = check_readme_tree(repo, manifest)
        assert any("PLACEHOLDER" in w for w in result.warnings)


async def _stamp_fingerprint(repo: Path, entry: ReadmeEntry) -> None:
    from sevn.docs.readme.fingerprint import (
        compute_digest,
        default_fingerprints_path,
        load_fingerprints,
        save_fingerprints,
        upsert_entry,
    )

    fp_path = default_fingerprints_path(repo)
    fp_path.parent.mkdir(parents=True, exist_ok=True)
    store = load_fingerprints(fp_path)
    upsert_entry(
        store,
        slug=entry.slug,
        digest=compute_digest(repo, entry.source_globs),
        source_globs=entry.source_globs,
    )
    save_fingerprints(fp_path, store)
