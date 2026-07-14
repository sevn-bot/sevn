"""Section/tier data model and template assembly for README generation.

Module: sevn.docs.readme.model
Depends: dataclasses, sevn.docs.readme.manifest, sevn.docs.readme.offline_sections

Exports:
    SectionContent — one rendered section body.
    ReadmeAssembly — profile + section map ready for Jinja2.
    offline_sections — deterministic section bodies from scan context.
    assemble_template_context — map assembly + scan context to template vars.
    merge_section — copy assembly with one section replaced.
    format_module_symbols_for_prompt — JSON symbol map for LLM prompts.

Examples:
    >>> from sevn.docs.readme.model import SectionContent
    >>> SectionContent(name="summary", content="Hello").name
    'summary'
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sevn.docs.readme.links import readme_relative_href
from sevn.docs.readme.manifest import ReadmeEntry
from sevn.docs.readme.offline_sections import (
    catalog_items_with_hrefs,
    offline_catalog_sections,
    offline_freeform_sections,
    offline_guide_sections,
    offline_index_sections,
    offline_root_sections,
    offline_subsystem_sections,
)
from sevn.docs.readme.symbols import README_MAX_SYMBOL_FILES, symbol_names
from sevn.docs.readme.text_utils import format_path_list, role_from_summary

__all__ = (
    "README_MAX_SYMBOL_FILES",
    "ReadmeAssembly",
    "SectionContent",
    "assemble_template_context",
    "format_module_symbols_for_prompt",
    "format_path_list",
    "merge_section",
    "offline_sections",
)


@dataclass(frozen=True)
class SectionContent:
    """One rendered README section."""

    name: str
    content: str


@dataclass(frozen=True)
class ReadmeAssembly:
    """Collected section bodies for one README."""

    entry: ReadmeEntry
    sections: dict[str, Any]


def offline_sections(entry: ReadmeEntry, scan: dict[str, Any]) -> ReadmeAssembly:
    """Build deterministic offline section bodies from scan context.

    Args:
        entry (ReadmeEntry): Manifest row.
        scan (dict[str, Any]): Output of :func:`sevn.docs.readme.scanner.scan_repo_context`.

    Returns:
        ReadmeAssembly: Section map keyed by template variable names.

    Examples:
        >>> from pathlib import Path as _P
        >>> from sevn.docs.readme.manifest import get_entry, load_manifest
        >>> from sevn.docs.readme.scanner import scan_repo_context
        >>> m = load_manifest(_P("docs/readmes/manifest.toml"))
        >>> e = get_entry(m, "gateway")
        >>> asm = offline_sections(e, scan_repo_context(_P("."), e))
        >>> "level1" in asm.sections
        True
    """
    profile = entry.profile
    if profile == "subsystem":
        sections = offline_subsystem_sections(entry, scan)
    elif profile == "root":
        sections = offline_root_sections(entry, scan)
    elif profile == "index":
        sections = offline_index_sections(entry, scan)
    elif profile == "catalog":
        sections = offline_catalog_sections(entry, scan)
    elif profile == "guide":
        sections = offline_guide_sections(entry, scan)
    else:
        sections = offline_freeform_sections(entry, scan)
    return ReadmeAssembly(entry=entry, sections=sections)


def assemble_template_context(
    assembly: ReadmeAssembly,
    scan: dict[str, Any],
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Merge scan metadata and section bodies into a Jinja2 context dict.

    Args:
        assembly (ReadmeAssembly): Rendered section map.
        scan (dict[str, Any]): Scanner context.
        repo_root (Path | None): Repository root for file-relative link hrefs.

    Returns:
        dict[str, Any]: Variables for :func:`sevn.docs.readme.render.render_profile`.

    Examples:
        >>> from pathlib import Path as _P
        >>> from sevn.docs.readme.manifest import get_entry, load_manifest
        >>> from sevn.docs.readme.scanner import scan_repo_context
        >>> m = load_manifest(_P("docs/readmes/manifest.toml"))
        >>> e = get_entry(m, "gateway")
        >>> s = scan_repo_context(_P("."), e)
        >>> asm = offline_sections(e, s)
        >>> ctx = assemble_template_context(asm, s, repo_root=_P("."))
        >>> ctx["slug"] == "gateway"
        True
    """
    entry = assembly.entry
    sections = assembly.sections
    base: dict[str, Any] = {
        "slug": entry.slug,
        "profile": entry.profile,
        "title": entry.title,
        "summary": sections.get("summary", entry.summary),
    }

    if entry.profile == "subsystem":
        spec_target = entry.specs[0] if entry.specs else "about-sevn.bot/specs/"
        source_target = str(scan.get("source_dir", "src/sevn/"))
        if repo_root is not None:
            spec_path = readme_relative_href(
                readme_output=entry.output,
                target=spec_target,
                repo_root=repo_root,
            )
            source_dir = readme_relative_href(
                readme_output=entry.output,
                target=source_target,
                repo_root=repo_root,
                directory=True,
            )
            index_link = readme_relative_href(
                readme_output=entry.output,
                target="docs/readmes/INDEX.md",
                repo_root=repo_root,
            )
            references = [
                readme_relative_href(
                    readme_output=entry.output,
                    target=spec,
                    repo_root=repo_root,
                )
                for spec in sections.get("references", list(entry.specs))
            ]
        else:
            spec_path = spec_target
            source_dir = source_target
            index_link = "docs/readmes/INDEX.md"
            references = list(sections.get("references", list(entry.specs)))
        base.update(
            {
                "role": sections.get("role", role_from_summary(entry.summary)),
                "spec_path": spec_path,
                "source_dir": source_dir,
                "index_link": index_link,
                "level1": sections.get("level1", ""),
                "level2": sections.get("level2", ""),
                "level3": sections.get("level3", ""),
                "references": references,
            }
        )
    elif entry.profile == "root":
        package = scan.get("package", {})
        base.update(
            {
                "intro_lines": sections.get("intro_lines", scan.get("intro_lines", [])),
                "tagline": sections.get("tagline", entry.summary),
                "package_version": package.get("version", "0.0.0"),
                "repo_owner": sections.get("repo_owner", "sevn-bot"),
                "repo_name": sections.get("repo_name", package.get("name", "sevn")),
                "value_prop": sections.get("value_prop", entry.summary),
                "highlights": sections.get("highlights", []),
                "architecture_bullets": sections.get("architecture_bullets", []),
                "subsystem_entries": sections.get("subsystem_entries", []),
                "quick_start": sections.get("quick_start", ""),
                "install_steps": sections.get("install_steps", []),
            }
        )
    elif entry.profile == "index":
        base["entries"] = sections.get("entries", [])
    elif entry.profile == "catalog":
        if entry.catalog == "skills":
            bundled = sections.get("bundled_items", [])
            runtime = sections.get("runtime_items", [])
            if repo_root is not None:
                bundled = catalog_items_with_hrefs(bundled, entry=entry, repo_root=repo_root)
                runtime = catalog_items_with_hrefs(runtime, entry=entry, repo_root=repo_root)
            base["catalog_kind"] = "skills"
            base["bundled_items"] = bundled
            base["runtime_items"] = runtime
        else:
            items = sections.get("items", [])
            if repo_root is not None:
                items = catalog_items_with_hrefs(items, entry=entry, repo_root=repo_root)
            base["catalog_kind"] = "modules"
            base["items"] = items
        base["table_intro"] = sections.get("table_intro", "")
    elif entry.profile == "guide":
        base["steps"] = sections.get("steps", [])
        refs = sections.get("references", list(entry.specs))
        if repo_root is not None:
            refs = [
                readme_relative_href(
                    readme_output=entry.output,
                    target=spec,
                    repo_root=repo_root,
                )
                for spec in refs
            ]
        base["references"] = refs
    else:
        base["body"] = sections.get("body", entry.summary)

    return base


