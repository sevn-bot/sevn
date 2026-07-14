"""Manifest catalog rows for root map and INDEX.md generation.

Module: sevn.docs.readme.catalog
Depends: pathlib, sevn.docs.readme.fingerprint, sevn.docs.readme.manifest

Exports:
    CatalogRow — one subsystem/README catalog entry with staleness status.
    build_catalog_rows — manifest rows excluding ``index`` with status.
    build_subsystem_map_rows — rows for root README subsystem map table.
    build_index_rows — rows for ``INDEX.md`` entry table.

Examples:
    >>> from pathlib import Path
    >>> from sevn.docs.readme.manifest import load_manifest
    >>> m = load_manifest(Path("docs/readmes/manifest.toml"))
    >>> any(r.slug == "gateway" for r in build_catalog_rows(Path("."), m))
    True
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sevn.docs.readme.fingerprint import (
    compute_digest,
    default_fingerprints_path,
    load_fingerprints,
)
from sevn.docs.readme.links import readme_relative_href
from sevn.docs.readme.manifest import ReadmeEntry, ReadmeManifest


@dataclass(frozen=True)
class CatalogRow:
    """One README catalog row with staleness status."""

    slug: str
    title: str
    summary: str
    profile: str
    path: str
    status: str


def build_catalog_rows(
    repo_root: Path,
    manifest: ReadmeManifest,
    *,
    fingerprints_path: Path | None = None,
) -> list[CatalogRow]:
    """Build catalog rows for every manifest entry except ``index``.

        Args:
    repo_root (Path): Repository root.
    manifest (ReadmeManifest): Loaded manifest.
    fingerprints_path (Path | None): Override fingerprint store path.

        Returns:
            list[CatalogRow]: Rows with ``fresh`` or ``stale`` status.

        Examples:
            >>> from pathlib import Path as _P
            >>> from sevn.docs.readme.manifest import load_manifest
            >>> m = load_manifest(_P("docs/readmes/manifest.toml"))
            >>> rows = build_catalog_rows(_P("."), m)
            >>> any(r.slug == "gateway" for r in rows)
            True
    """
    fp_path = fingerprints_path or default_fingerprints_path(repo_root)
    store = load_fingerprints(fp_path)
    stored = store.get("entries", {})
    rows: list[CatalogRow] = []
    for entry in manifest.entries:
        if entry.slug == "index":
            continue
        rows.append(_row_for_entry(repo_root, entry, stored))
    return rows


def build_subsystem_map_rows(
    repo_root: Path,
    manifest: ReadmeManifest,
    *,
    fingerprints_path: Path | None = None,
) -> list[dict[str, str]]:
    """Build subsystem-map dicts for the root README template.

        Args:
    repo_root (Path): Repository root.
    manifest (ReadmeManifest): Loaded manifest.
    fingerprints_path (Path | None): Override fingerprint store path.

        Returns:
            list[dict[str, str]]: ``slug``, ``title``, ``summary``, ``path`` keys.

        Examples:
            >>> from pathlib import Path as _P
            >>> from sevn.docs.readme.manifest import load_manifest
            >>> m = load_manifest(_P("docs/readmes/manifest.toml"))
            >>> rows = build_subsystem_map_rows(_P("."), m)
            >>> rows and "path" in rows[0]
            True
    """
    rows: list[dict[str, str]] = []
    for row in build_catalog_rows(repo_root, manifest, fingerprints_path=fingerprints_path):
        if row.slug == "root":
            continue
        rows.append(
            {
                "slug": row.slug,
                "title": row.title,
                "summary": row.summary,
                "profile": row.profile,
                "path": row.path,
            }
        )
    return rows


def build_index_rows(
    repo_root: Path,
    manifest: ReadmeManifest,
    *,
    fingerprints_path: Path | None = None,
    embed_output: str = "docs/readmes/INDEX.md",
) -> list[dict[str, str]]:
    """Build INDEX.md table rows (all READMEs except ``index`` itself).

        Args:
    repo_root (Path): Repository root.
    manifest (ReadmeManifest): Loaded manifest.
    fingerprints_path (Path | None): Override fingerprint store path.
    embed_output (str): Output path of the INDEX README emitting row links.

        Returns:
            list[dict[str, str]]: Template variables for ``index.md.j2``.

        Examples:
            >>> from pathlib import Path as _P
            >>> from sevn.docs.readme.manifest import load_manifest
            >>> m = load_manifest(_P("docs/readmes/manifest.toml"))
            >>> rows = build_index_rows(_P("."), m)
            >>> rows and "status" in rows[0]
            True
    """
    return [
        {
            "slug": row.slug,
            "title": row.title,
            "profile": row.profile,
            "summary": row.summary,
            "path": readme_relative_href(
                readme_output=embed_output,
                target=row.path,
                repo_root=repo_root,
            ),
            "status": row.status,
        }
        for row in build_catalog_rows(repo_root, manifest, fingerprints_path=fingerprints_path)
        if row.slug != "index"
    ]


def _row_for_entry(
    repo_root: Path,
    entry: ReadmeEntry,
    stored_entries: dict[str, object],
) -> CatalogRow:
    """Build one catalog row with staleness status.

        Args:
    repo_root (Path): Repository root.
    entry (ReadmeEntry): Manifest row.
    stored_entries (dict[str, object]): Fingerprint store ``entries`` object.

        Returns:
            CatalogRow: Row with ``fresh`` or ``stale`` status.

        Examples:
            >>> from sevn.docs.readme.manifest import ReadmeEntry
            >>> row = _row_for_entry(
            ...     Path("."),
            ...     ReadmeEntry("g", "G", "S", "subsystem", "g", "docs/readmes/g.md", ("Makefile",), ()),
            ...     {},
            ... )
            >>> row.status == "stale"
            True
    """
    current = compute_digest(repo_root, entry.source_globs)
    stored_row = stored_entries.get(entry.slug)
    stored_digest = ""
    if isinstance(stored_row, dict):
        stored_digest = str(stored_row.get("digest", ""))
    status = "fresh" if stored_digest == current else "stale"
    return CatalogRow(
        slug=entry.slug,
        title=entry.title,
        summary=entry.summary,
        profile=entry.profile,
        path=_public_path(entry.output),
        status=status,
    )


def _public_path(output: str) -> str:
    """Normalize manifest output path for markdown links.

        Args:
    output (str): Manifest ``output`` field.

        Returns:
            str: Repo-relative path suitable for markdown links.

        Examples:
            >>> _public_path("README.md")
            'README.md'
            >>> _public_path("docs/readmes/gateway.md")
            'docs/readmes/gateway.md'
    """
    return output.replace("\\", "/").lstrip("/")
