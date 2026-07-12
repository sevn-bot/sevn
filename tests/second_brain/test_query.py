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
