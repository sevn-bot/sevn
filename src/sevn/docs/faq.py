"""FAQ data model, validation, and markdown rendering (docs/faq/qa_input.json).

Module: sevn.docs.faq
Depends: __future__, dataclasses, pathlib, re

Operators edit ``docs/faq/qa_input.json``; ``scripts/generate_faq.py`` (via this
module) validates it and renders ``docs/FAQ.md``. Each answer must embed at least
one ``{{ref:<id>}}`` placeholder resolved from that question's ``references`` map
to a real, allowed-extension file in the repo — this is how every answer carries
a working link back into the codebase instead of floating free-form prose.

Exports:
    Reference — One named reference (repo-relative path + display text).
    Question — One Q&A pair with its references.
    Section — A named group of questions (e.g. "General", "Technical Q&A").
    Document — The full parsed ``qa_input.json`` (title + sections).
    load_document — Parse raw JSON into a ``Document``.
    validate_document — Return human-readable errors for a ``Document``.
    render_markdown — Render a validated ``Document`` to GitHub-flavored markdown.
    slugify — GitHub-style heading anchor slug.

Examples:
    >>> doc = load_document({"title": "FAQ", "sections": []})
    >>> isinstance(doc, Document)
    True
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MIN_ANSWER_WORDS = 20
MIN_QUESTION_WORDS = 3

ALLOWED_REFERENCE_EXTENSIONS = frozenset(
    {
        ".md",
        ".html",
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".json",
        ".toml",
        ".yaml",
        ".yml",
        ".sh",
        ".css",
    },
)

_REF_PATTERN = re.compile(r"\{\{ref:([a-zA-Z0-9_-]+)\}\}")
_GENERATED_HEADER = "<!-- generated: do not edit by hand; run `make faq-generate` -->"


@dataclass(frozen=True)
class Reference:
    """One named reference: a repo-relative path plus its link display text.

    Examples:
        >>> Reference(path="README.md", text="root README").path
        'README.md'
    """

    path: str
    text: str


@dataclass(frozen=True)
class Question:
    """One FAQ question/answer pair with its reference map.

    Examples:
        >>> q = Question(id="q1", question="What?", answer="A.", references={})
        >>> q.id
        'q1'
    """

    id: str
    question: str
    answer: str
    references: dict[str, Reference] = field(default_factory=dict)


@dataclass(frozen=True)
class Section:
    """A named group of FAQ questions (rendered as one ``##`` heading).

    Examples:
        >>> Section(id="general", title="General", questions=[]).id
        'general'
    """

    id: str
    title: str
    questions: list[Question] = field(default_factory=list)


@dataclass(frozen=True)
class Document:
    """The full parsed ``qa_input.json`` document.

    Examples:
        >>> Document(title="FAQ", sections=[]).title
        'FAQ'
    """

    title: str
    sections: list[Section] = field(default_factory=list)


def load_document(raw: dict[str, Any]) -> Document:
    """Parse a raw ``qa_input.json`` dict into a ``Document``.

    Args:
        raw (dict[str, Any]): Deserialized JSON (``{"title": ..., "sections": [...]}}``).

    Returns:
        Document: Parsed sections/questions/references. Malformed entries
        (non-dict sections/questions/references, missing fields) are dropped
        or defaulted rather than raising, so structural problems surface as
        ``validate_document`` errors instead of parser exceptions.

    Examples:
        >>> raw = {
        ...     "title": "FAQ",
        ...     "sections": [
        ...         {
        ...             "id": "general",
        ...             "title": "General",
        ...             "questions": [
        ...                 {
        ...                     "id": "q1",
        ...                     "question": "What is it?",
        ...                     "answer": "See {{ref:r}}.",
        ...                     "references": {"r": {"path": "README.md", "text": "readme"}},
        ...                 },
        ...             ],
        ...         },
        ...     ],
        ... }
        >>> load_document(raw).sections[0].questions[0].id
        'q1'
    """
    sections_raw = raw.get("sections", [])
    if not isinstance(sections_raw, list):
        sections_raw = []
    sections: list[Section] = []
    for raw_section in sections_raw:
        if not isinstance(raw_section, dict):
            continue
        questions_raw = raw_section.get("questions", [])
        if not isinstance(questions_raw, list):
            questions_raw = []
        questions: list[Question] = []
        for raw_question in questions_raw:
            if not isinstance(raw_question, dict):
                continue
            references_raw = raw_question.get("references", {})
            if not isinstance(references_raw, dict):
                references_raw = {}
            references: dict[str, Reference] = {}
            for ref_id, ref in references_raw.items():
                if not isinstance(ref, dict):
                    continue
                references[ref_id] = Reference(
                    path=str(ref.get("path", "")),
                    text=str(ref.get("text", "")),
                )
            questions.append(
                Question(
                    id=str(raw_question.get("id", "")),
                    question=str(raw_question.get("question", "")),
                    answer=str(raw_question.get("answer", "")),
                    references=references,
                ),
            )
        sections.append(
            Section(
                id=str(raw_section.get("id", "")),
                title=str(raw_section.get("title", "")),
                questions=questions,
            ),
        )
    title = raw.get("title", "Frequently Asked Questions (FAQ)")
    return Document(title=str(title), sections=sections)


def _validate_reference(
    ref_id: str,
    ref: Reference,
    *,
    question_id: str,
    repo_root: Path,
) -> list[str]:
    """Return errors for one reference's path (existence + allowed extension).

    Args:
        ref_id (str): Reference id (key in the question's ``references`` map).
        ref (Reference): The reference to validate.
        question_id (str): Owning question id (for error messages).
        repo_root (Path): Repository root used to resolve ``ref.path``.

    Returns:
        list[str]: Human-readable errors; empty when the reference is valid.

    Examples:
        >>> _validate_reference(
        ...     "r", Reference(path="does/not/exist.md", text="x"),
        ...     question_id="q1", repo_root=Path("."),
        ... )[0].startswith("q1")
        True
    """
    errors: list[str] = []
    suffix = Path(ref.path).suffix.lower()
    if suffix not in ALLOWED_REFERENCE_EXTENSIONS:
        errors.append(
            f"{question_id}: reference {ref_id!r} has disallowed extension {suffix or '(none)'!r} "
            f"({ref.path})",
        )
    target = (repo_root / ref.path).resolve()
    try:
        target.relative_to(repo_root.resolve())
    except ValueError:
        errors.append(f"{question_id}: reference {ref_id!r} escapes repo root ({ref.path})")
        return errors
    if not target.is_file():
        errors.append(f"{question_id}: reference {ref_id!r} path does not exist ({ref.path})")
    if not ref.text.strip():
        errors.append(f"{question_id}: reference {ref_id!r} has empty display text")
    return errors


def _validate_question(question: Question, *, repo_root: Path) -> list[str]:
    """Return formatting/word-count/reference errors for one question.

    Args:
        question (Question): Question to validate.
        repo_root (Path): Repository root used to resolve reference paths.

    Returns:
        list[str]: Human-readable errors; empty when the question is valid.

    Examples:
        >>> bad = Question(id="q1", question="No mark", answer="Too short.", references={})
        >>> len(_validate_question(bad, repo_root=Path("."))) > 0
        True
    """
    errors: list[str] = []
    qid = question.id or "<missing id>"

    if not question.id:
        errors.append("question is missing an 'id'")
    if not question.question.strip():
        errors.append(f"{qid}: question text is empty")
    elif not question.question.strip().endswith("?"):
        errors.append(f"{qid}: question must end with '?' ({question.question!r})")
    elif len(question.question.split()) < MIN_QUESTION_WORDS:
        errors.append(f"{qid}: question has fewer than {MIN_QUESTION_WORDS} words")

    answer = question.answer.strip()
    if not answer:
        errors.append(f"{qid}: answer text is empty")
        return errors

    word_count = len(_REF_PATTERN.sub("", answer).split())
    if word_count < MIN_ANSWER_WORDS:
        errors.append(
            f"{qid}: answer has {word_count} words, needs at least {MIN_ANSWER_WORDS}",
        )

    placeholder_ids = _REF_PATTERN.findall(answer)
    if not placeholder_ids:
        errors.append(f"{qid}: answer must contain at least one '{{{{ref:<id>}}}}' placeholder")

    for ref_id in placeholder_ids:
        if ref_id not in question.references:
            errors.append(f"{qid}: answer references unknown ref id {ref_id!r}")

    for ref_id, ref in question.references.items():
        errors.extend(_validate_reference(ref_id, ref, question_id=qid, repo_root=repo_root))

    return errors


def validate_document(document: Document, *, repo_root: Path) -> list[str]:
    """Return all validation errors for a parsed FAQ ``Document``.

    Checks: unique section/question ids, question formatting (ends with '?',
    minimum word count), answer minimum word count, at least one resolvable
    ``{{ref:<id>}}`` placeholder per answer, and that every reference points to
    an existing, allowed-extension file in the repo.

    Args:
        document (Document): Parsed FAQ document.
        repo_root (Path): Repository root used to resolve reference paths.

    Returns:
        list[str]: Human-readable errors; empty when the document is valid.

    Examples:
        >>> validate_document(Document(title="FAQ", sections=[]), repo_root=Path("."))
        ['document has no sections']
    """
    errors: list[str] = []
    if not document.sections:
        return ["document has no sections"]

    seen_section_ids: set[str] = set()
    seen_question_ids: set[str] = set()

    for section in document.sections:
        if not section.id:
            errors.append("section is missing an 'id'")
        elif section.id in seen_section_ids:
            errors.append(f"duplicate section id {section.id!r}")
        else:
            seen_section_ids.add(section.id)

        if not section.title.strip():
            errors.append(f"{section.id or '<missing id>'}: section is missing a 'title'")

        if not section.questions:
            errors.append(f"{section.id or '<missing id>'}: section has no questions")

        for question in section.questions:
            if question.id in seen_question_ids:
                errors.append(f"duplicate question id {question.id!r}")
            elif question.id:
                seen_question_ids.add(question.id)
            errors.extend(_validate_question(question, repo_root=repo_root))

    return errors


def slugify(text: str) -> str:
    """Return a GitHub-style heading anchor slug for ``text``.

    Args:
        text (str): Heading text without leading ``#`` markers.

    Returns:
        str: Lowercase, hyphenated anchor slug matching GitHub's algorithm.

    Examples:
        >>> slugify("Frequently Asked Questions (FAQ)")
        'frequently-asked-questions-faq'
    """
    slug = re.sub(r"[^\w\s-]", "", text.strip().lower())
    slug = re.sub(r"\s+", "-", slug)
    return slug.strip("-")


def _relative_href(*, output_path: str, target_path: str) -> str:
    """Return a POSIX path from ``output_path``'s directory to ``target_path``.

    Both paths are repo-relative; this lets ``qa_input.json`` reference files by
    their repo-root path while the rendered markdown gets a working relative link
    regardless of where the generated file lives (e.g. ``docs/FAQ.md``).

    Args:
        output_path (str): Repo-relative path of the file being rendered.
        target_path (str): Repo-relative path of the link target.

    Returns:
        str: POSIX-style relative path suitable for a markdown link.

    Examples:
        >>> _relative_href(output_path="docs/FAQ.md", target_path="README.md")
        '../README.md'
    """
    output_dir = Path(output_path).parent
    return Path(os.path.relpath(target_path, output_dir)).as_posix()


def _render_answer(question: Question, *, output_path: str) -> str:
    """Return ``question.answer`` with ``{{ref:<id>}}`` placeholders resolved to links.

    Args:
        question (Question): Question whose answer/references to render.
        output_path (str): Repo-relative path of the file being rendered, used to
            compute a working relative link from each repo-root-relative reference.

    Returns:
        str: Answer text with every placeholder replaced by a markdown link.

    Examples:
        >>> q = Question(
        ...     id="q1", question="What?", answer="See {{ref:r}}.",
        ...     references={"r": Reference(path="README.md", text="the README")},
        ... )
        >>> _render_answer(q, output_path="docs/FAQ.md")
        'See [the README](../README.md).'
    """

    def _replace(match: re.Match[str]) -> str:
        """Return the markdown link for one ``{{ref:<id>}}`` regex match.

        Args:
            match (re.Match[str]): Match whose group 1 is the reference id.

        Returns:
            str: Rendered ``[text](href)`` markdown link.

        Examples:
            >>> import re
            >>> q = Question(
            ...     id="q1", question="What?", answer="See {{ref:r}}.",
            ...     references={"r": Reference(path="README.md", text="the README")},
            ... )
            >>> _render_answer(q, output_path="docs/FAQ.md")
            'See [the README](../README.md).'
        """
        ref = question.references[match.group(1)]
        href = _relative_href(output_path=output_path, target_path=ref.path)
        return f"[{ref.text}]({href})"

    return _REF_PATTERN.sub(_replace, question.answer)


def _unique_heading_slugs(document: Document) -> dict[str, str]:
    """Return a GitHub-deduplicated heading slug for every section/question.

    GitHub disambiguates repeated heading text within one page by appending
    ``-1``, ``-2``, ... to later occurrences (in document order), leaving the
    first occurrence unchanged. Both the table of contents and the actual
    ``##``/``###`` headings must agree on these slugs, so this is computed
    once up front and looked up by a stable ``section:<id>`` / ``question:<id>``
    key in both rendering passes.

    Args:
        document (Document): Parsed FAQ document.

    Returns:
        dict[str, str]: Maps ``f"section:{section.id}"`` and
        ``f"question:{question.id}"`` to their deduplicated anchor slug.

    Examples:
        >>> q1 = Question(id="q1", question="What?", answer="A.", references={})
        >>> q2 = Question(id="q2", question="What?", answer="B.", references={})
        >>> section = Section(id="s", title="S", questions=[q1, q2])
        >>> slugs = _unique_heading_slugs(Document(title="FAQ", sections=[section]))
        >>> (slugs["question:q1"], slugs["question:q2"])
        ('what', 'what-1')
    """
    counts: dict[str, int] = {}
    slugs: dict[str, str] = {}

    def _assign(key: str, text: str) -> None:
        base = slugify(text)
        count = counts.get(base, 0)
        slugs[key] = base if count == 0 else f"{base}-{count}"
        counts[base] = count + 1

    for section in document.sections:
        _assign(f"section:{section.id}", section.title)
        for question in section.questions:
            _assign(f"question:{question.id}", question.question)

    return slugs


def render_markdown(document: Document, *, output_path: str = "docs/FAQ.md") -> str:
    """Render a validated FAQ ``Document`` to GitHub-flavored markdown.

    Args:
        document (Document): Parsed (and validated) FAQ document.
        output_path (str): Repo-relative path the markdown will be written to;
            used to turn each repo-root-relative reference into a working
            relative link.

    Returns:
        str: Full markdown file body, including the generated-file header,
        title, table of contents, and one ``###`` per question grouped under
        ``##`` section headings.

    Examples:
        >>> q = Question(
        ...     id="q1", question="What is it?", answer="It is a thing, see {{ref:r}}.",
        ...     references={"r": Reference(path="README.md", text="README")},
        ... )
        >>> section = Section(id="general", title="General", questions=[q])
        >>> doc = Document(title="FAQ", sections=[section])
        >>> "### What is it?" in render_markdown(doc)
        True
    """
    lines: list[str] = [_GENERATED_HEADER, "", f"# {document.title}", ""]
    slugs = _unique_heading_slugs(document)

    lines.append("## Table of contents")
    lines.append("")
    for section in document.sections:
        lines.append(f"- [{section.title}](#{slugs[f'section:{section.id}']})")
        for question in section.questions:
            lines.append(f"  - [{question.question}](#{slugs[f'question:{question.id}']})")
    lines.append("")

    for section in document.sections:
        lines.append(f"## {section.title}")
        lines.append("")
        for question in section.questions:
            lines.append(f"### {question.question}")
            lines.append("")
            lines.append(_render_answer(question, output_path=output_path))
            lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"
