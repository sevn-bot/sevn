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
    format_module_symbols_for_prompt — JSON symbol map for LLM prompts.

Examples:
    >>> from sevn.docs.readme.model import SectionContent
    >>> SectionContent(name="summary", content="Hello").name
    'summary'
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sevn.docs.readme.manifest import ReadmeEntry

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
) -> dict[str, Any]:
    """Merge scan metadata and section bodies into a Jinja2 context dict.

        Args:
    assembly (ReadmeAssembly): Rendered section map.
    scan (dict[str, Any]): Scanner context.

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
            >>> ctx = assemble_template_context(asm, s)
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
        spec_path = entry.specs[0] if entry.specs else "specs/"
        base.update(
            {
                "role": sections.get("role", _role_from_summary(entry.summary)),
                "spec_path": spec_path,
                "source_dir": scan.get("source_dir", "src/sevn/"),
                "level1": sections.get("level1", ""),
                "level2": sections.get("level2", ""),
                "level3": sections.get("level3", ""),
                "references": sections.get("references", list(entry.specs)),
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
        base["items"] = sections.get("items", [])
    elif entry.profile == "guide":
        base["steps"] = sections.get("steps", [])
        base["references"] = sections.get("references", list(entry.specs))
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
    module_symbols: dict[str, list[str]] = scan.get("module_symbols", {})
    return {
        "summary": _build_subsystem_summary(entry, spec_excerpt),
        "role": _role_from_summary(entry.summary),
        "level1": _build_level1_overview(entry, spec_excerpt),
        "level2": _build_level2_how_it_works(entry, scan, py_files, spec_excerpt),
        "level3": _build_level3_deep_dive(entry, source_dir, py_files, module_symbols, scan),
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
        "value_prop": str(package.get("description", entry.summary)),
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
            ...     {"source_py_files": ["src/sevn/tools/x.py"]},
            ... )["items"][0]["name"]
            'x'
    """
    items: list[dict[str, str]] = []
    module_symbols: dict[str, list[str]] = scan.get("module_symbols", {})
    for rel in scan.get("source_py_files", [])[:40]:
        name = rel.rsplit("/", maxsplit=1)[-1].removesuffix(".py")
        symbols = module_symbols.get(rel, [])
        sym_hint = f" Entry points: {', '.join(f'`{s}`' for s in symbols[:3])}." if symbols else ""
        items.append(
            {
                "name": name,
                "path": rel,
                "summary": f"Module `{rel}`.{sym_hint}",
            }
        )
    return {"summary": entry.summary, "items": items}


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
    first_sentence = prose.split(".", maxsplit=1)[0].strip()
    if (
        first_sentence
        and len(first_sentence) > 20
        and first_sentence not in entry.summary
        and not first_sentence.startswith("Offline scaffold")
        and prose.rstrip().endswith((".", "!", "?"))
    ):
        return f"{entry.summary} {first_sentence}."
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
            trimmed = snippet[:600].rstrip()
            paragraphs.append(trimmed + ("…" if len(snippet) > 600 else ""))
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
    module_symbols: dict[str, list[str]] = scan.get("module_symbols", {})
    parts = [
        f"### Components and layout\n\n"
        f"Implementation lives under `{source_dir}`. "
        f"The package contains {len(py_files)} Python module(s); primary entry points "
        f"include {_format_path_list(py_files[:6])}.",
        f"### Data and control flow\n\n"
        f"{entry.title} sits in the sevn.bot turn spine: a channel delivers a message, "
        f"the gateway normalises it, triage routes work to the right executor, and the "
        f"reply returns through the same channel adapter. This subsystem owns the "
        f"responsibilities described in the manifest summary and defers provider API "
        f"calls to the paired egress proxy (keys never load in the gateway process).",
        f"### Configuration\n\n"
        f"Operator settings come from `sevn.json` in the workspace. Related normative "
        f"specs: {_format_path_list(list(entry.specs))}. "
        f"Run `sevn config validate` after edits; use `sevn doctor` to confirm the "
        f"install sees the expected layout.",
    ]
    if module_symbols:
        symbol_lines = []
        for rel, symbols in list(module_symbols.items())[:5]:
            symbol_lines.append(f"- `{rel}` — {', '.join(f'`{s}`' for s in symbols[:4])}")
        parts.append("### Key modules\n\n" + "\n".join(symbol_lines))
    if spec_excerpt:
        parts.append(f"### Spec context\n\n{spec_excerpt[:1200]}")
    return "\n\n".join(parts)


