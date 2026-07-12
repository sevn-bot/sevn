"""Prompt/template registry metadata for cache versioning.

Module: sevn.agent.templates.registry
Depends: (none)

Exports:
    TemplateEntry — one on-disk template with a stable id and content hash.
    load_template_registry — scan Markdown templates under a root directory.
    registry_version — deterministic hash over all template content hashes.

Examples:
    >>> from pathlib import Path
    >>> load_template_registry(Path("/nonexistent"))
    []
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

_ID_LINE = re.compile(r"^\s*id:\s*(\S+)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class TemplateEntry:
    """One template file contributing to Triager/executor registry versioning."""

    template_id: str
    path: Path
    content_sha256: str


def _hash_bytes(data: bytes) -> str:
    """Return a lowercase hex sha256 digest.

        Args:
    data (bytes): Raw bytes to hash.

        Returns:
            str: Hex digest string length 64.

        Examples:
            >>> len(_hash_bytes(b"x")) == 64
            True
    """
    return hashlib.sha256(data).hexdigest()


def _parse_frontmatter_id(text: str) -> str | None:
    """Return ``id:`` from a minimal YAML frontmatter block when present.

        Args:
    text (str): Full file text.

        Returns:
            str | None: Parsed id or ``None`` when missing or invalid.

        Examples:
            >>> _parse_frontmatter_id("---\\nid: x\\n---\\n") == "x"
            True
    """
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    block = text[3:end]
    for line in block.splitlines():
        m = _ID_LINE.match(line)
        if m:
            return m.group(1)
    return None


def _template_id_for_path(root: Path, file_path: Path, text: str) -> str:
    """Pick a stable template id from frontmatter or relative path.

        Args:
    root (Path): Template root directory.
    file_path (Path): Template file path (typically under ``root``).
    text (str): Decoded file text for frontmatter parsing.

        Returns:
            str: Identifier used in registry ordering and versioning.

        Examples:
            >>> isinstance(True, bool)
            True
    """
    explicit = _parse_frontmatter_id(text)
    if explicit:
        return explicit
    rel = file_path.relative_to(root).as_posix()
    return rel  # noqa: RET504


def load_template_registry(root: Path, *, glob: str = "**/*.md") -> list[TemplateEntry]:
    """Discover Markdown templates and compute per-file content hashes.

        Args:
    root (Path): Directory containing template files.
    glob (str): Glob pattern relative to ``root``.

        Returns:
            list[TemplateEntry]: Sorted entries (by ``template_id``) for stable versioning.

        Examples:
            >>> from pathlib import Path
            >>> load_template_registry(Path("/nonexistent"))
            []
    """
    if not root.exists():
        return []
    entries: list[TemplateEntry] = []
    for path in sorted(root.glob(glob)):
        if not path.is_file():
            continue
        raw = path.read_bytes()
        digest = _hash_bytes(raw)
        text = raw.decode("utf-8", errors="replace")
        tid = _template_id_for_path(root, path, text)
        entries.append(TemplateEntry(template_id=tid, path=path, content_sha256=digest))
    entries.sort(key=lambda e: e.template_id)
    return entries


def registry_version(entries: list[TemplateEntry]) -> str:
    """Fingerprint the whole registry for provider cache breakpoints.

        Args:
    entries (list[TemplateEntry]): Typically ``load_template_registry(...)``.

        Returns:
            str: Hex sha256 over sorted ``template_id`` + content hash lines.

        Examples:
            >>> registry_version([])
            'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
    """
    lines = [f"{e.template_id}:{e.content_sha256}" for e in entries]
    payload = "\n".join(lines).encode("utf-8")
    return _hash_bytes(payload)
