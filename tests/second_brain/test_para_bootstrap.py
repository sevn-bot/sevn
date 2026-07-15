"""Tests for PARA layout bootstrap and ``detect_layout`` (D6/D7)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sevn.second_brain.bootstrap import ensure_second_brain_scope_layout
from tests.second_brain.conftest import para_sevn_doc, sb_cfg_from_doc

if TYPE_CHECKING:
    from sevn.config.workspace_config import SecondBrainWorkspaceConfig

PARA_BOOTSTRAP_DIRS = frozenset(
    {
        "00_Inbox",
        "10_Projects",
        "20_Areas",
        "30_Resources",
        "30_Resources/_sources",
        "30_Resources/_outputs",
        "40_Archive",
        "90_Templates",
    },
)
PARA_BOOTSTRAP_FILES = frozenset({"index.md", "log.md", "MODEL.md"})


def _bootstrap_scope(
    scope_root: Path,
    cfg: SecondBrainWorkspaceConfig,
    *,
    copy_model: bool = False,
) -> list[str]:
    return ensure_second_brain_scope_layout(scope_root, cfg=cfg, copy_model=copy_model)  # type: ignore[call-arg]


def _detect_layout(vault_root: Path) -> str | None:
    from sevn.second_brain.bootstrap import detect_layout  # type: ignore[attr-defined]

    result = detect_layout(vault_root)
    return result if isinstance(result, (str, type(None))) else str(result)


def test_para_bootstrap_creates_full_role_tree(tmp_path: Path, para_vault_root: Path) -> None:
    cfg = sb_cfg_from_doc(para_sevn_doc())
    created = _bootstrap_scope(para_vault_root, cfg, copy_model=True)
    for rel in PARA_BOOTSTRAP_DIRS:
        assert (para_vault_root / rel).is_dir(), rel
    for rel in PARA_BOOTSTRAP_FILES:
        assert (para_vault_root / rel).is_file(), rel
    assert "00_Inbox" in created or "00_Inbox/" in str(created)


def test_para_bootstrap_copies_bundled_templates(tmp_path: Path, para_vault_root: Path) -> None:
    cfg = sb_cfg_from_doc(para_sevn_doc())
    _bootstrap_scope(para_vault_root, cfg, copy_model=True)
    templates = para_vault_root / "90_Templates"
    names = {p.stem for p in templates.glob("*.md")}
    assert {"project", "area", "meeting", "daily-note"} <= names


def test_para_bootstrap_idempotent(tmp_path: Path, para_vault_root: Path) -> None:
    cfg = sb_cfg_from_doc(para_sevn_doc())
    first = _bootstrap_scope(para_vault_root, cfg, copy_model=False)
    assert first
    second = _bootstrap_scope(para_vault_root, cfg, copy_model=False)
    assert second == []


def test_para_bootstrap_never_overwrites_existing_note(
    tmp_path: Path,
    para_vault_root: Path,
) -> None:
    cfg = sb_cfg_from_doc(para_sevn_doc())
    index = para_vault_root / "index.md"
    index.write_text("# Existing home\n", encoding="utf-8")
    _bootstrap_scope(para_vault_root, cfg, copy_model=False)
    assert index.read_text(encoding="utf-8") == "# Existing home\n"


def test_para_bootstrap_never_overwrites_obsidian(
    tmp_path: Path,
    para_vault_root: Path,
) -> None:
    cfg = sb_cfg_from_doc(para_sevn_doc())
    obsidian = para_vault_root / ".obsidian"
    obsidian.mkdir()
    marker = obsidian / "app.json"
    marker.write_text('{"legacy": true}\n', encoding="utf-8")
    _bootstrap_scope(para_vault_root, cfg, copy_model=False)
    assert json.loads(marker.read_text(encoding="utf-8")) == {"legacy": True}


@pytest.mark.parametrize(
    ("folders", "has_obsidian", "expected"),
    [
        (("00_Inbox", "10_Projects"), False, "para"),
        (("00_Inbox",), True, "para"),
        (("wiki", "raw"), False, "legacy"),
        (("random",), False, None),
    ],
)
def test_detect_layout(
    tmp_path: Path,
    folders: tuple[str, ...],
    has_obsidian: bool,
    expected: str | None,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    for name in folders:
        (vault / name).mkdir()
    if has_obsidian:
        (vault / ".obsidian").mkdir()
    assert _detect_layout(vault) == expected


def test_para_adoption_fills_missing_dirs_only(tmp_path: Path) -> None:
    vault = tmp_path / "obsidian" / "alex_AI"
    vault.mkdir(parents=True)
    (vault / "00_Inbox").mkdir()
    (vault / "10_Projects").mkdir()
    (vault / "index.md").write_text("# Home\n", encoding="utf-8")
    cfg = sb_cfg_from_doc(para_sevn_doc())
    created = _bootstrap_scope(vault, cfg, copy_model=False)
    assert "00_Inbox" not in created
    assert "10_Projects" not in created
    assert (vault / "20_Areas").is_dir()
    assert (vault / "index.md").read_text(encoding="utf-8") == "# Home\n"
