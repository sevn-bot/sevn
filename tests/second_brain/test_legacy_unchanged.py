"""Back-compat oracle — legacy layout paths and bootstrap tree (D17, W1.0).

These tests must stay green through every implementation wave without edits.
They snapshot today's ``wiki`` / ``raw`` / ``outputs`` layout contract.
"""

from __future__ import annotations

from pathlib import Path

from sevn.config.workspace_config import SecondBrainWorkspaceConfig, parse_workspace_config
from sevn.second_brain.bootstrap import ensure_second_brain_scope_layout
from sevn.second_brain.paths import (
    outputs_dir_for_scope,
    raw_dir_for_scope,
    resolve_scope_root,
    wiki_dir_for_scope,
)

LEGACY_BOOTSTRAP_DIRS = frozenset({"raw", "wiki", "wiki/ingests", "outputs"})
LEGACY_BOOTSTRAP_FILES = frozenset({"wiki/index.md", "wiki/log.md"})


def test_legacy_role_dirs_resolve_wiki_raw_outputs(tmp_path: Path) -> None:
    cfg = SecondBrainWorkspaceConfig()
    scope_root = resolve_scope_root(tmp_path, cfg, "owner")
    assert wiki_dir_for_scope(scope_root).resolve() == (scope_root / "wiki").resolve()
    assert raw_dir_for_scope(scope_root).resolve() == (scope_root / "raw").resolve()
    assert outputs_dir_for_scope(scope_root).resolve() == (scope_root / "outputs").resolve()


def test_legacy_custom_vault_still_uses_wiki_raw_outputs(tmp_path: Path) -> None:
    vault = tmp_path / "obsidian" / "alex_AI"
    vault.mkdir(parents=True)
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "gateway": {"token": "x"},
            "second_brain": {"paths": {"vault": "obsidian/alex_AI"}},
        },
    ).second_brain
    assert cfg is not None
    scope_root = resolve_scope_root(tmp_path, cfg, "owner")
    assert scope_root.resolve() == vault.resolve()
    assert wiki_dir_for_scope(scope_root).resolve() == (vault / "wiki").resolve()
    assert raw_dir_for_scope(scope_root).resolve() == (vault / "raw").resolve()
    assert outputs_dir_for_scope(scope_root).resolve() == (vault / "outputs").resolve()


def test_legacy_bootstrap_creates_canonical_tree(tmp_path: Path) -> None:
    created = ensure_second_brain_scope_layout(tmp_path, copy_model=False)
    for rel in LEGACY_BOOTSTRAP_DIRS:
        assert (tmp_path / rel).is_dir(), rel
    for rel in LEGACY_BOOTSTRAP_FILES:
        assert (tmp_path / rel).is_file(), rel
    assert set(created) >= LEGACY_BOOTSTRAP_DIRS
    assert set(created) >= LEGACY_BOOTSTRAP_FILES


def test_legacy_bootstrap_idempotent_preserves_custom_index(tmp_path: Path) -> None:
    ensure_second_brain_scope_layout(tmp_path, copy_model=False)
    index = tmp_path / "wiki" / "index.md"
    index.write_text("# Custom index\n", encoding="utf-8")
    created = ensure_second_brain_scope_layout(tmp_path, copy_model=False)
    assert index.read_text(encoding="utf-8") == "# Custom index\n"
    assert "wiki/index.md" not in created
