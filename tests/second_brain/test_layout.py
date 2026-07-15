"""Tests for ``second_brain.layout`` config and ``VaultLayout`` resolver (D1-D5)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from sevn.config.workspace_config import SecondBrainWorkspaceConfig, parse_workspace_config
from sevn.onboarding.validate import validate_workspace_document
from sevn.second_brain.errors import SecondBrainPathError
from sevn.second_brain.paths import (
    assert_wiki_relative_safe,
    outputs_dir_for_scope,
    raw_dir_for_scope,
    resolve_scope_root,
    wiki_dir_for_scope,
)
from tests.second_brain.conftest import (
    PARA_PROFILE_DEFAULTS,
    legacy_sevn_doc,
    para_sevn_doc,
    sb_cfg_from_doc,
)

# --- W1.1 config (green after W2) ---------------------------------------------------------------


def test_layout_defaults_to_legacy() -> None:
    assert "layout" in SecondBrainWorkspaceConfig.model_fields
    cfg = SecondBrainWorkspaceConfig()
    assert cfg.layout == "legacy"  # type: ignore[attr-defined]


def test_layout_para_parses() -> None:
    assert "layout" in SecondBrainWorkspaceConfig.model_fields
    doc = parse_workspace_config(para_sevn_doc())
    sb = doc.second_brain
    assert sb is not None
    assert sb.layout == "para"  # type: ignore[attr-defined]


@pytest.mark.parametrize("bad", ["obsidian", "PARA", "legacy-extra", ""])
def test_layout_invalid_value_rejected(bad: str) -> None:
    doc = para_sevn_doc()
    doc["second_brain"]["layout"] = bad
    with pytest.raises(ValidationError):
        parse_workspace_config(doc)


def test_para_profile_defaults() -> None:
    doc = parse_workspace_config(para_sevn_doc())
    sb = doc.second_brain
    assert sb is not None
    para = sb.para  # type: ignore[attr-defined]
    for key, expected in PARA_PROFILE_DEFAULTS.items():
        assert getattr(para, key) == expected


def test_para_profile_override_single_segment() -> None:
    doc = parse_workspace_config(para_sevn_doc(para={"inbox": "00_Capture"}))
    sb = doc.second_brain
    assert sb is not None
    assert sb.para.inbox == "00_Capture"  # type: ignore[attr-defined]


@pytest.mark.parametrize("bad_segment", ["../inbox", "a/b", ".."])
def test_para_profile_rejects_unsafe_segment(bad_segment: str) -> None:
    with pytest.raises(ValidationError):
        parse_workspace_config(para_sevn_doc(para={"inbox": bad_segment}))


def test_para_profile_rejects_unknown_key() -> None:
    doc = para_sevn_doc()
    doc["second_brain"]["para"]["extra_key"] = "nope"
    with pytest.raises(ValidationError):
        parse_workspace_config(doc)


def test_sevn_config_validate_accepts_legacy_fixture() -> None:
    validate_workspace_document(legacy_sevn_doc())
    parsed = parse_workspace_config(legacy_sevn_doc())
    sb = parsed.second_brain
    assert sb is not None
    assert sb.layout == "legacy"  # type: ignore[attr-defined]


def test_sevn_config_validate_accepts_para_fixture() -> None:
    validate_workspace_document(para_sevn_doc())
    parsed = parse_workspace_config(para_sevn_doc())
    sb = parsed.second_brain
    assert sb is not None
    assert sb.layout == "para"  # type: ignore[attr-defined]
    assert sb.para.projects == "10_Projects"  # type: ignore[attr-defined]


# --- W1.2 resolver (green after W3) -------------------------------------------------------------


def _vault_layout(
    content_root: Path,
    cfg: SecondBrainWorkspaceConfig,
    scope: str = "owner",
) -> Any:
    from sevn.second_brain.paths import VaultLayout  # type: ignore[attr-defined]

    return VaultLayout(content_root, cfg, scope)


def _sb_cfg(doc: dict[str, object]) -> SecondBrainWorkspaceConfig:
    return sb_cfg_from_doc(doc)


def test_legacy_role_dir_map_matches_current_paths(tmp_path: Path) -> None:
    cfg = SecondBrainWorkspaceConfig()
    scope_root = resolve_scope_root(tmp_path, cfg, "owner")
    layout = _vault_layout(tmp_path, cfg)
    assert layout.role_dir("curated").resolve() == wiki_dir_for_scope(scope_root).resolve()
    assert layout.role_dir("sources").resolve() == raw_dir_for_scope(scope_root).resolve()
    assert layout.role_dir("outputs").resolve() == outputs_dir_for_scope(scope_root).resolve()
    assert layout.role_dir("index_note").resolve() == (scope_root / "wiki" / "index.md").resolve()
    assert layout.role_dir("log_note").resolve() == (scope_root / "wiki" / "log.md").resolve()


def test_legacy_content_roots_is_wiki_only(tmp_path: Path) -> None:
    cfg = SecondBrainWorkspaceConfig()
    layout = _vault_layout(tmp_path, cfg)
    scope_root = resolve_scope_root(tmp_path, cfg, "owner")
    roots = layout.content_roots()
    assert roots == (wiki_dir_for_scope(scope_root).resolve(),)


def test_para_role_dir_map(tmp_path: Path, para_vault_root: Path) -> None:
    cfg = _sb_cfg(para_sevn_doc())
    layout = _vault_layout(tmp_path, cfg)
    vault = para_vault_root
    assert layout.role_dir("capture").resolve() == (vault / "00_Inbox").resolve()
    assert layout.role_dir("projects").resolve() == (vault / "10_Projects").resolve()
    assert layout.role_dir("areas").resolve() == (vault / "20_Areas").resolve()
    assert layout.role_dir("curated").resolve() == (vault / "30_Resources").resolve()
    assert layout.role_dir("archive").resolve() == (vault / "40_Archive").resolve()
    assert layout.role_dir("templates").resolve() == (vault / "90_Templates").resolve()
    assert layout.role_dir("sources").resolve() == (vault / "30_Resources" / "_sources").resolve()
    assert layout.role_dir("outputs").resolve() == (vault / "30_Resources" / "_outputs").resolve()
    assert layout.role_dir("index_note").resolve() == (vault / "index.md").resolve()
    assert layout.role_dir("log_note").resolve() == (vault / "log.md").resolve()


def test_para_content_roots_excludes_templates_and_archive(
    tmp_path: Path,
    para_vault_root: Path,
) -> None:
    cfg = _sb_cfg(para_sevn_doc())
    layout = _vault_layout(tmp_path, cfg)
    vault = para_vault_root
    roots = {p.resolve() for p in layout.content_roots()}
    expected = {
        (vault / "00_Inbox").resolve(),
        (vault / "10_Projects").resolve(),
        (vault / "20_Areas").resolve(),
        (vault / "30_Resources").resolve(),
    }
    assert roots == expected
    assert (vault / "90_Templates").resolve() not in roots
    assert (vault / "40_Archive").resolve() not in roots


@pytest.mark.parametrize("bad", ["../escape.md"])
def test_assert_wiki_relative_safe_rejects_traversal_legacy(bad: str) -> None:
    with pytest.raises(SecondBrainPathError):
        assert_wiki_relative_safe(bad)


@pytest.mark.parametrize("bad", ["../escape.md", "/abs/note.md"])
def test_assert_wiki_relative_safe_rejects_traversal_para(bad: str, tmp_path: Path) -> None:
    cfg = _sb_cfg(para_sevn_doc())
    layout = _vault_layout(tmp_path, cfg)
    curated = layout.role_dir("curated")
    curated.mkdir(parents=True, exist_ok=True)
    from sevn.second_brain.paths import resolve_wiki_file

    with pytest.raises(SecondBrainPathError):
        resolve_wiki_file(wiki_root=curated, workspace_root=tmp_path, rel_path=bad)


def test_wiki_dir_for_scope_shim_matches_curated_role(tmp_path: Path) -> None:
    cfg = SecondBrainWorkspaceConfig()
    scope_root = resolve_scope_root(tmp_path, cfg, "owner")
    layout = _vault_layout(tmp_path, cfg)
    assert wiki_dir_for_scope(scope_root).resolve() == layout.role_dir("curated").resolve()


def test_legacy_fixture_json_round_trip() -> None:
    """Sanity: legacy oracle fixture stays JSON-serialisable (no W2 dependency)."""
    payload = legacy_sevn_doc()
    round_trip = json.loads(json.dumps(payload))
    assert round_trip["second_brain"]["enabled"] is True
