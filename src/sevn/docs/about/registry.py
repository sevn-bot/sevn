"""About-docs manifest registry helpers.

Module: sevn.docs.about.registry
Depends: pathlib, tomllib

Exports:
    load_manifest_entries — parse ``about-sevn.bot/_docsys/manifest.toml``.
    find_doc_path — resolve a doc id to its markdown path.
    default_manifest_path — checked-in manifest location.

Examples:
    >>> from pathlib import Path
    >>> default_manifest_path(Path(".")).name
    'manifest.toml'
"""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING, Any

from sevn.docs.about.loader import load_doc

if TYPE_CHECKING:
    from pathlib import Path


def default_manifest_path(repo_root: Path) -> Path:
    """Return ``about-sevn.bot/_docsys/manifest.toml`` under ``repo_root``.

    Args:
        repo_root (Path): Repository root.

    Returns:
        Path: Manifest file path.

    Examples:
        >>> default_manifest_path.__name__
        'default_manifest_path'
    """
    return repo_root / "about-sevn.bot" / "_docsys" / "manifest.toml"


def load_manifest_entries(repo_root: Path) -> dict[str, dict[str, Any]]:
    """Load the about-docs migration manifest keyed by doc ``id``.

    Args:
        repo_root (Path): Repository root.

    Returns:
        dict[str, dict[str, Any]]: ``id`` → manifest row mapping.

    Examples:
        >>> load_manifest_entries.__name__
        'load_manifest_entries'
    """
    path = default_manifest_path(repo_root)
    if not path.is_file():
        return {}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    rows = data.get("entry")
    if not isinstance(rows, list):
        return {}
    entries: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        doc_id = str(row.get("id", "")).strip()
        if doc_id:
            entries[doc_id] = dict(row)
    return entries


def find_doc_path(repo_root: Path, doc_id: str) -> Path | None:
    """Resolve ``doc_id`` to an on-disk about-doc markdown path.

    Scans ``about-sevn.bot/{prd,specs}/*.md`` first, then falls back to the
    manifest ``new_path`` when the migrated file is not present yet.

    Args:
        repo_root (Path): Repository root.
        doc_id (str): Stable doc id (``spec-17-gateway``, etc.).

    Returns:
        Path | None: Absolute doc path when found.

    Examples:
        >>> find_doc_path.__name__
        'find_doc_path'
    """
    for subdir in ("prd", "specs"):
        directory = repo_root / "about-sevn.bot" / subdir
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            if path.name == "README.md":
                continue
            try:
                doc, _body = load_doc(path)
            except (OSError, ValueError):
                continue
            if doc.id == doc_id:
                return path
    manifest_row = load_manifest_entries(repo_root).get(doc_id)
    if manifest_row is None:
        return None
    new_path = str(manifest_row.get("new_path", "")).strip()
    if not new_path:
        return None
    return (repo_root / new_path).resolve()
