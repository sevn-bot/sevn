"""Tests for FAQ data model, validation, and markdown rendering."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sevn.docs.faq import (
    MIN_ANSWER_WORDS,
    Document,
    Question,
    Reference,
    Section,
    load_document,
    render_markdown,
    slugify,
    validate_document,
)

LONG_ANSWER = " ".join(["word"] * (MIN_ANSWER_WORDS + 5)) + " see {{ref:r}}."


def _repo_with_target() -> Path:
    td = Path(tempfile.mkdtemp())
    target = td / "docs" / "target.md"
    target.parent.mkdir(parents=True)
    target.write_text("# Target\n", encoding="utf-8")
    return td


def _valid_question(question_id: str = "q1") -> Question:
    return Question(
        id=question_id,
        question="What is this?",
        answer=LONG_ANSWER,
        references={"r": Reference(path="docs/target.md", text="target doc")},
    )


def test_load_document_parses_nested_structure() -> None:
    """load_document turns raw JSON into typed Section/Question/Reference objects."""
    raw = {
        "title": "FAQ",
        "sections": [
            {
                "id": "general",
                "title": "General",
                "questions": [
                    {
                        "id": "q1",
                        "question": "What is it?",
                        "answer": "See {{ref:r}}.",
                        "references": {"r": {"path": "README.md", "text": "readme"}},
                    },
                ],
            },
        ],
    }
    document = load_document(raw)
    assert document.title == "FAQ"
    assert document.sections[0].id == "general"
    question = document.sections[0].questions[0]
    assert question.id == "q1"
    assert question.references["r"] == Reference(path="README.md", text="readme")


def test_validate_document_empty_sections_is_error() -> None:
    """A document with no sections fails validation with a clear message."""
    errors = validate_document(Document(title="FAQ", sections=[]), repo_root=Path("."))
    assert errors == ["document has no sections"]


def test_validate_document_accepts_well_formed_question() -> None:
    """A question with a '?' ending, enough words, and a resolvable ref passes."""
    repo_root = _repo_with_target()
    section = Section(id="general", title="General", questions=[_valid_question()])
    document = Document(title="FAQ", sections=[section])
    assert validate_document(document, repo_root=repo_root) == []


def test_validate_document_rejects_missing_question_mark() -> None:
    """Questions must end with '?'."""
    repo_root = _repo_with_target()
    bad = Question(
        id="q1",
        question="What is this",
        answer=LONG_ANSWER,
        references={"r": Reference(path="docs/target.md", text="target doc")},
    )
    section = Section(id="general", title="General", questions=[bad])
    errors = validate_document(Document(title="FAQ", sections=[section]), repo_root=repo_root)
    assert any("must end with '?'" in e for e in errors)


def test_validate_document_rejects_short_answer() -> None:
    """Answers below MIN_ANSWER_WORDS fail validation."""
    repo_root = _repo_with_target()
    bad = Question(
        id="q1",
        question="What is this?",
        answer="Too short, see {{ref:r}}.",
        references={"r": Reference(path="docs/target.md", text="target doc")},
    )
    section = Section(id="general", title="General", questions=[bad])
    errors = validate_document(Document(title="FAQ", sections=[section]), repo_root=repo_root)
    assert any("needs at least" in e for e in errors)


def test_validate_document_requires_reference_placeholder() -> None:
    """An answer with no {{ref:...}} placeholder fails validation."""
    repo_root = _repo_with_target()
    bad = Question(
        id="q1",
        question="What is this?",
        answer=" ".join(["word"] * (MIN_ANSWER_WORDS + 5)) + ".",
        references={},
    )
    section = Section(id="general", title="General", questions=[bad])
    errors = validate_document(Document(title="FAQ", sections=[section]), repo_root=repo_root)
    assert any("must contain at least one" in e for e in errors)


def test_validate_document_rejects_unknown_reference_id() -> None:
    """A placeholder pointing at a missing reference id fails validation."""
    repo_root = _repo_with_target()
    bad = Question(
        id="q1",
        question="What is this?",
        answer=" ".join(["word"] * (MIN_ANSWER_WORDS + 5)) + " see {{ref:missing}}.",
        references={},
    )
    section = Section(id="general", title="General", questions=[bad])
    errors = validate_document(Document(title="FAQ", sections=[section]), repo_root=repo_root)
    assert any("unknown ref id" in e for e in errors)


def test_validate_document_rejects_missing_reference_file() -> None:
    """A reference path that does not exist on disk fails validation."""
    repo_root = _repo_with_target()
    bad = Question(
        id="q1",
        question="What is this?",
        answer=LONG_ANSWER,
        references={"r": Reference(path="docs/does-not-exist.md", text="missing")},
    )
    section = Section(id="general", title="General", questions=[bad])
    errors = validate_document(Document(title="FAQ", sections=[section]), repo_root=repo_root)
    assert any("does not exist" in e for e in errors)


def test_validate_document_rejects_disallowed_extension() -> None:
    """A reference path with a disallowed extension fails validation."""
    repo_root = _repo_with_target()
    binary = repo_root / "docs" / "image.png"
    binary.write_bytes(b"\x89PNG")
    bad = Question(
        id="q1",
        question="What is this?",
        answer=LONG_ANSWER.replace("{{ref:r}}", "{{ref:img}}"),
        references={"img": Reference(path="docs/image.png", text="image")},
    )
    section = Section(id="general", title="General", questions=[bad])
    errors = validate_document(Document(title="FAQ", sections=[section]), repo_root=repo_root)
    assert any("disallowed extension" in e for e in errors)


def test_validate_document_rejects_duplicate_ids() -> None:
    """Duplicate question ids across sections fail validation."""
    repo_root = _repo_with_target()
    section = Section(
        id="general",
        title="General",
        questions=[_valid_question("dup"), _valid_question("dup")],
    )
    errors = validate_document(Document(title="FAQ", sections=[section]), repo_root=repo_root)
    assert any("duplicate question id" in e for e in errors)


def test_validate_document_rejects_reference_escaping_repo_root() -> None:
    """A reference path that resolves outside the repo root fails validation."""
    repo_root = _repo_with_target()
    bad = Question(
        id="q1",
        question="What is this?",
        answer=LONG_ANSWER,
        references={"r": Reference(path="../outside.md", text="outside")},
    )
    section = Section(id="general", title="General", questions=[bad])
    errors = validate_document(Document(title="FAQ", sections=[section]), repo_root=repo_root)
    assert any("escapes repo root" in e for e in errors)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Frequently Asked Questions (FAQ)", "frequently-asked-questions-faq"),
        ("What is sevn.bot?", "what-is-sevnbot"),
    ],
)
def test_slugify_matches_github_anchor_style(text: str, expected: str) -> None:
    """slugify produces GitHub-compatible heading anchors."""
    assert slugify(text) == expected


def test_render_markdown_resolves_placeholders_and_includes_toc() -> None:
    """render_markdown resolves {{ref:...}} to links and lists every question in the TOC."""
    question = _valid_question()
    section = Section(id="general", title="General", questions=[question])
    document = Document(title="Frequently Asked Questions (FAQ)", sections=[section])
    markdown = render_markdown(document)
    assert "generated: do not edit by hand" in markdown
    assert "[target doc](target.md)" in markdown
    assert "{{ref:" not in markdown
    assert "### What is this?" in markdown
    assert "[General](#general)" in markdown
