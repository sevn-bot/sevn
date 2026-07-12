"""Worksheet Keep rows vs registry and bundled core skills (`plan/tools-skills-full-inventory-wave-plan.md` Wave 0).

Parses ``plan/architecture/04-tools-inventory-decisions.md`` and
``plan/architecture/04b-skills-inventory-decisions.md``. For each **Keep** native tool
row, asserts the name appears in a permissive :func:`sevn.tools.registry.build_session_registry`
snapshot. For each **Keep** bundled skill row, asserts
``src/sevn/data/bundled_skills/core/<name>/SKILL.md`` exists.

Emits ``reports/tools-skills-inventory-gap.json`` and exits **1** when gaps remain.

Module: scripts.check_tools_skills_inventory
Depends: json, pathlib, re, sys

Exports:
    WorksheetRow — one inventory worksheet row.
    parse_tools_worksheet — extract Keep native tool rows from the tools worksheet.
    parse_skills_worksheet — extract Keep bundled skill rows from the skills worksheet.
    collect_registry_tool_names — snapshot tool names from ``build_session_registry``.
    build_gap_report — merge worksheet expectations with on-disk/registry state.
    main — CLI entry; writes JSON report and returns exit code.

Examples:
    >>> isinstance(REPO, Path)
    True
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

REPO = Path(__file__).resolve().parents[1]
TOOLS_WORKSHEET = (
    REPO / ".ignorelocal" / "design" / "plan" / "architecture" / "04-tools-inventory-decisions.md"
)
SKILLS_WORKSHEET = (
    REPO / ".ignorelocal" / "design" / "plan" / "architecture" / "04b-skills-inventory-decisions.md"
)
CORE_SKILLS_ROOT = REPO / "src" / "sevn" / "data" / "bundled_skills" / "core"
GAP_REPORT = REPO / "reports" / "tools-skills-inventory-gap.json"

ToolDisposition = Literal["keep_tool", "make_skill", "remove", "skip"]

_MAKE_SKILL_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "agent",
        "canvas",
        "code_graph_rag_cli",
        "code_graph_rag_read_export",
        "cron_add",
        "cron_delete",
        "cron_edit",
        "cron_list",
        "lcm_conversations_meta",
        "lcm_describe",
        "lcm_expand",
        "lcm_expand_query",
        "lcm_fetch",
        "lcm_grep",
        "lcm_list_conversations",
        "lcm_search_summaries",
        "mycode_scan",
        "pdf",
        "pdf_load",
        "pdf_read",
        "reminder",
        "roam_code",
        "second_brain_ingest",
        "second_brain_query",
        "sessions",
        "sessions_history",
        "sessions_list",
        "sessions_send",
        "sessions_spawn",
        "sessions_yield",
        "session_status",
        "telegram_buttons",
        "telegram_forum_create",
        "telegram_forum_find_group",
    }
)
_REMOVE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "agent",
        "cron.schedule",
        "cron.update",
        "notify.*",
        "secret.capture",
        "secret.delete",
        "secret.rotate",
        "send_message",
        "send_voice",
    }
)
_DEFERRED_TOOL_NAMES: frozenset[str] = frozenset({"claude_code"})
# Wave Z documented exceptions: worksheet Keep rows satisfied outside the native registry
# snapshot (``plan/tools-skills-full-inventory-wave-plan.md`` locked decision #6 + §11 deferrals).
_DOCUMENTED_TOOL_EXCEPTIONS: dict[str, str] = {
    "gh_repo_get": (
        "No standalone native tool — GitHub repo metadata via "
        "`integration_call` + `github-manager` skill scripts "
        "(`legacy_gh_repo_integration_kwargs`; specs/11-tools-registry.md §11)."
    ),
    "gh_repo_search": (
        "No standalone native tool — repo search via `integration_call` + "
        "`github-manager` skill scripts."
    ),
    "gh_repo_clone": (
        "No standalone native tool — clone via `integration_call` + `github-manager` skill scripts."
    ),
    "gh_file_read": (
        "No standalone native tool — file read via `integration_call` + "
        "`github-manager` skill scripts."
    ),
    "camera_capture": (
        "Post-v1 device callback tool; worksheet §11 keep row deferred "
        "(channel-native capture not wired in v1 inventory scope)."
    ),
    "screen_record": ("Post-v1 device callback tool; worksheet §11 keep row deferred."),
    "location": ("Post-v1 device callback tool; worksheet §11 keep row deferred."),
    "notification": ("Post-v1 OS notification tool; worksheet §11 keep row deferred."),
    "semantic_search": (
        "Conditional registration — only when ``witchcraft_enabled`` and the Witchcraft "
        "indexer is wired (``register_semantic_search_tool``; specs/27-second-brain.md §11)."
    ),
}
# Bundled core skills shipped outside the worksheet table (no Keep row to assert).
_DOCUMENTED_SKILL_EXCEPTIONS: dict[str, str] = {
    "graphify": (
        "Bundled core skill beyond worksheet table; live `graphify build` "
        "subprocess in `src/sevn/data/bundled_skills/core/graphify/` "
        "(Wave TFI-19; optional `sevn[graphify]` extra)."
    ),
    "cua-agent": (
        "Worksheet Keep row for macOS-only autonomous GUI loop; bundled stub deferred "
        "until `computer-use` + HITL approval wiring ships (plan/architecture/04b-skills.md §17a)."
    ),
    "lume": (
        "Worksheet Keep row for Apple-Silicon VM lifecycle (`cua do switch lume`); bundled stub "
        "deferred until Lume provider wiring ships (plan/architecture/04b-skills.md §17b)."
    ),
}


@dataclass(frozen=True)
class WorksheetRow:
    """One inventory worksheet row."""

    name: str
    section: str
    worksheet: str
    disposition: ToolDisposition


def _normalise_cell(value: str) -> str:
    """Lower-case and strip worksheet decision cells.

    Args:
        value (str): Raw markdown table cell.

    Returns:
        str: Normalised marker text.

    Examples:
        >>> _normalise_cell("  Y ")
        'y'
    """
    return value.strip().lower()


def _section_default_mode(section_text: str) -> ToolDisposition:
    """Infer row disposition default from a worksheet section heading block.

    Args:
        section_text (str): Heading plus any prose before the table.

    Returns:
        ToolDisposition: Default disposition for rows in the section.

    Examples:
        >>> _section_default_mode("## 2. File operations\\n(keep all as tools)")
        'keep_tool'
    """
    lowered = section_text.lower()
    if "remove all" in lowered:
        return "remove"
    if "move " in lowered and "skill" in lowered:
        return "make_skill"
    if "keep all as tools" in lowered:
        return "keep_tool"
    if "only `sandbox_exec`" in lowered or "v1: only" in lowered:
        return "keep_tool"
    return "keep_tool"


def _row_disposition(
    *,
    tool_name: str,
    keep: str,
    remove: str,
    make_skill: str,
    section_default: ToolDisposition,
) -> ToolDisposition:
    """Resolve a tool row disposition from explicit markers and section defaults.

    Args:
        tool_name (str): Backtick tool identifier.
        keep (str): Keep column cell.
        remove (str): Remove column cell.
        make_skill (str): Make skill column cell.
        section_default (ToolDisposition): Section-level default.

    Returns:
        ToolDisposition: Resolved disposition for the row.

    Examples:
        >>> _row_disposition(
        ...     tool_name="read",
        ...     keep="",
        ...     remove="",
        ...     make_skill="",
        ...     section_default="keep_tool",
        ... )
        'keep_tool'
    """
    if tool_name in _REMOVE_TOOL_NAMES or "remove" in _normalise_cell(remove):
        return "remove"
    if tool_name in _DEFERRED_TOOL_NAMES:
        return "skip"
    if tool_name in _MAKE_SKILL_TOOL_NAMES or _normalise_cell(make_skill) in {"y", "yes"}:
        return "make_skill"
    if _normalise_cell(keep) in {"y", "yes", "keep"}:
        return "keep_tool"
    if _normalise_cell(remove) in {"y", "yes"}:
        return "remove"
    return section_default


def _parse_markdown_tables(text: str) -> list[tuple[str, list[list[str]]]]:
    """Split worksheet markdown into section labels and parsed table rows.

    Args:
        text (str): Full worksheet markdown.

    Returns:
        list[tuple[str, list[list[str]]]]: Section heading text and body rows.

    Examples:
        >>> sections = _parse_markdown_tables("| A | B |\\n|---|---|\\n| x | y |")
        >>> sections[0][1][0]
        ['x', 'y']
    """
    sections: list[tuple[str, list[list[str]]]] = []
    current_heading = ""
    current_rows: list[list[str]] = []
    in_table = False
    for line in text.splitlines():
        if line.startswith("## "):
            if current_rows:
                sections.append((current_heading, current_rows))
                current_rows = []
            current_heading = line
            in_table = False
            continue
        if not line.startswith("|"):
            if in_table and current_rows:
                sections.append((current_heading, current_rows))
                current_rows = []
            in_table = False
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells:
            continue
        if all(set(cell) <= {"-", ":", " "} for cell in cells):
            in_table = True
            continue
        if in_table:
            current_rows.append(cells)
    if current_rows:
        sections.append((current_heading, current_rows))
    return sections


def _extract_backtick_name(first_cell: str) -> str | None:
    """Return the first backtick identifier in a worksheet row label cell.

    Args:
        first_cell (str): First table column text.

    Returns:
        str | None: Tool or skill id when present.

    Examples:
        >>> _extract_backtick_name("`read`")
        'read'
    """
    match = re.search(r"`([^`]+)`", first_cell)
    if not match:
        return None
    name = match.group(1).strip()
    if name.endswith(("/*", "*")):
        return None
    return name


def parse_tools_worksheet(path: Path = TOOLS_WORKSHEET) -> list[WorksheetRow]:
    """Parse Keep native tool rows from the tools inventory worksheet.

    Args:
        path (Path): Worksheet markdown path.

    Returns:
        list[WorksheetRow]: Rows whose disposition is ``keep_tool``.

    Examples:
        >>> rows = parse_tools_worksheet(TOOLS_WORKSHEET)
        >>> any(row.name == "load_tool" for row in rows)
        True
    """
    text = path.read_text(encoding="utf-8")
    keep_rows: list[WorksheetRow] = []
    section_number = ""
    for heading, rows in _parse_markdown_tables(text):
        section_match = re.match(r"##\s+(\d+)\.", heading)
        if section_match:
            section_number = section_match.group(1)
        if section_number in {"14", "15"}:
            continue
        section_default = _section_default_mode(heading)
        for cells in rows:
            if len(cells) < 5:
                continue
            name = _extract_backtick_name(cells[0])
            if name is None:
                continue
            disposition = _row_disposition(
                tool_name=name,
                keep=cells[2] if len(cells) > 2 else "",
                remove=cells[3] if len(cells) > 3 else "",
                make_skill=cells[4] if len(cells) > 4 else "",
                section_default=section_default,
            )
            if disposition == "keep_tool":
                keep_rows.append(
                    WorksheetRow(
                        name=name,
                        section=section_number or "?",
                        worksheet=path.name,
                        disposition=disposition,
                    )
                )
    return keep_rows


def parse_skills_worksheet(path: Path = SKILLS_WORKSHEET) -> list[WorksheetRow]:
    """Parse Keep bundled skill rows from the skills inventory worksheet.

    Args:
        path (Path): Worksheet markdown path.

    Returns:
        list[WorksheetRow]: Core bundled skill rows not marked Remove.

    Examples:
        >>> rows = parse_skills_worksheet(SKILLS_WORKSHEET)
        >>> any(row.name == "lcm" for row in rows)
        True
    """
    text = path.read_text(encoding="utf-8")
    keep_rows: list[WorksheetRow] = []
    in_core = False
    for heading, rows in _parse_markdown_tables(text):
        if heading.startswith("## User and generated skills"):
            in_core = False
            continue
        if heading.startswith("## Core bundled skills"):
            in_core = True
        if not in_core:
            continue
        for cells in rows:
            if len(cells) < 5:
                continue
            name = _extract_backtick_name(cells[0])
            if name is None:
                continue
            remove = cells[4] if len(cells) > 4 else ""
            if _normalise_cell(remove) in {"y", "yes"}:
                continue
            keep_rows.append(
                WorksheetRow(
                    name=name,
                    section="core",
                    worksheet=path.name,
                    disposition="keep_tool",
                )
            )
    return keep_rows


def collect_registry_tool_names() -> frozenset[str]:
    """Build a permissive registry snapshot of registered native tool names.

    Returns:
        frozenset[str]: Tool names from ``build_session_registry`` with feature gates on.

    Examples:
        >>> names = collect_registry_tool_names()
        >>> "load_tool" in names
        True
    """
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.tools.registry import build_session_registry

    cfg = WorkspaceConfig.minimal(
        witchcraft_enabled=True,
        second_brain={"enabled": True},
        code_understanding={
            "mycode": {"enabled": True},
            "code_graph_rag": {"enabled": True},
            "roam_code": {"enabled": True},
            "graphify": {"enabled": True},
        },
    )
    executor, _tool_set = build_session_registry(workspace_config=cfg)
    return frozenset(definition.name for definition in executor.definitions())


def build_gap_report() -> dict[str, object]:
    """Compare worksheet Keep rows with registry and bundled skill trees.

    Returns:
        dict[str, object]: Machine-readable gap snapshot for ``reports/tools-skills-inventory-gap.json``.

    Examples:
        >>> report = build_gap_report()
        >>> report["total_gap_count"] >= 0
        True
    """
    tool_rows = parse_tools_worksheet()
    skill_rows = parse_skills_worksheet()
    registry_names = collect_registry_tool_names()
    raw_tool_gaps = [
        {"name": row.name, "section": row.section, "worksheet": row.worksheet}
        for row in tool_rows
        if row.name not in registry_names
    ]
    tool_exceptions = [
        {
            "name": gap["name"],
            "section": gap["section"],
            "worksheet": gap["worksheet"],
            "reason": _DOCUMENTED_TOOL_EXCEPTIONS[gap["name"]],
        }
        for gap in raw_tool_gaps
        if gap["name"] in _DOCUMENTED_TOOL_EXCEPTIONS
    ]
    tool_gaps = [gap for gap in raw_tool_gaps if gap["name"] not in _DOCUMENTED_TOOL_EXCEPTIONS]
    raw_skill_gaps = [
        {"name": row.name, "section": row.section, "worksheet": row.worksheet}
        for row in skill_rows
        if not (CORE_SKILLS_ROOT / row.name / "SKILL.md").is_file()
    ]
    skill_exceptions = [
        {
            "name": gap["name"],
            "section": gap["section"],
            "worksheet": gap["worksheet"],
            "reason": _DOCUMENTED_SKILL_EXCEPTIONS[gap["name"]],
        }
        for gap in raw_skill_gaps
        if gap["name"] in _DOCUMENTED_SKILL_EXCEPTIONS
    ]
    skill_gaps = [gap for gap in raw_skill_gaps if gap["name"] not in _DOCUMENTED_SKILL_EXCEPTIONS]
    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "tools_worksheet": str(TOOLS_WORKSHEET.relative_to(REPO)),
        "skills_worksheet": str(SKILLS_WORKSHEET.relative_to(REPO)),
        "tool_keep_count": len(tool_rows),
        "skill_keep_count": len(skill_rows),
        "registry_tool_count": len(registry_names),
        "tool_gap_count": len(tool_gaps),
        "skill_gap_count": len(skill_gaps),
        "tool_exception_count": len(tool_exceptions),
        "skill_exception_count": len(skill_exceptions),
        "total_gap_count": len(tool_gaps) + len(skill_gaps),
        "tool_gaps": tool_gaps,
        "skill_gaps": skill_gaps,
        "tool_exceptions": tool_exceptions,
        "skill_exceptions": skill_exceptions,
        "registry_tools": sorted(registry_names),
    }


def main() -> int:
    """Write gap JSON and fail when worksheet Keep rows lack implementation.

    Returns:
        int: ``0`` only when ``total_gap_count`` is zero.

    Examples:
        >>> main() in (0, 1)
        True
    """
    if not (TOOLS_WORKSHEET.is_file() and SKILLS_WORKSHEET.is_file()):
        # plan/ is a gitignored local-only tree — absent on CI runners and
        # fresh clones. The worksheet gate only has meaning where it exists.
        print(
            "tools-skills-inventory-check: skipped "
            "(plan/architecture worksheets not present — local-only tree)",
            file=sys.stderr,
        )
        return 0
    report = build_gap_report()
    GAP_REPORT.parent.mkdir(parents=True, exist_ok=True)
    GAP_REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    total = int(report["total_gap_count"])
    tool_exc = int(report.get("tool_exception_count", 0))
    skill_exc = int(report.get("skill_exception_count", 0))
    print(
        "tools-skills-inventory-check: "
        f"{report['tool_gap_count']} tool gap(s), "
        f"{report['skill_gap_count']} skill gap(s), "
        f"{tool_exc} tool exception(s), "
        f"{skill_exc} skill exception(s), "
        f"total={total} -> {GAP_REPORT.relative_to(REPO)}",
        file=sys.stderr,
    )
    if total:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
