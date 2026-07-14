"""Section/tier data model and template assembly for README generation.

Module: sevn.docs.readme.model
Depends: dataclasses, sevn.docs.readme.manifest

Exports:
    SectionContent — one rendered section body.
    ReadmeAssembly — profile + section map ready for Jinja2.
    offline_sections — deterministic section bodies from scan context.
    assemble_template_context — map assembly + scan context to template vars.
    merge_section — copy assembly with one section replaced.
    format_path_list — comma-separated backtick path list for prose.
    truncate_at_sentence — truncate prose at a sentence boundary within a limit.
    format_module_symbols_for_prompt — JSON symbol map for LLM prompts.

Examples:
    >>> from sevn.docs.readme.model import SectionContent
    >>> SectionContent(name="summary", content="Hello").name
    'summary'
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sevn.docs.readme.l3_prose import build_level3_deep_dive
from sevn.docs.readme.links import readme_relative_href
from sevn.docs.readme.manifest import ReadmeEntry
from sevn.docs.readme.prose import strip_inline_code  # re-export for tests/CLI
from sevn.docs.readme.symbols import README_MAX_SYMBOL_FILES, symbol_names

_MODULES_CATALOG_CAP = 200

__all__ = (
    "README_MAX_SYMBOL_FILES",
    "ReadmeAssembly",
    "SectionContent",
    "assemble_template_context",
    "format_module_symbols_for_prompt",
    "format_path_list",
    "merge_section",
    "offline_sections",
    "strip_inline_code",
    "truncate_at_sentence",
)
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s")
_ABBREV_BEFORE_PERIOD = frozenset(
    {
        "incl",
        "eg",
        "ie",
        "etc",
        "vs",
        "mr",
        "mrs",
        "dr",
        "sr",
        "jr",
        "st",
        "fig",
        "dept",
        "approx",
        "min",
        "max",
        "ext",
        "vol",
        "ref",
        "al",
    }
)

_ROOT_HIGHLIGHTS: tuple[str, ...] = (
    "Chat on Telegram, in your browser, or by voice — one assistant, many ways to reach it",
    "Runs on your machine — you choose the AI models and keep control of your data",
    "Remembers context across conversations so you do not have to repeat yourself",
    "Built-in safety checks help catch risky requests before they run",
    "Mission Control dashboard shows what Sevn is doing and lets you steer active tasks",
    "Automations and scheduled triggers can run work even when you are not chatting",
    "Grows with you through skills, tools, and workspace memory you control",
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
        sections = _offline_subsystem_sections(entry, scan)
    elif profile == "root":
        sections = _offline_root_sections(entry, scan)
    elif profile == "index":
        sections = _offline_index_sections(entry, scan)
    elif profile == "catalog":
        sections = _offline_catalog_sections(entry, scan)
    elif profile == "guide":
        sections = _offline_guide_sections(entry, scan)
    else:
        sections = _offline_freeform_sections(entry, scan)
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
                "role": sections.get("role", _role_from_summary(entry.summary)),
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
                bundled = _catalog_items_with_hrefs(bundled, entry=entry, repo_root=repo_root)
                runtime = _catalog_items_with_hrefs(runtime, entry=entry, repo_root=repo_root)
            base["catalog_kind"] = "skills"
            base["bundled_items"] = bundled
            base["runtime_items"] = runtime
        else:
            items = sections.get("items", [])
            if repo_root is not None:
                items = _catalog_items_with_hrefs(items, entry=entry, repo_root=repo_root)
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
    assembly (ReadmeAssembly): Existing assembly.
    name (str): Section key.
    content (str): New body text.

        Returns:
            ReadmeAssembly: Updated assembly.

        Examples:
            >>> from sevn.docs.readme.manifest import ReadmeEntry
            >>> e = ReadmeEntry("x", "T", "S", "freeform", "d", "out.md", ("a",), ())
            >>> asm = ReadmeAssembly(e, {"summary": "a"})
            >>> merge_section(asm, name="body", content="b").sections["body"]
            'b'
    """
    merged = dict(assembly.sections)
    merged[name] = content
    return ReadmeAssembly(entry=assembly.entry, sections=merged)


