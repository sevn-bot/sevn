"""Witchcraft reindex with custom Second Brain vault paths."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sevn.config.workspace_config import WorkspaceConfig
from sevn.second_brain.witchcraft_reindex import (
    reindex_workspace_wiki,
    resolve_index_wiki_paths,
)


def _config_with_custom_vault(tmp_path: Path) -> WorkspaceConfig:
    vault = tmp_path / "obsidian" / "alex_AI"
    vault.mkdir(parents=True)
    return WorkspaceConfig.minimal(
        second_brain={
            "enabled": True,
            "default_scope": "owner",
            "paths": {"vault": "obsidian/alex_AI"},
        },
        witchcraft_enabled=True,
    )


def test_resolve_index_wiki_paths_custom_vault(tmp_path: Path) -> None:
    cfg = _config_with_custom_vault(tmp_path)
    out = resolve_index_wiki_paths(config=cfg, content_root=tmp_path)
    assert out is not None
    user_wiki, shared = out
    assert user_wiki == (tmp_path / "obsidian" / "alex_AI" / "wiki").resolve()
    assert shared is None


def test_resolve_index_wiki_paths_default_layout(tmp_path: Path) -> None:
    cfg = WorkspaceConfig.minimal(second_brain={"enabled": True})
    out = resolve_index_wiki_paths(config=cfg, content_root=tmp_path)
    assert out is not None
    user_wiki, _shared = out
    assert user_wiki == (tmp_path / "second_brain" / "users" / "owner" / "wiki").resolve()


def test_reindex_workspace_wiki_uses_custom_vault_wiki(tmp_path: Path) -> None:
    cfg = _config_with_custom_vault(tmp_path)
    expected_wiki = tmp_path / "obsidian" / "alex_AI" / "wiki"
    expected_wiki.mkdir(parents=True)
    with patch(
        "sevn.second_brain.witchcraft_reindex.build_wiki_index",
        return_value=True,
    ) as mock_build:
        ok = reindex_workspace_wiki(config=cfg, content_root=tmp_path)
    assert ok is True
    mock_build.assert_called_once()
    indexed_wiki = mock_build.call_args.args[0]
    assert indexed_wiki == expected_wiki.resolve()
    assert mock_build.call_args.kwargs["workspace_path"] == tmp_path


def test_reindex_workspace_wiki_disabled_without_witchcraft(tmp_path: Path) -> None:
    cfg = WorkspaceConfig.minimal(
        second_brain={
            "enabled": True,
            "paths": {"vault": "obsidian/alex_AI"},
        },
    )
    assert reindex_workspace_wiki(config=cfg, content_root=tmp_path) is False


def test_reindex_workspace_wiki_disabled_when_second_brain_off(tmp_path: Path) -> None:
    cfg = WorkspaceConfig.minimal(
        second_brain={"enabled": False},
        witchcraft_enabled=True,
    )
    assert reindex_workspace_wiki(config=cfg, content_root=tmp_path) is False


def test_resolve_index_wiki_paths_para_layout(tmp_path: Path) -> None:
    vault = tmp_path / "obsidian" / "alex_AI"
    for name in ("00_Inbox", "10_Projects", "20_Areas", "30_Resources"):
        (vault / name).mkdir(parents=True)
    cfg = WorkspaceConfig.minimal(
        second_brain={
            "enabled": True,
            "layout": "para",
            "paths": {"vault": "obsidian/alex_AI"},
        },
        witchcraft_enabled=True,
    )
    out = resolve_index_wiki_paths(config=cfg, content_root=tmp_path)
    assert out is not None
    user_roots, shared = out
    assert shared is None
    if isinstance(user_roots, tuple):
        resolved = {p.resolve() for p in user_roots}
    else:
        resolved = {user_roots.resolve()}
    expected = {
        (vault / "00_Inbox").resolve(),
        (vault / "10_Projects").resolve(),
        (vault / "20_Areas").resolve(),
        (vault / "30_Resources").resolve(),
    }
    assert resolved == expected
