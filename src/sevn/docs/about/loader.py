"""Frontmatter load/dump helpers for about-docs markdown files.

Module: sevn.docs.about.loader
Depends: pathlib, re, yaml, sevn.docs.about.model

Exports:
    split_frontmatter — split leading ``---`` YAML block and body.
    load_doc — read one markdown file into ``(AboutDoc, body)``.
    dump_doc — serialise ``(AboutDoc, body)`` back to markdown.

Examples:
    >>> from sevn.docs.about.loader import split_frontmatter
    >>> fm, body = split_frontmatter("---\\nid: x\\n---\\n\\nbody")
    >>> fm["id"]
    'x'
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import yaml

from sevn.docs.about.model import AboutDoc

if TYPE_CHECKING:
    from pathlib import Path

_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z",
    re.DOTALL | re.MULTILINE,
)


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split leading ``---`` YAML frontmatter from the markdown body.

    Args:
        text (str): Full markdown file contents.

    Returns:
        tuple[dict[str, Any], str]: Parsed frontmatter mapping and body text.

    Raises:
        ValueError: When the file does not begin with YAML frontmatter fences.

    Examples:
        >>> split_frontmatter("---\\nid: spec-17-gateway\\n---\\n\\n## Body")[1].strip()
        '## Body'
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        msg = "missing YAML frontmatter (expected leading --- block)"
        raise ValueError(msg)
    raw_yaml = match.group(1)
    body = match.group(2)
    loaded = yaml.safe_load(raw_yaml) or {}
    if not isinstance(loaded, dict):
        msg = "frontmatter YAML must be a mapping"
        raise ValueError(msg)
    return dict(loaded), body


def load_doc(path: Path) -> tuple[AboutDoc, str]:
    """Read one about-doc markdown file and validate its frontmatter.

    Args:
        path (Path): Markdown file path.

    Returns:
        tuple[AboutDoc, str]: Validated frontmatter model and markdown body.

    Raises:
        ValueError: When frontmatter is missing or invalid YAML.
        pydantic.ValidationError: When frontmatter fails model validation.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> td = Path(tempfile.mkdtemp())
        >>> p = td / "doc.md"
        >>> _ = p.write_text(
        ...     "---\\n"
        ...     "id: spec-17-gateway\\n"
        ...     "kind: spec\\n"
        ...     "title: Gateway\\n"
        ...     "status: done\\n"
        ...     "owner: Alex\\n"
        ...     "summary: Turn spine.\\n"
        ...     "last_updated: 2026-06-19\\n"
        ...     "parent_prd: prd-01-conversational-experience\\n"
        ...     "sources:\\n  - src/sevn/gateway/**\\n"
        ...     "---\\n\\n## Body\\n",
        ...     encoding="utf-8",
        ... )
        >>> doc, body = load_doc(p)
        >>> doc.id == "spec-17-gateway" and body.strip().startswith("## Body")
        True
    """
    text = path.read_text(encoding="utf-8")
    frontmatter, body = split_frontmatter(text)
    return AboutDoc.model_validate(frontmatter), body


def dump_doc(doc: AboutDoc, body: str) -> str:
    """Serialise frontmatter and body into one markdown document.

    Args:
        doc (AboutDoc): Validated frontmatter model.
        body (str): Markdown body after the closing ``---`` fence.

    Returns:
        str: Full markdown text with YAML frontmatter block.

    Examples:
        >>> from datetime import date
        >>> from sevn.docs.about.model import AboutDoc
        >>> doc = AboutDoc(
        ...     id="spec-17-gateway",
        ...     kind="spec",
        ...     title="Gateway",
        ...     status="done",
        ...     owner="Alex",
        ...     summary="Turn spine.",
        ...     last_updated=date(2026, 6, 19),
        ...     parent_prd="prd-01-conversational-experience",
        ...     sources=["src/sevn/gateway/**"],
        ... )
        >>> dump_doc(doc, "## Body\\n").startswith("---\\n")
        True
    """
    payload = doc.model_dump(mode="json")
    yaml_block = yaml.safe_dump(
        payload,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    ).rstrip("\n")
    normalized_body = body if body.startswith("\n") or not body else f"\n{body}"
    if not normalized_body.endswith("\n") and normalized_body:
        normalized_body = f"{normalized_body}\n"
    return f"---\n{yaml_block}\n---\n{normalized_body}"