def _offline_subsystem_sections(entry: ReadmeEntry, scan: dict[str, Any]) -> dict[str, Any]:
    """Offline subsystem tier bodies from scan context.

        Args:
    entry (ReadmeEntry): Manifest row.
    scan (dict[str, Any]): Scanner context.

        Returns:
            dict[str, str]: Section key → markdown body.

        Examples:
            >>> _offline_subsystem_sections(
            ...     ReadmeEntry("g", "Gateway", "S.", "subsystem", "g", "o.md", ("src/**",), ("specs/x.md",)),
            ...     {"source_py_files": ["src/a.py"], "source_dir": "src/sevn/gateway/", "source_excerpt": ""},
            ... )["summary"]
            'S.'
    """
    py_files = list(scan.get("source_py_files", []))
    source_dir = str(scan.get("source_dir", "src/sevn/"))
    spec_excerpt = str(scan.get("spec_excerpt", "")).strip()
    module_symbols: dict[str, list[dict[str, int | str]]] = scan.get("module_symbols", {})
    return {
        "summary": _build_subsystem_summary(entry, spec_excerpt),
        "role": _role_from_summary(entry.summary),
        "level1": _build_level1_overview(entry, spec_excerpt),
        "level2": _build_level2_how_it_works(entry, scan, py_files, spec_excerpt),
        "level3": build_level3_deep_dive(entry, source_dir, py_files, module_symbols, scan),
        "references": list(entry.specs),
    }


def _offline_root_sections(entry: ReadmeEntry, scan: dict[str, Any]) -> dict[str, Any]:
    """Offline root README section bodies.

        Args:
    entry (ReadmeEntry): Manifest row.
    scan (dict[str, Any]): Scanner context.

        Returns:
            dict[str, str]: Section key → value (strings or lists).

        Examples:
            >>> out = _offline_root_sections(
            ...     ReadmeEntry("root", "R", "S", "root", "d", "README.md", ("a",), ()),
            ...     {"package": {"name": "sevn", "description": "d"}},
            ... )
            >>> "value_prop" in out
            True
    """
    package = scan.get("package", {})
    intro_lines = list(scan.get("intro_lines", ()))
    return {
        "summary": entry.summary,
        "intro_lines": intro_lines,
        "tagline": intro_lines[0] if intro_lines else entry.summary,
        "value_prop": str(scan.get("value_prop") or package.get("description", entry.summary)),
        "highlights": list(_ROOT_HIGHLIGHTS),
        "architecture_bullets": [
            "Turn spine: channel → gateway → triage → executor → tools/skills → reply",
            "Secrets and LLM calls route through the paired egress proxy",
            "Workspace-scoped memory and configurable tracing sinks",
        ],
        "subsystem_entries": list(scan.get("subsystem_entries", [])),
        "quick_start": (
            "**Clone and onboard**\n\n"
            "```bash\n"
            "git clone https://github.com/sevn-bot/sevn.git\n"
            "cd sevn\n"
            "make setup\n"
            "sevn onboard\n"
            "sevn doctor\n"
            "```\n\n"
            "`make setup` syncs dependencies, installs pre-commit hooks, and puts the "
            "`sevn` CLI on your PATH (via uv). Do **not** hand-edit `sevn.json` for "
            "first-time setup — run **`sevn onboard`** (web wizard by default; "
            "`sevn onboard --cli` for the terminal UI). It writes workspace config, "
            "secrets, and optional daemon units.\n\n"
            "After onboarding, use the **`sevn` CLI** for everyday operations: "
            "`sevn doctor`, `sevn gateway start`, `sevn sync --latest`, etc."
        ),
        "install_steps": [
            "Clone this repository",
            "From the repo root, run **`make setup`** — installs **uv** when missing, fetches **Python 3.12+** via uv (see `.python-version`), syncs dependencies, and puts the `sevn` CLI on PATH",
            "Run **`sevn onboard`** to configure your workspace (replaces manual `sevn.json` editing; installs gateway/proxy daemons by default)",
            "Run **`sevn doctor`** to confirm the install is healthy",
        ],
        "repo_owner": "sevn-bot",
        "repo_name": str(package.get("name", "sevn")),
    }


