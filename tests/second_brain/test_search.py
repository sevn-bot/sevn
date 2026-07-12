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