def merge_section(
    assembly: ReadmeAssembly,
    *,
    name: str,
    content: str,
) -> ReadmeAssembly:
    """Return a copy of ``assembly`` with one section replaced.

    Args:
        assembly (ReadmeAssembly): Baseline section map.
        name (str): Section key to replace.
        content (str): New section body.

    Returns:
        ReadmeAssembly: Updated assembly.

    Examples:
        >>> from sevn.docs.readme.manifest import ReadmeEntry
        >>> base = ReadmeAssembly(
        ...     ReadmeEntry("g", "G", "S", "subsystem", "g", "o.md", ("a",), ()),
        ...     {"summary": "old"},
        ... )
        >>> merged = merge_section(base, name="summary", content="new")
        >>> merged.sections["summary"]
        'new'
    """
    merged = dict(assembly.sections)
    merged[name] = content
    return ReadmeAssembly(entry=assembly.entry, sections=merged)


def format_module_symbols_for_prompt(module_symbols: dict[str, list[object]]) -> str:
    """Format module symbol map for LLM prompt variables.

    Args:
        module_symbols (dict[str, list[object]]): Path → symbol records or legacy names.

    Returns:
        str: JSON-ish bullet list.

    Examples:
        >>> "Foo.bar" in format_module_symbols_for_prompt(
        ...     {"src/a.py": [{"name": "Foo.bar", "lineno": 4}]}
        ... )
        True
    """
    if not module_symbols:
        return "(no symbols extracted)"
    normalized = {
        rel: symbol_names(entries) if entries else [] for rel, entries in module_symbols.items()
    }
    return json.dumps(normalized, indent=2, sort_keys=True)
