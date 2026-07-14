"""Generator claim contracts (D1-D6; W2 generator core)."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from sevn.docs.readme.manifest import get_entry, load_manifest
from sevn.docs.readme.render import render_readme_markdown
from sevn.docs.readme.scanner import _primary_source_dir, extract_module_symbols

_KEYS_NEVER_LOAD = "keys never load in the gateway process"
_SUPPORTING_SUBSYSTEM = "supporting subsystem"


def _strip_inline_code(text: str) -> str:
    fn = getattr(importlib.import_module("sevn.docs.readme.prose"), "strip_inline_code", None)
    assert fn is not None, "strip_inline_code not implemented (green after W2)"
    return fn(text)


def _subsystem_manifest(
    *,
    slug: str,
    turn_spine: bool = False,
    provider_keys_via_proxy: bool | None = None,
    source_globs: tuple[str, ...] = ("src/sevn/demo/**",),
) -> str:
    lines = [
        "version = 1",
        "[[readme]]",
        f'slug = "{slug}"',
        f'title = "{slug.title()}"',
        'summary = "Demo subsystem for generator claim tests."',
        'profile = "subsystem"',
        'tier_owner = "docs"',
        f'output = "docs/readmes/{slug}.md"',
        f"source_globs = [{', '.join(repr(g) for g in source_globs)}]",
    ]
    if turn_spine:
        lines.append("turn_spine = true")
    if provider_keys_via_proxy is True:
        lines.append("provider_keys_via_proxy = true")
    return "\n".join(lines) + "\n"


def _write_demo_module(root: Path, rel: str, *, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


@pytest.mark.asyncio
async def test_turn_spine_body_omits_keys_never_load_claim(tmp_path: Path) -> None:
    """D1: ``turn_spine=true`` Level 2 must not hardcode the false key-location claim."""
    manifest_path = tmp_path / "manifest.toml"
    manifest_path.write_text(_subsystem_manifest(slug="gateway", turn_spine=True), encoding="utf-8")
    _write_demo_module(
        tmp_path,
        "src/sevn/demo/mod.py",
        body='"""Gateway demo module."""\n\nclass Router:\n    def route(self) -> None:\n        pass\n',
    )
    manifest = load_manifest(manifest_path)
    markdown = await render_readme_markdown(
        repo_root=tmp_path,
        entry=get_entry(manifest, "gateway"),
        manifest=manifest,
    )
    assert _KEYS_NEVER_LOAD not in markdown.lower()


@pytest.mark.asyncio
async def test_provider_keys_via_proxy_emits_brokered_line_only_when_set(
    tmp_path: Path,
) -> None:
    """D1: brokered provider-key prose appears only when ``provider_keys_via_proxy`` is true."""
    manifest_path = tmp_path / "manifest.toml"
    manifest_path.write_text(
        _subsystem_manifest(slug="voice", turn_spine=True, provider_keys_via_proxy=True),
        encoding="utf-8",
    )
    _write_demo_module(tmp_path, "src/sevn/demo/mod.py", body='"""Voice demo."""\n')
    manifest = load_manifest(manifest_path)
    voice = await render_readme_markdown(
        repo_root=tmp_path,
        entry=get_entry(manifest, "voice"),
        manifest=manifest,
    )
    brokered_clause = "provider api calls are brokered by the egress proxy"
    assert brokered_clause in voice.lower()

    secrets_manifest = tmp_path / "secrets.toml"
    secrets_manifest.write_text(
        _subsystem_manifest(slug="secrets", turn_spine=False),
        encoding="utf-8",
    )
    manifest2 = load_manifest(secrets_manifest)
    secrets = await render_readme_markdown(
        repo_root=tmp_path,
        entry=get_entry(manifest2, "secrets"),
        manifest=manifest2,
    )
    assert _KEYS_NEVER_LOAD not in secrets.lower()


@pytest.mark.asyncio
async def test_turn_spine_false_renders_module_graph_not_supporting_one_liner(
    tmp_path: Path,
) -> None:
    """D2: ``turn_spine=false`` Level 2 derives a real module-graph summary."""
    manifest_path = tmp_path / "manifest.toml"
    manifest_path.write_text(
        _subsystem_manifest(slug="storage", turn_spine=False), encoding="utf-8"
    )
    _write_demo_module(
        tmp_path,
        "src/sevn/demo/migrate.py",
        body='"""Migration helpers."""\n\ndef migrate() -> None:\n    pass\n',
    )
    _write_demo_module(
        tmp_path,
        "src/sevn/demo/sqlite.py",
        body='"""SQLite connection layer."""\n\ndef connect() -> None:\n    pass\n',
    )
    manifest = load_manifest(manifest_path)
    markdown = await render_readme_markdown(
        repo_root=tmp_path,
        entry=get_entry(manifest, "storage"),
        manifest=manifest,
    )
    l2_start = markdown.lower().find("level 2")
    l3_start = markdown.lower().find("level 3")
    level2 = markdown[l2_start:l3_start] if l2_start >= 0 and l3_start > l2_start else markdown
    assert _SUPPORTING_SUBSYSTEM not in level2.lower()
    assert "migrate" in level2.lower() or "sqlite" in level2.lower()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Use `foo` here.", "Use foo here."),
        ("Already ''doubled'' quotes.", "Already doubled quotes."),
        ("No ``double`` backticks.", "No double backticks."),
        ("Plain text.", "Plain text."),
    ],
)
def test_strip_inline_code_parametrized(raw: str, expected: str) -> None:
    """D3: inline-code stripping never doubles quotes."""
    assert _strip_inline_code(raw) == expected
    assert "''" not in _strip_inline_code(raw)


@pytest.mark.asyncio
async def test_skills_catalog_joins_folded_description_without_marker(tmp_path: Path) -> None:
    """D4: skills catalog joins ``>-`` folded descriptions without leaking the marker."""
    bundled = tmp_path / "src/sevn/data/bundled_skills/core/fold-demo"
    bundled.mkdir(parents=True)
    (bundled / "SKILL.md").write_text(
        "---\n"
        "name: fold-demo\n"
        "description: >-\n"
        "  Line one of description.\n"
        "  Line two continues here.\n"
        "---\n\n"
        "# fold-demo\n",
        encoding="utf-8",
    )
    (tmp_path / "src/sevn/skills").mkdir(parents=True)
    (tmp_path / "src/sevn/skills/loader.py").write_text(
        '"""Runtime loader."""\n\ndef load() -> None:\n    pass\n',
        encoding="utf-8",
    )
    manifest_path = tmp_path / "docs/readmes/manifest.toml"
    manifest_path.parent.mkdir(parents=True)
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
    manifest = load_manifest(manifest_path)
    markdown = await render_readme_markdown(
        repo_root=tmp_path,
        entry=get_entry(manifest, "skills"),
        manifest=manifest,
    )
    assert "Line one of description." in markdown
    assert "Line two continues here." in markdown
    assert ">-" not in markdown


@pytest.mark.asyncio
async def test_twelve_file_subsystem_renders_symbols_for_modules_eleven_and_twelve(
    tmp_path: Path,
) -> None:
    """D5: modules 11-12 render public symbols instead of bare ``See `X``` stubs."""
    manifest_path = tmp_path / "manifest.toml"
    manifest_path.write_text(_subsystem_manifest(slug="wide", turn_spine=False), encoding="utf-8")
    for idx in range(12):
        _write_demo_module(
            tmp_path,
            f"src/sevn/demo/mod_{idx:02d}.py",
            body=(
                f'"""Module {idx} docstring sentence."""\n\n'
                f"def public_fn_{idx}() -> None:\n"
                f'    """Public entry {idx}."""\n'
                f"    pass\n"
            ),
        )
    manifest = load_manifest(manifest_path)
    markdown = await render_readme_markdown(
        repo_root=tmp_path,
        entry=get_entry(manifest, "wide"),
        manifest=manifest,
    )
    l3_start = markdown.lower().find("level 3")
    level3 = markdown[l3_start:] if l3_start >= 0 else markdown
    assert "mod_10.py" in level3
    assert "mod_11.py" in level3
    assert "public_fn_10" in level3 or "`public_fn_10`" in level3
    assert "public_fn_11" in level3 or "`public_fn_11`" in level3
    assert "See `src/sevn/demo/mod_10.py`" not in level3
    assert "See `src/sevn/demo/mod_11.py`" not in level3


def test_multi_root_glob_source_badge_uses_first_concrete_package_root() -> None:
    """D6: multi-root globs badge the first concrete package root, not ``src/sevn/``."""
    globs = ("src/sevn/secrets/**", "src/sevn/security/secrets/**")
    result = _primary_source_dir(globs)
    assert result == "src/sevn/secrets/"
    assert result != "src/sevn/"


def test_extract_module_symbols_honors_twelve_file_window(tmp_path: Path) -> None:
    """D5: ``extract_module_symbols`` scans twelve modules when twelve are supplied."""
    for idx in range(12):
        _write_demo_module(
            tmp_path,
            f"src/sevn/demo/mod_{idx:02d}.py",
            body=f"def fn_{idx}() -> None:\n    pass\n",
        )
    files = [f"src/sevn/demo/mod_{idx:02d}.py" for idx in range(12)]
    symbols = extract_module_symbols(tmp_path, files)
    assert len(symbols) == 12
