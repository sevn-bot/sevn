"""Tests for PARA layout lint and frontmatter (D8/D9)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from sevn.second_brain.frontmatter import compose_page, split_frontmatter
from tests.second_brain.conftest import para_sevn_doc, sb_cfg_from_doc

if TYPE_CHECKING:
    from sevn.config.workspace_config import SecondBrainWorkspaceConfig


def _lint_vault(layout: Any, *, stale_days: int = 90) -> list[Any]:
    from sevn.second_brain.lint_local import lint_vault_tree  # type: ignore[attr-defined]

    issues = lint_vault_tree(layout, stale_days=stale_days)
    return list(issues)


def _vault_layout(content_root: Path, cfg: SecondBrainWorkspaceConfig, scope: str = "owner") -> Any:
    from sevn.second_brain.paths import VaultLayout  # type: ignore[attr-defined]

    return VaultLayout(content_root, cfg, scope)


def test_para_lint_flags_dangling_wikilink(tmp_path: Path, para_vault_root: Path) -> None:
    cfg = sb_cfg_from_doc(para_sevn_doc())
    layout = _vault_layout(tmp_path, cfg)
    inbox = para_vault_root / "00_Inbox"
    inbox.mkdir(parents=True)
    (inbox / "note.md").write_text(
        compose_page({"title": "Note", "tags": ["inbox"]}, "See [[missing]].\n"),
        encoding="utf-8",
    )
    issues = _lint_vault(layout)
    assert any("wikilink" in i.message.lower() for i in issues)


def test_para_lint_flags_orphan_page(tmp_path: Path, para_vault_root: Path) -> None:
    cfg = sb_cfg_from_doc(para_sevn_doc())
    layout = _vault_layout(tmp_path, cfg)
    orphan = para_vault_root / "10_Projects" / "lonely.md"
    orphan.parent.mkdir(parents=True)
    orphan.write_text(compose_page({"title": "Lonely"}, "# Lonely\n"), encoding="utf-8")
    issues = _lint_vault(layout)
    assert any(i.path.endswith("lonely.md") and "orphan" in i.message.lower() for i in issues)


def test_para_lint_skips_templates_and_archive(tmp_path: Path, para_vault_root: Path) -> None:
    cfg = sb_cfg_from_doc(para_sevn_doc())
    layout = _vault_layout(tmp_path, cfg)
    templates = para_vault_root / "90_Templates" / "orphan.md"
    archive = para_vault_root / "40_Archive" / "old.md"
    templates.parent.mkdir(parents=True)
    archive.parent.mkdir(parents=True)
    templates.write_text("# Template orphan\n", encoding="utf-8")
    archive.write_text("# Archived orphan\n", encoding="utf-8")
    issues = _lint_vault(layout)
    paths = {i.path for i in issues}
    assert not any("90_Templates" in p for p in paths)
    assert not any("40_Archive" in p for p in paths)


def test_para_type_missing_is_warning(tmp_path: Path, para_vault_root: Path) -> None:
    cfg = sb_cfg_from_doc(para_sevn_doc())
    layout = _vault_layout(tmp_path, cfg)
    note = para_vault_root / "30_Resources" / "note.md"
    note.parent.mkdir(parents=True)
    note.write_text(compose_page({"title": "Note"}, "# Note\n"), encoding="utf-8")
    issues = _lint_vault(layout)
    type_issues = [i for i in issues if "type" in i.message.lower()]
    assert type_issues
    assert all(i.severity == "warning" for i in type_issues)


def test_para_frontmatter_obsidian_keys_round_trip() -> None:
    fm_in = {
        "tags": ["project", "active"],
        "aliases": ["My Project"],
        "created": "2026-01-01",
        "updated": "2026-07-01",
        "source": "meeting-notes",
        "source_hash": "abc123",
        "captured": "2026-07-01T12:00:00Z",
        "title": "Project Alpha",
    }
    text = compose_page(fm_in, "# Project Alpha\n")
    fm_out, body, _ = split_frontmatter(text)
    for key in ("tags", "aliases", "created", "updated", "source", "source_hash", "captured"):
        assert fm_out.get(key) == fm_in[key]
    assert body.strip().startswith("# Project Alpha")
