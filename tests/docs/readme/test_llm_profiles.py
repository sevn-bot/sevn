"""Tests for LLM profile wiring and root README content (D15/D16; green after W6)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from sevn.docs.readme.brand import load_root_intro_lines
from sevn.docs.readme.manifest import ReadmeEntry, ReadmeManifest
from sevn.docs.readme.providers import ReadmeProviderConfig
from sevn.docs.readme.render import render_readme_markdown
from sevn.docs.readme.scanner import scan_repo_context

_LIVE_CI_BADGE = "https://github.com/sevn-bot/sevn/actions/workflows/ci.yml/badge.svg"


@dataclass
class RecordingProvider:
    """Capture ``render_section`` prompt names for profile wiring tests."""

    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def render_section(self, prompt_name: str, variables: dict[str, Any]) -> str:
        self.calls.append((prompt_name, variables))
        return f"polished:{prompt_name}"


def _llm_config() -> ReadmeProviderConfig:
    return ReadmeProviderConfig(offline=False, proxy_base_url="http://proxy.test")


def _guide_entry() -> ReadmeEntry:
    return ReadmeEntry(
        slug="onboarding",
        title="Onboarding",
        summary="Operator onboarding guide.",
        profile="guide",
        tier_owner="onboarding",
        output="docs/readmes/onboarding.md",
        source_globs=("src/sevn/onboarding/**",),
        specs=("about-sevn.bot/specs/22-onboarding.md",),
    )


def _catalog_entry() -> ReadmeEntry:
    return ReadmeEntry(
        slug="tools",
        title="Tools",
        summary="Tool inventory.",
        profile="catalog",
        tier_owner="tools",
        output="docs/readmes/tools.md",
        source_globs=("src/sevn/tools/**",),
        specs=(),
    )


def _root_entry() -> ReadmeEntry:
    return ReadmeEntry(
        slug="root",
        title="sevn.bot",
        summary="Root README.",
        profile="root",
        tier_owner="docs",
        output="README.md",
        source_globs=("docs/readmes/manifest.toml",),
        specs=(),
    )


def _index_entry() -> ReadmeEntry:
    return ReadmeEntry(
        slug="index",
        title="README catalog",
        summary="Generated catalog.",
        profile="index",
        tier_owner="docs",
        output="docs/readmes/INDEX.md",
        source_globs=("docs/readmes/manifest.toml",),
        specs=(),
    )


@pytest.mark.xfail(reason="green after W6: LLM guide-steps prompt", strict=False)
@pytest.mark.asyncio
async def test_llm_guide_calls_guide_steps_prompt(tmp_path: Path) -> None:
    """D15: ``guide`` profile with LLM calls ``guide-steps`` section provider."""
    (tmp_path / "src/sevn/onboarding").mkdir(parents=True)
    (tmp_path / "src/sevn/onboarding/wizard.py").write_text("x = 1\n", encoding="utf-8")
    provider = RecordingProvider()
    await render_readme_markdown(
        repo_root=tmp_path,
        entry=_guide_entry(),
        provider=provider,
        config=_llm_config(),
    )
    prompt_names = [name for name, _ in provider.calls]
    assert "guide-steps" in prompt_names


@pytest.mark.xfail(reason="green after W6: LLM root prompts", strict=False)
@pytest.mark.asyncio
async def test_llm_root_calls_valueprop_and_highlights(tmp_path: Path) -> None:
    """D15: ``root`` profile with LLM calls ``root-valueprop`` and ``highlights``."""
    (tmp_path / "docs/readmes").mkdir(parents=True)
    (tmp_path / "docs/readmes/manifest.toml").write_text("version = 1\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "sevn"\nversion = "0.0.1"\n', encoding="utf-8"
    )
    provider = RecordingProvider()
    manifest = ReadmeManifest(version=1, entries=(_root_entry(), _index_entry()))
    await render_readme_markdown(
        repo_root=tmp_path,
        entry=_root_entry(),
        provider=provider,
        config=_llm_config(),
        manifest=manifest,
    )
    prompt_names = [name for name, _ in provider.calls]
    assert "root-valueprop" in prompt_names
    assert "highlights" in prompt_names


@pytest.mark.xfail(reason="green after W6: LLM catalog-table prompt", strict=False)
@pytest.mark.asyncio
async def test_llm_catalog_calls_catalog_table_prompt(tmp_path: Path) -> None:
    """D15: ``catalog`` profile with LLM calls ``catalog-table`` section provider."""
    tools = tmp_path / "src/sevn/tools"
    tools.mkdir(parents=True)
    (tools / "a.py").write_text("x = 1\n", encoding="utf-8")
    provider = RecordingProvider()
    await render_readme_markdown(
        repo_root=tmp_path,
        entry=_catalog_entry(),
        provider=provider,
        config=_llm_config(),
    )
    prompt_names = [name for name, _ in provider.calls]
    assert "catalog-table" in prompt_names


@pytest.mark.asyncio
async def test_llm_index_never_calls_section_provider(tmp_path: Path) -> None:
    """D15: ``index`` profile stays offline-only even when LLM config is set."""
    manifest_dir = tmp_path / "docs/readmes"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "demo.md").write_text("> **Summary.** Demo.\n", encoding="utf-8")
    provider = RecordingProvider()
    manifest = ReadmeManifest(version=1, entries=(_index_entry(),))
    await render_readme_markdown(
        repo_root=tmp_path,
        entry=_index_entry(),
        provider=provider,
        config=_llm_config(),
        manifest=manifest,
    )
    assert provider.calls == []


@pytest.mark.xfail(reason="green after W6: value_prop from root-intro.toml", strict=False)
def test_root_scan_includes_value_prop_from_brand_toml(tmp_path: Path) -> None:
    """D16: root scan context loads ``value_prop`` from ``docs/brand/root-intro.toml``."""
    brand_dir = tmp_path / "docs/brand"
    brand_dir.mkdir(parents=True)
    (brand_dir / "root-intro.toml").write_text(
        'value_prop = "Custom value proposition for tests."\nlines = ["Intro line one."]\n',
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "sevn"\ndescription = "fallback"\n', encoding="utf-8"
    )
    _ = load_root_intro_lines(tmp_path)
    scan = scan_repo_context(tmp_path, _root_entry())
    assert scan.get("value_prop") == "Custom value proposition for tests."


@pytest.mark.xfail(reason="green after W6: live CI badge URL", strict=False)
@pytest.mark.asyncio
async def test_root_render_contains_live_ci_badge(tmp_path: Path) -> None:
    """D16: rendered root README uses the live GitHub Actions badge URL."""
    (tmp_path / "docs/readmes").mkdir(parents=True)
    (tmp_path / "docs/readmes/manifest.toml").write_text("version = 1\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "sevn"\nversion = "0.0.1"\n', encoding="utf-8"
    )
    manifest = ReadmeManifest(version=1, entries=(_root_entry(),))
    markdown = await render_readme_markdown(
        repo_root=tmp_path,
        entry=_root_entry(),
        manifest=manifest,
    )
    assert _LIVE_CI_BADGE in markdown
