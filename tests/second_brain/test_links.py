"""Tests for Second Brain link extraction and resolution."""

from __future__ import annotations

from pathlib import Path

from sevn.second_brain.links import (
    index_line_targets,
    iter_internal_link_targets,
    resolve_wiki_target,
)


def test_iter_internal_link_targets_wikilink_and_okf() -> None:
    body = "See [[foo]] and [bar](/tables/bar.md) and [rel](./sib.md)"
    assert list(iter_internal_link_targets(body)) == [
        ("wikilink", "foo"),
        ("okf_md", "/tables/bar.md"),
        ("okf_md", "./sib.md"),
    ]


def test_resolve_wikilink_target() -> None:
    by_rel = {"ingests/note.md": Path("ingests/note.md")}
    assert (
        resolve_wiki_target(
            "wikilink",
            "ingests/note",
            source_rel="index.md",
            by_rel=by_rel,
        )
        == "ingests/note.md"
    )


def test_resolve_okf_absolute_target() -> None:
    by_rel = {"tables/foo.md": Path("tables/foo.md")}
    assert (
        resolve_wiki_target(
            "okf_md",
            "/tables/foo.md",
            source_rel="index.md",
            by_rel=by_rel,
        )
        == "tables/foo.md"
    )


def test_resolve_okf_relative_target() -> None:
    by_rel = {"topics/sib.md": Path("topics/sib.md")}
    assert (
        resolve_wiki_target(
            "okf_md",
            "./sib.md",
            source_rel="topics/main.md",
            by_rel=by_rel,
        )
        == "topics/sib.md"
    )


def test_resolve_okf_parent_relative_target() -> None:
    by_rel = {"topics/sibling.md": Path("topics/sibling.md")}
    assert (
        resolve_wiki_target(
            "okf_md",
            "../sibling.md",
            source_rel="topics/nested/page.md",
            by_rel=by_rel,
        )
        == "topics/sibling.md"
    )


def test_resolve_okf_parent_relative_rejects_escape() -> None:
    by_rel = {"topics/sibling.md": Path("topics/sibling.md")}
    assert (
        resolve_wiki_target(
            "okf_md",
            "../../outside.md",
            source_rel="topics/nested/page.md",
            by_rel=by_rel,
        )
        is None
    )


def test_index_line_targets_okf_and_wikilink() -> None:
    assert index_line_targets("- [[ingests/foo]] — title") == ["ingests/foo.md"]
    assert index_line_targets("- [Title](/concepts/bar.md) — summary") == ["concepts/bar.md"]