def _offline_index_sections(entry: ReadmeEntry, scan: dict[str, Any]) -> dict[str, Any]:
    """Offline index catalog section bodies.

        Args:
    entry (ReadmeEntry): Manifest row.
    scan (dict[str, Any]): Scanner context (unused for index scaffold).

        Returns:
            dict[str, str]: Section key → value.

        Examples:
            >>> _offline_index_sections(
            ...     ReadmeEntry("index", "I", "S", "index", "d", "INDEX.md", ("a",), ()),
            ...     {},
            ... )["entries"]
            []
    """
    _ = scan
    entries = scan.get("index_entries", [])
    return {
        "summary": entry.summary,
        "entries": entries,
    }


def _offline_catalog_sections(entry: ReadmeEntry, scan: dict[str, Any]) -> dict[str, Any]:
    """Offline catalog item table scaffold.

        Args:
    entry (ReadmeEntry): Manifest row.
    scan (dict[str, Any]): Scanner context with ``source_py_files``.

        Returns:
            dict[str, str]: Section key → value.

        Examples:
            >>> _offline_catalog_sections(
            ...     ReadmeEntry("tools", "T", "S", "catalog", "t", "o.md", ("src/**",), ()),
            ...     {"source_py_files": ["src/sevn/tools/x.py"], "module_summaries": {}},
            ... )["items"][0]["name"]
            'x'
    """
    if entry.catalog == "skills":
        return _offline_skills_catalog_sections(entry, scan)
    return _offline_modules_catalog_sections(entry, scan)


def _offline_modules_catalog_sections(entry: ReadmeEntry, scan: dict[str, Any]) -> dict[str, Any]:
    """Build the modules catalog table with docstring summaries and overflow row.

        Args:
    entry (ReadmeEntry): Manifest row.
    scan (dict[str, Any]): Scanner context with ``source_py_files``.

        Returns:
            dict[str, Any]: Section map with ``summary`` and ``items`` keys.

        Examples:
            >>> _offline_modules_catalog_sections(
            ...     ReadmeEntry("tools", "T", "S", "catalog", "t", "o.md", ("src/**",), ()),
            ...     {"source_py_files": ["src/sevn/tools/x.py"], "module_summaries": {"src/sevn/tools/x.py": "Tool x."}},
            ... )["items"][0]["summary"]
            'Tool x.'
    """
    items: list[dict[str, str]] = []
    py_files = list(scan.get("source_py_files", []))
    module_summaries: dict[str, str] = scan.get("module_summaries", {})
    module_symbols: dict[str, list[dict[str, int | str]]] = scan.get("module_symbols", {})
    for rel in py_files[:_MODULES_CATALOG_CAP]:
        name = rel.rsplit("/", maxsplit=1)[-1].removesuffix(".py")
        summary = module_summaries.get(rel, "")
        if not summary:
            symbols = symbol_names(module_symbols.get(rel, []))
            sym_hint = (
                f" Entry points: {', '.join(f'`{s}`' for s in symbols[:3])}." if symbols else ""
            )
            summary = f"Module `{rel}`.{sym_hint}"
        items.append({"name": name, "path": rel, "summary": summary})
    remainder = len(py_files) - _MODULES_CATALOG_CAP
    if remainder > 0:
        items.append({"name": "…", "path": "", "summary": f"+{remainder} more modules"})
    return {"summary": entry.summary, "items": items}


