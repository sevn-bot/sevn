"""Tests for Second Brain path resolution with custom vault paths."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sevn.config.workspace_config import SecondBrainWorkspaceConfig, parse_workspace_config
from sevn.second_brain.errors import SecondBrainPathError
from sevn.second_brain.paths import (
    assert_wiki_relative_safe,
    display_scope_root_relative,
    resolve_scope_root,
    user_scope_root,
    vault_root,
    wiki_dir_for_scope,
)


def test_reject_dotdot_in_wiki_path() -> None:
    with pytest.raises(SecondBrainPathError):
        assert_wiki_relative_safe("../escape.md")


def test_vault_and_scope_paths(tmp_path) -> None:
    v = vault_root(tmp_path)
    assert v.name == "second_brain"
    s = user_scope_root(v, "owner")
    assert s.name == "owner"


def test_default_scope_layout_unchanged(tmp_path) -> None:
    cfg = SecondBrainWorkspaceConfig()
    scope_root = resolve_scope_root(tmp_path, cfg, "owner")
    assert scope_root == (tmp_path / "second_brain" / "users" / "owner").resolve()
    assert wiki_dir_for_scope(scope_root).name == "wiki"


def test_wiki_dir_shim_returns_wiki_for_legacy_layout(tmp_path) -> None:
    from sevn.second_brain.paths import VaultLayout  # type: ignore[attr-defined]

    cfg = SecondBrainWorkspaceConfig()
    scope_root = resolve_scope_root(tmp_path, cfg, "owner")
    layout = VaultLayout(tmp_path, cfg, "owner")
    assert wiki_dir_for_scope(scope_root).resolve() == layout.role_dir("curated").resolve()
    assert wiki_dir_for_scope(scope_root).name == "wiki"


def test_custom_vault_resolves_under_workspace(tmp_path) -> None:
    target = tmp_path / "obsidian" / "alex_AI"
    target.mkdir(parents=True)
    cfg = SecondBrainWorkspaceConfig(paths={"vault": "obsidian/alex_AI"})
    scope_root = resolve_scope_root(tmp_path, cfg, "owner")
    assert scope_root == target.resolve()
    assert wiki_dir_for_scope(scope_root) == (target / "wiki").resolve()


def test_custom_vault_rejects_escape(tmp_path) -> None:
    with pytest.raises(ValidationError):
        SecondBrainWorkspaceConfig(paths={"vault": "../outside"})


def test_non_default_scope_falls_back_with_custom_vault(tmp_path) -> None:
    cfg = SecondBrainWorkspaceConfig(default_scope="owner", paths={"vault": "obsidian/alex_AI"})
    scope_root = resolve_scope_root(tmp_path, cfg, "guest")
    assert scope_root == (tmp_path / "second_brain" / "users" / "guest").resolve()


def test_display_scope_root_relative(tmp_path) -> None:
    scope = tmp_path / "obsidian" / "alex_AI"
    scope.mkdir(parents=True)
    assert display_scope_root_relative(tmp_path, scope) == "obsidian/alex_AI"


def test_parse_paths_vault_round_trip() -> None:
    doc = parse_workspace_config(
        {
            "schema_version": 1,
            "gateway": {"token": "x"},
            "second_brain": {"enabled": True, "paths": {"vault": "obsidian/alex_AI"}},
        },
    )
    assert doc.second_brain.paths.vault == "obsidian/alex_AI"


def test_paths_wiki_alias_maps_to_vault() -> None:
    doc = parse_workspace_config(
        {
            "schema_version": 1,
            "gateway": {"token": "x"},
            "second_brain": {"paths": {"wiki": "obsidian/legacy"}},
        },
    )
    assert doc.second_brain.paths.vault == "obsidian/legacy"


def test_resolve_vault_note_file_para_index_and_archive(tmp_path) -> None:
    from sevn.second_brain.paths import VaultLayout, resolve_vault_note_file

    vault = tmp_path / "obsidian" / "alex_AI"
    inbox = vault / "00_Inbox"
    archive = vault / "40_Archive"
    resources = vault / "30_Resources"
    for d in (inbox, archive, resources):
        d.mkdir(parents=True)
    (vault / "index.md").write_text("# home\n", encoding="utf-8")
    (vault / "log.md").write_text("# log\n", encoding="utf-8")
    cfg = SecondBrainWorkspaceConfig(
        layout="para",
        paths={"vault": "obsidian/alex_AI"},
    )
    layout = VaultLayout(tmp_path, cfg, "owner")

    index_hit = resolve_vault_note_file(layout=layout, workspace_root=tmp_path, rel_path="index.md")
    assert index_hit == (vault / "index.md").resolve()

    archive_new = resolve_vault_note_file(
        layout=layout,
        workspace_root=tmp_path,
        rel_path="40_Archive/new.md",
    )
    assert archive_new == (archive / "new.md").resolve()

    inbox_hit = resolve_vault_note_file(
        layout=layout,
        workspace_root=tmp_path,
        rel_path="00_Inbox/capture.md",
    )
    assert inbox_hit == (inbox / "capture.md").resolve()
