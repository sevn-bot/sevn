"""Curated README content contracts (D13-D15; green after W5-W7)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from sevn.docs.readme.manifest import get_entry, load_manifest
from sevn.docs.readme.templates import resolve_template_path, validate_against_template

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "docs/readmes/manifest.toml"
CURATED_STAMP = "<!-- curated:"


@dataclass(frozen=True)
class CuratedContract:
    slug: str
    wave: str
    anchor: str


W5_CONTRACTS: tuple[CuratedContract, ...] = (
    CuratedContract("gateway", "W5", "route_incoming"),
    CuratedContract("security", "W5", "retention_days"),
    CuratedContract("config-workspace", "W5", "cli/config_sections/"),
    CuratedContract("self-improve", "W5", "no live MC/Telegram/CLI caller"),
    CuratedContract("onboarding", "W5", "openai_family"),
    CuratedContract("subagents", "W5", "36-sub-agents.md"),
)

W6_CONTRACTS: tuple[CuratedContract, ...] = (
    CuratedContract("secrets", "W6", "secrets_chain_from_workspace"),
    CuratedContract("proxy-egress", "W6", "/llm/"),
    CuratedContract("tracing", "W6", "configure_gateway_otel"),
    CuratedContract("storage", "W6", "agent/harness/snapshots.py"),
    CuratedContract("ui-mission-control", "W6", "tab_registry"),
)

W7_CONTRACTS: tuple[CuratedContract, ...] = (
    CuratedContract("channels", "W7", "webchat.py"),
    CuratedContract("tools", "W7", "spawn_subagent"),
    CuratedContract("voice", "W7", "tts_mode"),
    CuratedContract("triggers", "W7", "notify_only"),
    CuratedContract("memory-context", "W7", "dreaming"),
    CuratedContract("second-brain", "W7", "paths.vault"),
    CuratedContract("code-understanding", "W7", "roam-code"),
)


def _readme_body(slug: str) -> str:
    path = REPO_ROOT / "docs/readmes" / f"{slug}.md"
    assert path.is_file(), f"missing README for {slug}"
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("contract", W5_CONTRACTS, ids=lambda c: c.slug)
def test_w5_curated_slug_contract(contract: CuratedContract) -> None:
    """D15: W5 curated slugs carry the D5 stamp, template outline, and drift anchor."""
    manifest = load_manifest(MANIFEST_PATH)
    entry = get_entry(manifest, contract.slug)
    assert entry.curated is True
    body = _readme_body(contract.slug)
    assert CURATED_STAMP in body
    template_path = resolve_template_path(REPO_ROOT, entry)
    assert template_path.is_file()
    assert validate_against_template(template_path.read_text(encoding="utf-8"), body) == []
    assert contract.anchor in body


@pytest.mark.parametrize("contract", W6_CONTRACTS, ids=lambda c: c.slug)
def test_w6_curated_slug_contract(contract: CuratedContract) -> None:
    """D13/D14: W6 newly-curated slugs expose required anchor tokens and outlines."""
    manifest = load_manifest(MANIFEST_PATH)
    entry = get_entry(manifest, contract.slug)
    assert entry.curated is True
    assert entry.template
    body = _readme_body(contract.slug)
    assert CURATED_STAMP in body
    template_path = resolve_template_path(REPO_ROOT, entry)
    assert template_path.is_file()
    assert validate_against_template(template_path.read_text(encoding="utf-8"), body) == []
    assert contract.anchor in body


@pytest.mark.parametrize("contract", W7_CONTRACTS, ids=lambda c: c.slug)
def test_w7_curated_slug_contract(contract: CuratedContract) -> None:
    """D13/D14: W7 newly-curated slugs expose required anchor tokens and outlines."""
    manifest = load_manifest(MANIFEST_PATH)
    entry = get_entry(manifest, contract.slug)
    assert entry.curated is True
    assert entry.template
    body = _readme_body(contract.slug)
    assert CURATED_STAMP in body
    template_path = resolve_template_path(REPO_ROOT, entry)
    assert template_path.is_file()
    assert validate_against_template(template_path.read_text(encoding="utf-8"), body) == []
    assert contract.anchor in body
