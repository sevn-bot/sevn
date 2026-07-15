"""Tests for ``lint_wiki_tree``."""

from __future__ import annotations

from pathlib import Path

from sevn.second_brain.frontmatter import compose_page
from sevn.second_brain.lint_local import lint_wiki_tree


def test_lint_warns_large_index(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "index.md").write_text("x" * (512 * 1024 + 1), encoding="utf-8")
    issues = lint_wiki_tree(wiki)
    assert any(i.path == "index.md" and "large" in i.message for i in issues)


def test_lint_missing_okf_type(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "note.md").write_text(
        compose_page({"title": "Note"}, "# Note\n\nShort.\n"),
        encoding="utf-8",
    )
    issues = lint_wiki_tree(wiki)
    assert any(i.path == "note.md" and "missing OKF type" in i.message for i in issues)


def test_lint_index_exempt_from_okf_type(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "index.md").write_text("# Index\n", encoding="utf-8")
    issues = lint_wiki_tree(wiki)
    assert not any("missing OKF type" in i.message for i in issues)


def test_lint_orphan_okf_link(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "a.md").write_text(
        compose_page({"type": "Note", "title": "A"}, "See [missing](/missing.md).\n"),
        encoding="utf-8",
    )
    issues = lint_wiki_tree(wiki)
    assert any(i.path == "a.md" and "orphan OKF link" in i.message for i in issues)


def test_lint_okf_parent_relative_not_orphan(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    nested = wiki / "topics" / "nested"
    nested.mkdir(parents=True)
    (wiki / "topics" / "sibling.md").write_text(
        compose_page({"type": "Note", "title": "Sibling"}, "# Sibling\n"),
        encoding="utf-8",
    )
    (nested / "page.md").write_text(
        compose_page(
            {"type": "Note", "title": "Nested"},
            "See [sibling](../sibling.md).\n",
        ),
        encoding="utf-8",
    )
    issues = lint_wiki_tree(wiki)
    assert not any(
        i.path == "topics/nested/page.md" and "orphan OKF link" in i.message for i in issues
    )


def test_lint_wikilink_regression(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "a.md").write_text(
        compose_page({"type": "Note", "title": "A"}, "See [[missing]].\n"),
        encoding="utf-8",
    )
    issues = lint_wiki_tree(wiki)
    assert any(i.path == "a.md" and "orphan wikilink" in i.message for i in issues)


def test_legacy_type_missing_is_error_severity(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "note.md").write_text(
        compose_page({"title": "Note"}, "# Note\n\nShort.\n"),
        encoding="utf-8",
    )
    issues = lint_wiki_tree(wiki)
    type_issues = [i for i in issues if i.path == "note.md" and "type" in i.message.lower()]
    assert type_issues
    assert type_issues[0].severity == "error"
