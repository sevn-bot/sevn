"""Offline README section builders for deterministic generation.

Module: sevn.docs.readme.offline_sections
Depends: pathlib, sevn.docs.readme.l2_prose, sevn.docs.readme.l3_prose, sevn.docs.readme.links,
    sevn.docs.readme.manifest, sevn.docs.readme.symbols, sevn.docs.readme.text_utils

Exports:
    offline_subsystem_sections — subsystem tier bodies.
    offline_root_sections — root README bodies.
    offline_index_sections — INDEX catalog bodies.
    offline_catalog_sections — catalog profile bodies.
    offline_modules_catalog_sections — modules catalog table scaffold.
    offline_skills_catalog_sections — skills catalog table scaffold.
    offline_guide_sections — guide step bodies.
    offline_freeform_sections — freeform bodies.
    catalog_items_with_hrefs — attach hrefs to catalog rows.
    build_subsystem_summary — expand manifest summary with spec context.
    build_level1_overview — plain-language Level 1 overview.

Examples:
    >>> from sevn.docs.readme.offline_sections import offline_subsystem_sections
    >>> from sevn.docs.readme.manifest import ReadmeEntry
    >>> out = offline_subsystem_sections(
    ...     ReadmeEntry("g", "G", "S.", "subsystem", "g", "o.md", ("src/**",), ("specs/x.md",)),
    ...     {"source_py_files": ["src/a.py"], "source_dir": "src/sevn/gateway/", "source_excerpt": ""},
    ... )
    >>> "summary" in out
    True
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sevn.docs.readme.l2_prose import build_level2_how_it_works
from sevn.docs.readme.l3_prose import build_level3_deep_dive
from sevn.docs.readme.links import readme_relative_href
from sevn.docs.readme.manifest import ReadmeEntry
from sevn.docs.readme.scan_context import ScanContext
from sevn.docs.readme.symbols import symbol_names
from sevn.docs.readme.text_utils import format_path_list, role_from_summary, truncate_at_sentence

_MODULES_CATALOG_CAP = 200

_ROOT_HIGHLIGHTS: tuple[str, ...] = (
    "Chat on Telegram, in your browser, or by voice — one assistant, many ways to reach it",
    "Runs on your machine — you choose the AI models and keep control of your data",
    "Remembers context across conversations so you do not have to repeat yourself",
    "Built-in safety checks help catch risky requests before they run",
    "Mission Control dashboard shows what Sevn is doing and lets you steer active tasks",
    "Automations and scheduled triggers can run work even when you are not chatting",
    "Grows with you through skills, tools, and workspace memory you control",
)


def _scan_dict(scan: ScanContext | dict[str, Any]) -> dict[str, Any]:
    """Normalize scanner output for section builders.

    Args:
        scan (ScanContext | dict[str, Any]): Scanner context.

    Returns:
        dict[str, Any]: Plain mapping for template assembly.

    Examples:
        >>> _scan_dict({"slug": "gateway"})["slug"]
        'gateway'
    """
    if isinstance(scan, ScanContext):
        return scan.to_dict()
    return scan


def _catalog_row_summary(
    rel: str,
    module_summaries: dict[str, str],
    module_symbols: dict[str, list[dict[str, int | str]]],
) -> str:
    """Build one catalog row summary with optional symbol hints.

    Args:
        rel (str): Repo-relative Python module path.
        module_summaries (dict[str, str]): Module summary map.
        module_symbols (dict): Symbol inventory.

    Returns:
        str: Catalog summary cell text.

    Examples:
        >>> _catalog_row_summary("src/a.py", {}, {})
        'Module `src/a.py`.'
    """
    summary = module_summaries.get(rel, "")
    if summary:
        return summary
    symbols = symbol_names(module_symbols.get(rel, []))
    sym_hint = f" Entry points: {', '.join(f'`{s}`' for s in symbols[:3])}." if symbols else ""
    return f"Module `{rel}`.{sym_hint}"


def offline_subsystem_sections(
    entry: ReadmeEntry, scan: ScanContext | dict[str, Any]
) -> dict[str, Any]:
    """Offline subsystem tier bodies from scan context.

        Args:
    entry (ReadmeEntry): Manifest row.
    scan (dict[str, Any]): Scanner context.

        Returns:
            dict[str, str]: Section key → markdown body.

        Examples:
            >>> offline_subsystem_sections(
            ...     ReadmeEntry("g", "Gateway", "S.", "subsystem", "g", "o.md", ("src/**",), ("specs/x.md",)),
            ...     {"source_py_files": ["src/a.py"], "source_dir": "src/sevn/gateway/", "source_excerpt": ""},
            ... )["summary"]
            'S.'
    """
    scan = _scan_dict(scan)
    py_files = list(scan.get("source_py_files", []))
    source_dir = str(scan.get("source_dir", "src/sevn/"))
    spec_excerpt = str(scan.get("spec_excerpt", "")).strip()
    module_symbols: dict[str, list[dict[str, int | str]]] = scan.get("module_symbols", {})
    return {
        "summary": build_subsystem_summary(entry, spec_excerpt),
        "role": role_from_summary(entry.summary),
        "level1": build_level1_overview(entry, spec_excerpt),
        "level2": build_level2_how_it_works(entry, scan, py_files, spec_excerpt),
        "level3": build_level3_deep_dive(entry, source_dir, py_files, module_symbols, scan),
        "references": list(entry.specs),
    }


def offline_root_sections(entry: ReadmeEntry, scan: ScanContext | dict[str, Any]) -> dict[str, Any]:
    """Offline root README section bodies.

        Args:
    entry (ReadmeEntry): Manifest row.
    scan (dict[str, Any]): Scanner context.

        Returns:
            dict[str, str]: Section key → value (strings or lists).

        Examples:
            >>> out = offline_root_sections(
            ...     ReadmeEntry("root", "R", "S", "root", "d", "README.md", ("a",), ()),
            ...     {"package": {"name": "sevn", "description": "d"}},
            ... )
            >>> "value_prop" in out
            True
    """
    scan = _scan_dict(scan)
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


def offline_index_sections(entry: ReadmeEntry, scan: dict[str, Any]) -> dict[str, Any]:
    """Offline index catalog section bodies.

        Args:
    entry (ReadmeEntry): Manifest row.
    scan (dict[str, Any]): Scanner context supplying ``index_entries``.

        Returns:
            dict[str, str]: Section key → value.

        Examples:
            >>> offline_index_sections(
            ...     ReadmeEntry("index", "I", "S", "index", "d", "INDEX.md", ("a",), ()),
            ...     {},
            ... )["entries"]
            []
    """
    entries = scan.get("index_entries", [])
    return {
        "summary": entry.summary,
        "entries": entries,
    }


def offline_catalog_sections(entry: ReadmeEntry, scan: dict[str, Any]) -> dict[str, Any]:
    """Offline catalog item table scaffold.

        Args:
    entry (ReadmeEntry): Manifest row.
    scan (dict[str, Any]): Scanner context with ``source_py_files``.

        Returns:
            dict[str, str]: Section key → value.

        Examples:
            >>> offline_catalog_sections(
            ...     ReadmeEntry("tools", "T", "S", "catalog", "t", "o.md", ("src/**",), ()),
            ...     {"source_py_files": ["src/sevn/tools/x.py"], "module_summaries": {}},
            ... )["items"][0]["name"]
            'x'
    """
    if entry.catalog == "skills":
        return offline_skills_catalog_sections(entry, scan)
    return offline_modules_catalog_sections(entry, scan)


def offline_modules_catalog_sections(entry: ReadmeEntry, scan: dict[str, Any]) -> dict[str, Any]:
    """Build the modules catalog table with docstring summaries and overflow row.

        Args:
    entry (ReadmeEntry): Manifest row.
    scan (dict[str, Any]): Scanner context with ``source_py_files``.

        Returns:
            dict[str, Any]: Section map with ``summary`` and ``items`` keys.

        Examples:
            >>> offline_modules_catalog_sections(
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
        summary = _catalog_row_summary(rel, module_summaries, module_symbols)
        items.append({"name": name, "path": rel, "summary": summary})
    remainder = len(py_files) - _MODULES_CATALOG_CAP
    if remainder > 0:
        items.append({"name": "…", "path": "", "summary": f"+{remainder} more modules"})
    return {"summary": entry.summary, "items": items}


def offline_skills_catalog_sections(entry: ReadmeEntry, scan: dict[str, Any]) -> dict[str, Any]:
    """Build bundled-skill and runtime-loader tables for the skills catalog.

        Args:
    entry (ReadmeEntry): Manifest row.
    scan (dict[str, Any]): Scanner context with ``bundled_skills`` and ``source_py_files``.

        Returns:
            dict[str, Any]: Section map with bundled and runtime item lists.

        Examples:
            >>> offline_skills_catalog_sections(
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
        summary = _catalog_row_summary(rel, module_summaries, module_symbols)
        runtime_items.append({"name": name, "path": rel, "summary": summary})
    return {
        "summary": entry.summary,
        "bundled_items": bundled_items,
        "runtime_items": runtime_items,
    }


def catalog_items_with_hrefs(
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
            >>> catalog_items_with_hrefs(
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


def offline_guide_sections(entry: ReadmeEntry, scan: dict[str, Any]) -> dict[str, Any]:
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
        f"Normative specs: {format_path_list(list(entry.specs))}."
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


def offline_freeform_sections(entry: ReadmeEntry, scan: dict[str, Any]) -> dict[str, Any]:
    """Offline freeform body scaffold.

        Args:
    entry (ReadmeEntry): Manifest row.
    scan (dict[str, Any]): Scanner context (body uses manifest summary only).

        Returns:
            dict[str, str]: Summary and body text.

        Examples:
            >>> offline_freeform_sections(
            ...     ReadmeEntry("x", "X", "Body", "freeform", "d", "o.md", ("a",), ()),
            ...     {},
            ... )["body"]
            'Body'
    """
    return {
        "summary": entry.summary,
        "body": entry.summary,
    }


def build_subsystem_summary(entry: ReadmeEntry, spec_excerpt: str) -> str:
    """Expand manifest summary with spec context when available.

        Args:
    entry (ReadmeEntry): Manifest row.
    spec_excerpt (str): Spec prose excerpt from scanner.

        Returns:
            str: Summary paragraph(s).

        Examples:
            >>> build_subsystem_summary(
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


def build_level1_overview(entry: ReadmeEntry, spec_excerpt: str) -> str:
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
