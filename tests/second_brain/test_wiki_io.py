"""Tests for wiki atomic apply."""

from __future__ import annotations

import hashlib

import pytest

from sevn.second_brain.errors import SecondBrainMergeNeededError
from sevn.second_brain.frontmatter import compose_page
from sevn.second_brain.wiki_io import wiki_apply_atomic, wiki_read


def _digest_file(p) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_wiki_apply_happy_path(tmp_path) -> None:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    page = wiki / "a.md"
    initial = compose_page({"title": "A"}, "one")
    page.write_text(initial, encoding="utf-8")
    h = _digest_file(page)
    new = compose_page({"title": "A"}, "two")
    wiki_apply_atomic(path=page, patch=new, base_hash=h, workspace_root=tmp_path)
    _, _fm, body = wiki_read(page)
    assert body.strip() == "two"


def test_wiki_apply_merge_needed(tmp_path) -> None:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    page = wiki / "b.md"
    page.write_text(compose_page({}, "x"), encoding="utf-8")
    with pytest.raises(SecondBrainMergeNeededError):
        wiki_apply_atomic(
            path=page,
            patch=compose_page({}, "y"),
            base_hash="0" * 64,
            workspace_root=tmp_path,
        )
