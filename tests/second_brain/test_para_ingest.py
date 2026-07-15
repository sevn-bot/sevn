"""Tests for PARA ingest, search, and Witchcraft indexing (D10/D11)."""

from __future__ import annotations

import json
from pathlib import Path

from sevn.config.workspace_config import WorkspaceConfig
from sevn.second_brain.frontmatter import split_frontmatter
from sevn.second_brain.ingest import run_ingest
from sevn.second_brain.paths import resolve_scope_root
from sevn.second_brain.search import wiki_search
from sevn.second_brain.witchcraft_reindex import resolve_index_wiki_paths
from tests.second_brain.conftest import para_sevn_doc, sb_cfg_from_doc


def _para_workspace_config(tmp_path: Path) -> WorkspaceConfig:
    doc = para_sevn_doc()
    (tmp_path / "sevn.json").write_text(json.dumps(doc), encoding="utf-8")
    return WorkspaceConfig.model_validate(doc)


def _bootstrap_para_vault(tmp_path: Path, vault: Path) -> None:
    from sevn.second_brain.bootstrap import ensure_second_brain_scope_layout

    cfg = sb_cfg_from_doc(para_sevn_doc())
    ensure_second_brain_scope_layout(vault, cfg=cfg, copy_model=False)  # type: ignore[call-arg]


def test_para_ingest_source_lands_under_resources_sources(
    tmp_path: Path, para_vault_root: Path
) -> None:
    cfg = sb_cfg_from_doc(para_sevn_doc())
    scope_root = resolve_scope_root(tmp_path, cfg, "owner")
    _bootstrap_para_vault(tmp_path, para_vault_root)
    sources = para_vault_root / "30_Resources" / "_sources"
    sources.mkdir(parents=True, exist_ok=True)
    (sources / "article.md").write_text("# Source\nbody text\n", encoding="utf-8")
    out = run_ingest(
        workspace_root=tmp_path,
        vault_users_scope=scope_root,
        raw_relpath="article.md",
        sevn_source="test",
    )
    assert out["skipped"] is False
    stored = sources / "article.md"
    assert stored.is_file()
    assert out.get("raw_hash")


def test_para_ingest_curated_page_in_inbox_with_provenance(
    tmp_path: Path,
    para_vault_root: Path,
) -> None:
    cfg = sb_cfg_from_doc(para_sevn_doc())
    scope_root = resolve_scope_root(tmp_path, cfg, "owner")
    _bootstrap_para_vault(tmp_path, para_vault_root)
    sources = para_vault_root / "30_Resources" / "_sources"
    sources.mkdir(parents=True, exist_ok=True)
    (sources / "note.md").write_text("# Title\ncontent\n", encoding="utf-8")
    run_ingest(
        workspace_root=tmp_path,
        vault_users_scope=scope_root,
        raw_relpath="note.md",
        sevn_source="capture",
    )
    page = para_vault_root / "00_Inbox" / "note.md"
    assert page.is_file()
    fm, _body, _ = split_frontmatter(page.read_text(encoding="utf-8"))
    assert fm.get("source") or fm.get("sevn_source")
    assert fm.get("source_hash") or fm.get("sevn_raw_hash")


def test_para_ingest_outputs_dir(tmp_path: Path, para_vault_root: Path) -> None:
    _bootstrap_para_vault(tmp_path, para_vault_root)
    outputs = para_vault_root / "30_Resources" / "_outputs"
    assert outputs.is_dir()


def test_para_ingest_appends_root_log(tmp_path: Path, para_vault_root: Path) -> None:
    cfg = sb_cfg_from_doc(para_sevn_doc())
    scope_root = resolve_scope_root(tmp_path, cfg, "owner")
    _bootstrap_para_vault(tmp_path, para_vault_root)
    log = para_vault_root / "log.md"
    log.write_text("# Log\n", encoding="utf-8")
    sources = para_vault_root / "30_Resources" / "_sources"
    sources.mkdir(parents=True, exist_ok=True)
    (sources / "x.md").write_text("body\n", encoding="utf-8")
    run_ingest(
        workspace_root=tmp_path,
        vault_users_scope=scope_root,
        raw_relpath="x.md",
        sevn_source="test",
    )
    assert "ingest" in log.read_text(encoding="utf-8").lower()


def test_para_wiki_search_finds_project_note(tmp_path: Path, para_vault_root: Path) -> None:
    from sevn.second_brain.paths import VaultLayout  # type: ignore[attr-defined]

    layout = VaultLayout(tmp_path, sb_cfg_from_doc(para_sevn_doc()), "owner")
    projects = para_vault_root / "10_Projects"
    projects.mkdir(parents=True)
    (projects / "alpha.md").write_text(
        "---\ntitle: Alpha\n---\nunique-alpha-token-here\n",
        encoding="utf-8",
    )
    roots = layout.content_roots()
    hits = wiki_search(
        query="unique-alpha-token-here",
        user_wiki=roots[0],
        shared_wiki=None,
        limit=10,
        content_roots=layout.content_roots(),  # type: ignore[call-arg]
    )
    assert any("alpha.md" in str(h.get("path", "")) for h in hits)


def test_resolve_index_wiki_paths_para_content_roots(
    tmp_path: Path,
    para_vault_root: Path,
) -> None:
    cfg = _para_workspace_config(tmp_path)
    for name in ("00_Inbox", "10_Projects", "20_Areas", "30_Resources"):
        (para_vault_root / name).mkdir(parents=True, exist_ok=True)
    out = resolve_index_wiki_paths(config=cfg, content_root=tmp_path)
    assert out is not None
    user_roots, shared = out
    assert shared is None
    if isinstance(user_roots, tuple):
        resolved = {p.resolve() for p in user_roots}
    else:
        resolved = {user_roots.resolve()}
    expected = {
        (para_vault_root / "00_Inbox").resolve(),
        (para_vault_root / "10_Projects").resolve(),
        (para_vault_root / "20_Areas").resolve(),
        (para_vault_root / "30_Resources").resolve(),
    }
    assert resolved == expected
