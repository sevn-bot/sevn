"""Deterministic README scaffold for failing trees (`make readme-scaffold`).

Module: sevn.docs.readme.scaffold
Depends: asyncio, pathlib, re, sevn.docs.readme.check, sevn.docs.readme.fingerprint,
    sevn.docs.readme.manifest, sevn.docs.readme.profile_schemas, sevn.docs.readme.providers,
    sevn.docs.readme.render

Exports:
    scaffold_readme_tree — offline regenerate + insert missing section stubs.

Examples:
    >>> from pathlib import Path
    >>> from sevn.docs.readme.manifest import load_manifest
    >>> m = load_manifest(Path("docs/readmes/manifest.toml"))
    >>> isinstance(scaffold_readme_tree(Path("."), m), int)
    True
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from sevn.docs.readme.catalog import build_catalog_rows
from sevn.docs.readme.check import _has_heading
from sevn.docs.readme.fingerprint import default_fingerprints_path, stamp_entry
from sevn.docs.readme.manifest import ReadmeEntry, ReadmeManifest
from sevn.docs.readme.profile_schemas import ProfileSchema, get_profile_schema
from sevn.docs.readme.providers import ReadmeProviderConfig
from sevn.docs.readme.render import write_readme

_SUMMARY_MARKERS = ("> **Summary.**", "## Summary")
_STUB_BODY = "TODO: fill this section (run `sevn readme update {slug}`)."
_GUIDE_STEP_STUB = "## TODO — step\n\nTODO: add operator steps for `{slug}`.\n\n"


def scaffold_readme_tree(
    repo_root: Path,
    manifest: ReadmeManifest,
    *,
    fingerprints_path: Path | None = None,
    provider_config: ReadmeProviderConfig | None = None,
) -> int:
    """Bring README files toward green: regenerate missing/stale, stub missing sections.

    Curated manifest entries (``curated = true``) are never rewritten: when stale,
    only ``_fingerprints.json`` is refreshed via ``stamp_entry``; section stubs are
    skipped even when the file exists.

        Args:
    repo_root (Path): Repository root.
    manifest (ReadmeManifest): Loaded manifest.
    fingerprints_path (Path | None): Override fingerprint store path.
    provider_config (ReadmeProviderConfig | None): Offline provider config.

        Returns:
            int: Number of files written, sections stubbed, or curated fingerprints stamped.

        Examples:
            >>> from pathlib import Path as _P
            >>> from sevn.docs.readme.manifest import load_manifest
            >>> m = load_manifest(_P("docs/readmes/manifest.toml"))
            >>> scaffold_readme_tree(_P("."), m) >= 0
            True
    """
    repo_root = repo_root.resolve()
    fp_path = fingerprints_path or default_fingerprints_path(repo_root)
    config = provider_config or ReadmeProviderConfig(offline=True)
    catalog = build_catalog_rows(repo_root, manifest, fingerprints_path=fp_path)
    status_by_slug = {row.slug: row.status for row in catalog}
    inserted = 0

    for entry in manifest.entries:
        output = repo_root / entry.output
        stale = status_by_slug.get(entry.slug) == "stale"
        if entry.curated:
            if stale:
                stamp_entry(
                    repo_root,
                    slug=entry.slug,
                    source_globs=entry.source_globs,
                    fingerprints_path=fp_path,
                )
                inserted += 1
            continue
        if not output.is_file() or stale:
            asyncio.run(
                write_readme(
                    repo_root=repo_root,
                    entry=entry,
                    config=config,
                    fingerprints_path=fp_path,
                    manifest=manifest,
                )
            )
            inserted += 1
            continue

        schema = get_profile_schema(entry.profile)
        text = output.read_text(encoding="utf-8")
        updated, n = _insert_section_stubs(entry, text, schema)
        if n:
            output.write_text(updated, encoding="utf-8")
            inserted += n

    return inserted


def _insert_section_stubs(
    entry: ReadmeEntry,
    text: str,
    schema: ProfileSchema,
) -> tuple[str, int]:
    """Insert TODO stubs for missing profile sections without overwriting prose.

        Args:
    entry (ReadmeEntry): Manifest row.
    text (str): Existing README body.
    schema (ProfileSchema): §C0 schema.

        Returns:
            tuple[str, int]: Updated text and stub count.

        Examples:
            >>> from sevn.docs.readme.profile_schemas import get_profile_schema
            >>> from sevn.docs.readme.manifest import ReadmeEntry
            >>> e = ReadmeEntry("g", "G", "S", "subsystem", "g", "o.md", ("a",), ())
            >>> body = "> **Summary.** s\\n\\n## References\\n"
            >>> out, n = _insert_section_stubs(e, body, get_profile_schema("subsystem"))
            >>> n >= 1
            True
    """
    updated = text
    count = 0

    if schema.requires_summary and not any(marker in updated for marker in _SUMMARY_MARKERS):
        updated = _insert_after_generation_stamp(
            updated,
            f"> **Summary.** {entry.summary}\n\n",
        )
        count += 1

    for heading in schema.required_headings:
        if _has_heading(updated, heading):
            continue
        stub = f"## {heading}\n\n{_STUB_BODY.format(slug=entry.slug)}\n\n"
        updated = _insert_before_references(updated, stub)
        count += 1

    if schema.requires_table and not re.search(r"^\|.+\|.+\|", updated, re.MULTILINE):
        table_stub = (
            "| Name | Path | Summary |\n"
            "|------|------|---------|\n"
            f"| TODO | `{entry.slug}` | {_STUB_BODY.format(slug=entry.slug)} |\n\n"
        )
        updated = _insert_before_references(updated, table_stub)
        count += 1

    if schema.requires_step_sections:
        skip = {"summary", "references"}
        has_step = False
        for match in re.finditer(r"^##\s+(.+)$", updated, re.MULTILINE):
            title = match.group(1).strip().split("—", 1)[0].strip().lower()
            if title not in skip:
                has_step = True
                break
        if not has_step:
            updated = _insert_before_references(updated, _GUIDE_STEP_STUB.format(slug=entry.slug))
            count += 1

    if entry.profile == "index" and not updated.lstrip().startswith("#"):
        updated = f"# {entry.title}\n\n{updated}"
        count += 1

    return updated, count


def _insert_after_generation_stamp(text: str, block: str) -> str:
    """Insert ``block`` after the generated HTML comment when present.

        Args:
    text (str): README body.
    block (str): Text to insert.

        Returns:
            str: Updated body.

        Examples:
            >>> out = _insert_after_generation_stamp("<!-- generated -->\\n# T\\n", "> **Summary.**\\n")
            >>> "Summary" in out
            True
    """
    lines = text.splitlines(keepends=True)
    for idx, line in enumerate(lines):
        if line.strip().startswith("<!-- generated:"):
            return "".join(lines[: idx + 1]) + block + "".join(lines[idx + 1 :])
    return block + text


def _insert_before_references(text: str, block: str) -> str:
    """Insert ``block`` immediately before ``## References`` when present.

        Args:
    text (str): README body.
    block (str): Stub section to insert.

        Returns:
            str: Updated body.

        Examples:
            >>> out = _insert_before_references("## Level 1\\n\\n## References\\n", "## Level 3\\n\\n")
            >>> out.index("Level 3") < out.index("References")
            True
    """
    match = re.search(r"^##\s+References\b", text, re.MULTILINE)
    if match:
        return text[: match.start()] + block + text[match.start() :]
    return text.rstrip() + "\n\n" + block
