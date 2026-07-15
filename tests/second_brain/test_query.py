"""Tests for ``second_brain_query`` union behaviour."""

from __future__ import annotations

from sevn.second_brain.paths import (
    shared_wiki_root,
    user_scope_root,
    vault_root,
    wiki_dir_for_scope,
)
from sevn.second_brain.query import second_brain_query


def test_query_index_okf_link(tmp_path) -> None:
    vault = vault_root(tmp_path)
    scope = user_scope_root(vault, "owner")
    uw = wiki_dir_for_scope(scope)
    uw.mkdir(parents=True)
    (uw / "index.md").write_text(
        "# Index\n\n- [Concept](/topics/concept.md) — summary\n",
        encoding="utf-8",
    )
    (uw / "topics").mkdir()
    (uw / "topics" / "concept.md").write_text(
        "---\ntype: Reference\ntitle: Concept\n---\nconcept alpha keyword\n",
        encoding="utf-8",
    )
    rows = second_brain_query(
        q="concept",
        user_wiki=uw,
        shared_wiki=None,
        include_shared=False,
        limit=5,
    )
    assert any(r.get("page") == "topics/concept.md" for r in rows)


def test_query_includes_shared_when_no_basename_collision(tmp_path) -> None:
    vault = vault_root(tmp_path)
    scope = user_scope_root(vault, "owner")
    uw = wiki_dir_for_scope(scope)
    sw = shared_wiki_root(vault)
    uw.mkdir(parents=True)
    sw.mkdir(parents=True)
    (uw / "index.md").write_text("# Index\n\n- local page\n", encoding="utf-8")
    (sw / "only-shared.md").write_text("---\n---\ncontent zeta-unique-phrase\n", encoding="utf-8")
    rows = second_brain_query(
        q="zeta-unique-phrase",
        user_wiki=uw,
        shared_wiki=sw,
        include_shared=True,
        limit=10,
    )
    assert any(r.get("origin") == "shared" for r in rows)


def test_query_finds_note_in_para_projects(tmp_path) -> None:
    from sevn.config.workspace_config import parse_workspace_config
    from sevn.second_brain.paths import VaultLayout  # type: ignore[attr-defined]

    vault = tmp_path / "obsidian" / "alex_AI"
    projects = vault / "10_Projects"
    projects.mkdir(parents=True)
    (vault / "index.md").write_text("# Index\n", encoding="utf-8")
    (projects / "plan.md").write_text(
        "---\ntype: Project\ntitle: Plan\n---\npara-query-unique-token\n",
        encoding="utf-8",
    )
    doc = parse_workspace_config(
        {
            "schema_version": 1,
            "gateway": {"token": "x"},
            "second_brain": {
                "enabled": True,
                "layout": "para",
                "paths": {"vault": "obsidian/alex_AI"},
            },
        },
    )
    sb = doc.second_brain
    assert sb is not None
    layout = VaultLayout(tmp_path, sb, "owner")
    roots = layout.content_roots()
    rows = second_brain_query(
        q="para-query-unique-token",
        user_wiki=roots[0],
        shared_wiki=None,
        include_shared=False,
        limit=5,
        content_roots=roots,  # type: ignore[call-arg]
    )
    assert any("plan.md" in str(r.get("page", "")) for r in rows)
