"""Per-README structural templates for curated docs (`docs/readmes/_templates/`).

Module: sevn.docs.readme.templates
Depends: pathlib, re, sevn.docs.readme.manifest

Each curated README is validated against a slug-specific template that pins the
stable heading skeleton (the *outline*), while leaving prose bodies to the human
or the ``readme-curator`` agent. Templates use three markup directives:

* Real markdown headings (``#``/``##``/``###``) are **required anchors** — they
  must appear in the README in the same relative order (subsequence match).
* A heading whose text contains a wildcard token (``<``, ``…``, ``{{``) matches
  **any** heading of the same level — used for the title line.
* ``<!-- fill: … -->`` comments are agent guidance and are ignored by the
  validator. ``<!-- generated -->``/``<!-- /generated -->`` blocks mark
  pipeline-owned regions; their anchor headings are still required, but the
  variable per-module headings the pipeline emits are extra and ignored.

Exports:
    Heading — one parsed markdown heading (level + text).
    TemplateError — a single structural mismatch against a template.
    resolve_template_path — default template path for a manifest entry.
    load_template_headings — parse required headings from a template file.
    validate_against_template — check a README body against a template.

Examples:
    >>> tmpl = "# <Title>\\n## Level 1 — Overview (non-technical)\\n## References\\n"
    >>> body = "# Gateway — x\\n## Level 1 — Overview (non-technical)\\n## References\\n"
    >>> validate_against_template(tmpl, body)
    []
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from sevn.docs.readme.manifest import ReadmeEntry

_HEADING_LINE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_WILDCARD_TOKENS = ("<", "…", "{{")
_SUMMARY_MARKER = "> **Summary.**"

TEMPLATES_DIRNAME = "docs/readmes/_templates"


@dataclass(frozen=True)
class Heading:
    """One markdown heading parsed from a template or README."""

    level: int
    text: str

    @property
    def is_wildcard(self) -> bool:
        """Return True when this heading matches any heading of the same level.

        Returns:
            bool: True when the text contains a wildcard token.

        Examples:
            >>> Heading(1, "<Title>").is_wildcard
            True
            >>> Heading(2, "References").is_wildcard
            False
        """
        return any(token in self.text for token in _WILDCARD_TOKENS)


@dataclass(frozen=True)
class TemplateError:
    """A single structural mismatch between a README and its template."""

    kind: str
    detail: str

    def __str__(self) -> str:
        """Render ``kind: detail`` for gate messages.

        Returns:
            str: Human-readable one-liner.

        Examples:
            >>> str(TemplateError("missing-heading", "## References"))
            'missing-heading: ## References'
        """
        return f"{self.kind}: {self.detail}"


def resolve_template_path(repo_root: Path, entry: ReadmeEntry) -> Path:
    """Return the template path for ``entry`` (explicit key or slug convention).

        Args:
    repo_root (Path): Repository root.
    entry (ReadmeEntry): Manifest row.

        Returns:
            Path: Absolute path to the slug's template file (may not exist).

        Examples:
            >>> from sevn.docs.readme.manifest import ReadmeEntry
            >>> e = ReadmeEntry("gateway", "G", "S", "subsystem", "g", "o.md", ("a",), ())
            >>> resolve_template_path(Path("/repo"), e).as_posix()
            '/repo/docs/readmes/_templates/gateway.md'
    """
    if entry.template:
        return repo_root / entry.template
    return repo_root / TEMPLATES_DIRNAME / f"{entry.slug}.md"


def _parse_headings(text: str) -> list[Heading]:
    """Extract ordered headings from markdown, skipping fenced code and comments.

        Args:
    text (str): Markdown body.

        Returns:
            list[Heading]: Headings in document order.

        Examples:
            >>> _parse_headings("# A\\n<!-- ## B -->\\n## C\\n")
            [Heading(level=1, text='A'), Heading(level=2, text='C')]
    """
    without_comments = _HTML_COMMENT.sub("", text)
    headings: list[Heading] = []
    in_fence = False
    for line in without_comments.splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _HEADING_LINE.match(line)
        if match:
            headings.append(Heading(level=len(match.group(1)), text=match.group(2).strip()))
    return headings


def load_template_headings(path: Path) -> list[Heading]:
    """Parse the required heading anchors from a template file.

        Args:
    path (Path): Template file path.

        Returns:
            list[Heading]: Required headings in order.

        Raises:
            FileNotFoundError: When ``path`` is missing.

        Examples:
            >>> import tempfile, pathlib
            >>> p = pathlib.Path(tempfile.mkdtemp()) / "t.md"
            >>> _ = p.write_text("# <Title>\\n## References\\n", encoding="utf-8")
            >>> [h.text for h in load_template_headings(p)]
            ['<Title>', 'References']
    """
    return _parse_headings(path.read_text(encoding="utf-8"))


def _heading_matches(required: Heading, candidate: Heading) -> bool:
    """Return True when ``candidate`` satisfies the ``required`` template heading.

        Args:
    required (Heading): Template heading (may be a wildcard).
    candidate (Heading): README heading.

        Returns:
            bool: True on a level + text match.

        Examples:
            >>> _heading_matches(Heading(1, "<Title>"), Heading(1, "Gateway — x"))
            True
            >>> _heading_matches(Heading(2, "References"), Heading(2, "References"))
            True
            >>> _heading_matches(Heading(2, "References"), Heading(2, "Refs"))
            False
    """
    if required.level != candidate.level:
        return False
    if required.is_wildcard:
        return True
    return required.text == candidate.text


def validate_against_template(template_text: str, readme_text: str) -> list[TemplateError]:
    """Validate a README body against its template outline.

    The README must contain every template heading, at the same level and in the
    same relative order (a subsequence — extra headings such as per-module
    sections are allowed between anchors). When the template declares a Summary
    marker, the README must carry one too.

        Args:
    template_text (str): Template file contents.
    readme_text (str): Rendered README contents.

        Returns:
            list[TemplateError]: Empty when the README conforms.

        Examples:
            >>> t = "# <Title>\\n## Level 2 — How it works (technical)\\n## References\\n"
            >>> ok = "# G\\n## Level 2 — How it works (technical)\\n### x\\n## References\\n"
            >>> validate_against_template(t, ok)
            []
            >>> bad = "# G\\n## References\\n"
            >>> [e.kind for e in validate_against_template(t, bad)]
            ['missing-heading']
    """
    required = _parse_headings(template_text)
    present = _parse_headings(readme_text)
    errors: list[TemplateError] = []

    cursor = 0
    for req in required:
        found_at = -1
        for idx in range(cursor, len(present)):
            if _heading_matches(req, present[idx]):
                found_at = idx
                break
        if found_at < 0:
            label = "any heading" if req.is_wildcard else req.text
            prefix = "#" * req.level
            # Distinguish "exists but out of order" from "absent" for a better hint.
            exists_anywhere = any(_heading_matches(req, h) for h in present)
            kind = "out-of-order-heading" if exists_anywhere else "missing-heading"
            errors.append(TemplateError(kind, f"{prefix} {label}"))
            continue
        cursor = found_at + 1

    if _SUMMARY_MARKER in template_text and _SUMMARY_MARKER not in readme_text:
        errors.append(TemplateError("missing-summary", _SUMMARY_MARKER))

    return errors