def _offline_skills_catalog_sections(entry: ReadmeEntry, scan: dict[str, Any]) -> dict[str, Any]:
    """Build bundled-skill and runtime-loader tables for the skills catalog.

        Args:
    entry (ReadmeEntry): Manifest row.
    scan (dict[str, Any]): Scanner context with ``bundled_skills`` and ``source_py_files``.

        Returns:
            dict[str, Any]: Section map with bundled and runtime item lists.

        Examples:
            >>> _offline_skills_catalog_sections(
            ...     ReadmeEntry("skills", "S", "Sum", "catalog", "s", "o.md", ("a",), (), catalog="skills"),
            ...     {"bundled_skills": [{"name": "demo", "path": "p/SKILL.md", "summary": "Demo."}], "source_py_files": []},
            ... )["bundled_items"][0]["name"]
            'demo'
    """
    bundled_items = [
        {"name": row["name"], "path": row["path"], "summary": row["summary"]}
        for row in scan.get("bundled_skills", [])
    ]
    runtime_items: list[dict[str, str]] = []
    module_summaries: dict[str, str] = scan.get("module_summaries", {})
    module_symbols: dict[str, list[dict[str, int | str]]] = scan.get("module_symbols", {})
    runtime_prefix = "src/sevn/skills/"
    for rel in scan.get("source_py_files", []):
        if not rel.startswith(runtime_prefix):
            continue
        name = rel.rsplit("/", maxsplit=1)[-1].removesuffix(".py")
        summary = module_summaries.get(rel, "")
        if not summary:
            symbols = symbol_names(module_symbols.get(rel, []))
            sym_hint = (
                f" Entry points: {', '.join(f'`{s}`' for s in symbols[:3])}." if symbols else ""
            )
            summary = f"Module `{rel}`.{sym_hint}"
        runtime_items.append({"name": name, "path": rel, "summary": summary})
    return {
        "summary": entry.summary,
        "bundled_items": bundled_items,
        "runtime_items": runtime_items,
    }


def _catalog_items_with_hrefs(
    items: list[dict[str, str]],
    *,
    entry: ReadmeEntry,
    repo_root: Path,
) -> list[dict[str, str]]:
    """Attach file-relative hrefs to catalog row paths.

        Args:
    items (list[dict[str, str]]): Catalog rows with repo-root ``path`` values.
    entry (ReadmeEntry): Manifest row for output-relative link resolution.
    repo_root (Path): Repository root.

        Returns:
            list[dict[str, str]]: Rows with ``path`` rewritten to README-relative hrefs.

        Examples:
            >>> from pathlib import Path as _P
            >>> rows = _catalog_items_with_hrefs(
            ...     [{"name": "x", "path": "src/a.py", "summary": "A."}],
            ...     entry=ReadmeEntry("t", "T", "S", "catalog", "t", "docs/readmes/t.md", ("src/**",), ()),
            ...     repo_root=_P("."),
            ... )
            >>> rows[0]["path"].endswith("src/a.py")
            True
    """
    out: list[dict[str, str]] = []
    for item in items:
        path = str(item.get("path", ""))
        if not path:
            out.append(dict(item))
            continue
        out.append(
            {
                **item,
                "path": readme_relative_href(
                    readme_output=entry.output,
                    target=path,
                    repo_root=repo_root,
                ),
            }
        )
    return out


def _offline_guide_sections(entry: ReadmeEntry, scan: dict[str, Any]) -> dict[str, Any]:
    """Offline guide step scaffold.

        Args:
    entry (ReadmeEntry): Manifest row.
    scan (dict[str, Any]): Scanner context.

        Returns:
            dict[str, str]: Section key → value.

        Examples:
            >>> steps = _offline_guide_sections(
            ...     ReadmeEntry("onboarding", "O", "S", "guide", "o", "o.md", ("a",), ("specs/x.md",)),
            ...     {"spec_excerpt": "Setup wizard."},
            ... )["steps"]
            >>> steps[0]["heading"]
            'Overview'
    """
    spec_excerpt = str(scan.get("spec_excerpt", "")).strip()
    overview_body = (
        f"{entry.summary}\n\n"
        f"This guide walks through operator setup step by step. "
        f"Normative specs: {_format_path_list(list(entry.specs))}."
    )
    if spec_excerpt:
        overview_body += f"\n\n{spec_excerpt[:800]}"
    steps = [
        {"heading": "Overview", "body": overview_body},
        {
            "heading": "First-time setup",
            "body": (
                "From the repo root run **`make setup`**, then **`sevn onboard`** "
                "(web wizard by default; `sevn onboard --cli` for terminal UI). "
                "Finish with **`sevn doctor`** to confirm health."
            ),
        },
        {
            "heading": "Daily operations",
            "body": (
                "Use **`sevn gateway start`**, **`sevn config validate`**, and channel-specific "
                "commands documented in the linked specs. Re-run onboarding safely with "
                "`sevn onboard` when adding channels or rotating secrets."
            ),
        },
    ]
    return {
        "summary": entry.summary,
        "steps": steps,
        "references": list(entry.specs),
    }


