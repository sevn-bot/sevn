"""Tests for idempotent ingest stub."""

from __future__ import annotations

from pathlib import Path

from sevn.second_brain.frontmatter import split_frontmatter
from sevn.second_brain.ingest_stub import run_ingest_stub
from sevn.second_brain.paths import raw_dir_for_scope, user_scope_root, vault_root


def test_ingest_stub_creates_page_and_updates_index(tmp_path: Path) -> None:
    vault = vault_root(tmp_path)
    scope_path = user_scope_root(vault, "owner")
    raw = raw_dir_for_scope(scope_path)
    raw.mkdir(parents=True)
    (raw / "note.md").write_text("src", encoding="utf-8")
    out = run_ingest_stub(
        workspace_root=tmp_path,
        vault_users_scope=scope_path,
        raw_relpath="note.md",
        sevn_source="test",
    )
    assert out["promoted"] is False
    wiki = scope_path / "wiki"
    page = wiki / "ingests" / "note.md"
    assert page.is_file()
    fm, _body, _ = split_frontmatter(page.read_text(encoding="utf-8"))
    assert fm.get("type") == "Stub"
    assert (wiki / "index.md").is_file()
    assert (wiki / "log.md").is_file()
