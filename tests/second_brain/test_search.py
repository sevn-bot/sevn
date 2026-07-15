"""Tests for wiki_search ranking."""

from __future__ import annotations

from pathlib import Path

from sevn.second_brain.search import wiki_search


def test_wiki_search_orders_by_relevance(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "a.md").write_text("---\ntitle: A\n---\nalpha beta\n", encoding="utf-8")
    (wiki / "b.md").write_text("---\ntitle: B\n---\nalpha alpha alpha\n", encoding="utf-8")
    hits = wiki_search(query="alpha", user_wiki=wiki, shared_wiki=None, limit=10)
    assert len(hits) == 2
    assert hits[0]["path"] == "b.md"


def test_wiki_search_finds_note_across_para_roots(tmp_path: Path) -> None:
    from sevn.config.workspace_config import parse_workspace_config
    from sevn.second_brain.paths import VaultLayout  # type: ignore[attr-defined]

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
    vault = tmp_path / "obsidian" / "alex_AI"
    projects = vault / "10_Projects"
    projects.mkdir(parents=True)
    (projects / "goal.md").write_text(
        "---\ntitle: Goal\n---\npara-search-token\n", encoding="utf-8"
    )
    hits = wiki_search(
        query="para-search-token",
        user_wiki=layout.content_roots()[0],
        shared_wiki=None,
        limit=10,
        content_roots=layout.content_roots(),  # type: ignore[call-arg]
    )
    assert any("goal.md" in str(h.get("path")) for h in hits)