def _offline_freeform_sections(entry: ReadmeEntry, scan: dict[str, Any]) -> dict[str, Any]:
    """Offline freeform body scaffold.

        Args:
    entry (ReadmeEntry): Manifest row.
    scan (dict[str, Any]): Scanner context (unused).

        Returns:
            dict[str, str]: Summary and body text.

        Examples:
            >>> _offline_freeform_sections(
            ...     ReadmeEntry("x", "X", "Body", "freeform", "d", "o.md", ("a",), ()),
            ...     {},
            ... )["body"]
            'Body'
    """
    _ = scan
    return {
        "summary": entry.summary,
        "body": entry.summary,
    }


def _build_subsystem_summary(entry: ReadmeEntry, spec_excerpt: str) -> str:
    """Expand manifest summary with spec context when available.

        Args:
    entry (ReadmeEntry): Manifest row.
    spec_excerpt (str): Spec prose excerpt from scanner.

        Returns:
            str: Summary paragraph(s).

        Examples:
            >>> _build_subsystem_summary(
            ...     ReadmeEntry("g", "G", "FastAPI control plane.", "subsystem", "g", "o.md", ("a",), ()),
            ...     "",
            ... )
            'FastAPI control plane.'
    """
    if not spec_excerpt:
        return entry.summary
    prose = spec_excerpt.split("\n\n")[0]
    if prose.startswith("From "):
        prose = prose.split(":", maxsplit=1)[-1].strip()
    elongation = truncate_at_sentence(prose, 400)
    if (
        elongation
        and len(elongation) > 20
        and elongation not in entry.summary
        and not elongation.startswith("Offline scaffold")
    ):
        return f"{entry.summary} {elongation}"
    return entry.summary


def _build_level1_overview(entry: ReadmeEntry, spec_excerpt: str) -> str:
    """Plain-language Level 1 overview for operators.

        Args:
    entry (ReadmeEntry): Manifest row.
    spec_excerpt (str): Spec prose excerpt.

        Returns:
            str: Non-technical overview paragraphs.

        Examples:
            >>> text = _build_level1_overview(
            ...     ReadmeEntry("g", "Gateway", "Control plane.", "subsystem", "g", "o.md", ("a",), ()),
            ...     "Accepts messages from channels.",
            ... )
            >>> "Gateway" in text
            True
    """
    title = entry.title
    paragraphs = [
        (
            f"**{title}** is a core part of sevn.bot — the personal AI assistant you "
            f"run on your own machine. {entry.summary}"
        ),
        (
            f"In everyday use, {title.lower()} helps Sevn do its job reliably: "
            f"you interact through familiar channels (Telegram, browser, voice), and "
            f"this layer keeps those interactions safe, consistent, and under your control."
        ),
    ]
    if spec_excerpt:
        snippet = spec_excerpt.split("\n\n")[0]
        for prefix in ("From specs/", "From "):
            if snippet.startswith(prefix):
                snippet = snippet.split(":", maxsplit=1)[-1].strip()
                break
        if len(snippet) > 40:
            trimmed = truncate_at_sentence(snippet, 600)
            if trimmed:
                paragraphs.append(trimmed)
    return "\n\n".join(paragraphs)