def _build_level3_deep_dive(
    entry: ReadmeEntry,
    source_dir: str,
    py_files: list[str],
    module_symbols: dict[str, list[str]],
    scan: dict[str, Any],
) -> str:
    """Very detailed Level 3 with verified paths and symbols.

        Args:
    entry (ReadmeEntry): Manifest row.
    source_dir (str): Primary source directory.
    py_files (list[str]): Python module paths.
    module_symbols (dict[str, list[str]]): AST symbol inventory.
    scan (dict[str, Any]): Scanner context.

        Returns:
            str: Deep-dive markdown body.

        Examples:
            >>> body = _build_level3_deep_dive(
            ...     ReadmeEntry("g", "G", "S.", "subsystem", "g", "o.md", ("src/**",), ("specs/x.md",)),
            ...     "src/sevn/gateway/",
            ...     ["src/sevn/gateway/a.py"],
            ...     {"src/sevn/gateway/a.py": ["Foo.bar"]},
            ...     {"source_excerpt": "- `src/sevn/gateway/a.py`"},
            ... )
            >>> "src/sevn/gateway/a.py" in body
            True
    """
    sections: list[str] = [
        f"Primary source tree: `{source_dir}` ({len(py_files)} Python files). "
        f"Normative design: {_format_path_list(list(entry.specs))}."
    ]
    if scan.get("source_excerpt"):
        sections.append("### Module inventory\n\n" + str(scan["source_excerpt"]))
    for rel, symbols in list(module_symbols.items())[:12]:
        heading = rel.rsplit("/", maxsplit=1)[-1].removesuffix(".py").replace("_", " ").title()
        lines = [f"### {heading} (`{rel}`)", ""]
        if symbols:
            lines.append("Public entry points:")
            for sym in symbols:
                lines.append(f"- `{sym}` — see `{rel}`")
        else:
            lines.append(f"See `{rel}` for implementation details.")
        sections.append("\n".join(lines))
    if len(py_files) > 12:
        sections.append(
            f"### Additional modules\n\n"
            f"{len(py_files) - 12} more Python files under `{source_dir}` — "
            f"including {_format_path_list(py_files[12:16])}."
        )
    if entry.specs:
        sections.append(
            f"### Extension and invariants\n\n"
            f"Follow `{entry.specs[0]}` for merge gates, error semantics, and "
            f"compatibility constraints. After code changes under `{source_dir}`, "
            f"run `sevn readme update {entry.slug}` and `make readme-check`."
        )
    return "\n\n".join(sections)


def format_module_symbols_for_prompt(module_symbols: dict[str, list[str]]) -> str:
    """Format module symbol map for LLM prompt variables.

        Args:
    module_symbols (dict[str, list[str]]): Path → symbol names.

        Returns:
            str: JSON-ish bullet list.

        Examples:
            >>> "Foo.bar" in format_module_symbols_for_prompt({"src/a.py": ["Foo.bar"]})
            True
    """
    if not module_symbols:
        return "(no symbols extracted)"
    return json.dumps(module_symbols, indent=2, sort_keys=True)


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


def format_path_list(paths: list[str]) -> str:
    """Format path list for inline prose.

        Args:
    paths (list[str]): Repo-relative paths.

        Returns:
            str: Comma-separated backtick paths.

        Examples:
            >>> format_path_list(["a.py", "b.py"])
            '`a.py`, `b.py`'
    """
    if not paths:
        return "(see source tree)"
    quoted = [f"`{p}`" for p in paths[:4]]
    if len(paths) > 4:
        return ", ".join(quoted) + f", and {len(paths) - 4} more"
    return ", ".join(quoted)


def _format_path_list(paths: list[str]) -> str:
    """Backward-compatible alias for :func:`format_path_list`.

        Args:
    paths (list[str]): Repo-relative paths.

        Returns:
            str: Comma-separated backtick paths.

        Examples:
            >>> _format_path_list(["a.py"])
            '`a.py`'
    """
    return format_path_list(paths)