def _build_level2_how_it_works(
    entry: ReadmeEntry,
    scan: dict[str, Any],
    py_files: list[str],
    spec_excerpt: str,
) -> str:
    """Technical Level 2 — roughly 2x a brief overview.

        Args:
    entry (ReadmeEntry): Manifest row.
    scan (dict[str, Any]): Scanner context.
    py_files (list[str]): Repo-relative Python paths.
    spec_excerpt (str): Spec prose excerpt.

        Returns:
            str: Technical how-it-works body.

        Examples:
            >>> body = _build_level2_how_it_works(
            ...     ReadmeEntry("g", "Gateway", "S.", "subsystem", "g", "o.md", ("src/**",), ("specs/x.md",)),
            ...     {"source_dir": "src/sevn/gateway/"},
            ...     ["src/sevn/gateway/a.py"],
            ...     "",
            ... )
            >>> "src/sevn/gateway/" in body
            True
    """
    source_dir = str(scan.get("source_dir", "src/sevn/"))
    source_roots = [str(root) for root in scan.get("source_roots", ())]
    module_symbols: dict[str, list[dict[str, int | str]]] = scan.get("module_symbols", {})
    if entry.turn_spine:
        flow = (
            f"### Data and control flow\n\n"
            f"{entry.title} sits in the sevn.bot turn spine: a channel delivers a message, "
            f"the gateway normalises it, triage routes work to the right executor, and the "
            f"reply returns through the same channel adapter. This subsystem owns the "
            f"responsibilities described in the manifest summary."
        )
        suffix = entry.l2_flow_suffix.strip()
        if not suffix and entry.provider_keys_via_proxy:
            suffix = "Provider API calls are brokered by the egress proxy."
        if suffix:
            flow += f" {suffix}"
    else:
        module_names = [
            rel.rsplit("/", maxsplit=1)[-1].removesuffix(".py").replace("_", " ")
            for rel in py_files[:6]
        ]
        if module_names:
            modules_phrase = ", ".join(f"`{name}`" for name in module_names[:4])
            if len(module_names) > 4:
                modules_phrase += f", and {len(module_names) - 4} more"
            graph = (
                f"{entry.title} is organized around {modules_phrase} under "
                f"{_format_path_list([source_dir], max_items=1)}"
            )
        else:
            graph = f"{entry.title} implements supporting services under `{source_dir}`"
        if len(source_roots) > 1:
            graph += (
                f"; implementation spans "
                f"{_format_path_list(source_roots, max_items=len(source_roots))}."
            )
        else:
            graph += f" with {len(py_files)} Python module(s) in the scanned tree."
        entry_points: list[str] = []
        for rel, symbols in list(module_symbols.items())[:4]:
            names = symbol_names(symbols)
            if names:
                entry_points.append(f"{rel.rsplit('/', 1)[-1]} ({names[0]})")
        if entry_points:
            graph += f" Primary entry points include {', '.join(entry_points)}."
        flow = f"### Data and control flow\n\n{graph}"
    if len(source_roots) > 1:
        layout = (
            f"### Components and layout\n\n"
            f"Implementation spans {_format_path_list(source_roots, max_items=len(source_roots))}. "
            f"The package contains {len(py_files)} Python module(s); primary entry points "
            f"include {_format_path_list(py_files, max_items=6)}."
        )
    else:
        layout = (
            f"### Components and layout\n\n"
            f"Implementation lives under `{source_dir}`. "
            f"The package contains {len(py_files)} Python module(s); primary entry points "
            f"include {_format_path_list(py_files, max_items=6)}."
        )
    parts = [
        layout,
        flow,
        f"### Configuration\n\n"
        f"Operator settings come from `sevn.json` in the workspace. Related normative "
        f"specs: {_format_path_list(list(entry.specs))}. "
        f"Run `sevn config validate` after edits; use `sevn doctor` to confirm the "
        f"install sees the expected layout.",
    ]
    if module_symbols:
        symbol_lines = []
        for rel, symbols in list(module_symbols.items())[:5]:
            names = symbol_names(symbols)
            symbol_lines.append(f"- `{rel}` — {', '.join(f'`{s}`' for s in names[:4])}")
        parts.append("### Key modules\n\n" + "\n".join(symbol_lines))
    if spec_excerpt:
        spec_context = truncate_at_sentence(spec_excerpt, 1200)
        if spec_context:
            parts.append(f"### Spec context\n\n{spec_context}")
    return "\n\n".join(parts)


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


def _first_sentence(text: str) -> str:
    """Return the first complete sentence from prose text.

        Args:
    text (str): Source prose.

        Returns:
            str: First sentence ending in ``.``, ``!``, or ``?``; empty when none.

        Examples:
            >>> _first_sentence("Hello world. More text.")
            'Hello world.'
    """
    stripped = text.strip()
    for match in _SENTENCE_BOUNDARY.finditer(stripped):
        if not _is_sentence_boundary(stripped, match.start()):
            continue
        candidate = stripped[: match.start() + 1].strip()
        if candidate and candidate[-1] in ".!?":
            return candidate
    return ""


def truncate_at_sentence(text: str, limit: int) -> str:
    """Return the longest leading sentence fragment that fits within ``limit``.

        Args:
    text (str): Source prose.
    limit (int): Maximum character length for the returned fragment.

        Returns:
            str: Sentence ending in ``.``, ``!``, or ``?``; empty when none fits.

        Examples:
            >>> truncate_at_sentence("Hello world. More text.", 15)
            'Hello world.'
            >>> truncate_at_sentence("No sentence boundary at all", 12)
            ''
    """
    if limit <= 0 or not text.strip():
        return ""
    stripped = text.strip()
    if len(stripped) <= limit and stripped[-1] in ".!?":
        return stripped
    best = ""
    for match in _SENTENCE_BOUNDARY.finditer(stripped):
        end = match.start() + 1
        if end > limit:
            break
        if not _is_sentence_boundary(stripped, match.start()):
            continue
        candidate = stripped[:end].strip()
        if candidate and candidate[-1] in ".!?":
            best = candidate
    return best


def _is_sentence_boundary(text: str, space_pos: int) -> bool:
    """Return True when ``space_pos`` ends a real sentence (not an abbreviation).

        Args:
    text (str): Full prose string.
    space_pos (int): Index of the whitespace after sentence punctuation.

        Returns:
            bool: True when the boundary is a sentence end.

        Examples:
            >>> _is_sentence_boundary("Items (incl. foo) and more. Extra", 24)
            False
    """
    if space_pos < 1 or text[space_pos - 1] not in ".!?":
        return False
    punct_pos = space_pos - 1
    word_start = punct_pos
    while word_start > 0 and (text[word_start - 1].isalnum() or text[word_start - 1] == "."):
        word_start -= 1
    word = text[word_start:punct_pos].lower().rstrip(".")
    return word not in _ABBREV_BEFORE_PERIOD


def format_path_list(paths: list[str], *, max_items: int = 4) -> str:
    """Format path list for inline prose.

        Args:
    paths (list[str]): Repo-relative paths.
    max_items (int): Maximum paths to quote before summarizing the remainder.

        Returns:
            str: Comma-separated backtick paths with a true remainder count.

        Examples:
            >>> format_path_list(["a.py", "b.py"])
            '`a.py`, `b.py`'
            >>> format_path_list([f"m{i}.py" for i in range(114)], max_items=4)
            '`m0.py`, `m1.py`, `m2.py`, `m3.py`, and 110 more'
    """
    if not paths:
        return "(see source tree)"
    quoted = [f"`{p}`" for p in paths[:max_items]]
    remainder = len(paths) - max_items
    if remainder > 0:
        return ", ".join(quoted) + f", and {remainder} more"
    return ", ".join(quoted)


def _format_path_list(paths: list[str], *, max_items: int = 4) -> str:
    """Backward-compatible alias for :func:`format_path_list`.

        Args:
    paths (list[str]): Repo-relative paths.
    max_items (int): Maximum paths to quote before summarizing the remainder.

        Returns:
            str: Comma-separated backtick paths.

        Examples:
            >>> _format_path_list(["a.py"])
            '`a.py`'
    """
    return format_path_list(paths, max_items=max_items)


def _role_from_summary(summary: str) -> str:
    """Use the first sentence of the manifest summary as the role line.

        Args:
    summary (str): Manifest summary text.

        Returns:
            str: Role line for the title suffix.

        Examples:
            >>> _role_from_summary("FastAPI control plane. More detail.")
            'FastAPI control plane'
    """
    first = summary.split(".", maxsplit=1)[0].strip()
    return first or summary
