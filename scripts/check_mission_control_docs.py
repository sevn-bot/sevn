#!/usr/bin/env python3
"""Gate: ``Mission Control.html`` structure matches live ``tab_registry``.

Compares :mod:`sevn.ui.dashboard.tab_registry` to the developer catalog in
``about-sevn.bot/Mission Control.html``. With ``--scaffold``, inserts WIP/TODO
``TAB(...)`` and group stubs for missing rows (never overwrites prose).

Module: scripts.check_mission_control_docs
Depends: argparse, json, pathlib, re, sys

Exports:
    DocGap — one structural mismatch record.
    build_docs_gap_report — machine-readable drift snapshot.
    collect_doc_gaps — compute missing groups, tabs, and nav entries.
    main — CLI entry.
    scaffold_dev_catalog — write stubs into dev HTML.

Examples:
    >>> from pathlib import Path
    >>> isinstance(REPO, Path)
    True
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.mission_control_catalog import (  # noqa: E402
    DEV_MISSION_HTML,
    catalog_has_live_tab,
    groups_block_bounds,
    parse_dev_group_nav,
    parse_dev_mission_control_catalog,
)
from scripts.mission_control_snapshot import (  # noqa: E402
    LiveGroup,
    LiveTab,
    collect_live_mission_control,
)

REPO = _REPO
DOCS_GAP_REPORT = REPO / "reports" / "mission-control-docs-gap.json"

__all__ = [
    "DocGap",
    "build_docs_gap_report",
    "collect_doc_gaps",
    "main",
    "scaffold_dev_catalog",
]


@dataclass(frozen=True)
class DocGap:
    """One structural mismatch between live registry and dev catalog."""

    kind: str
    group_id: str
    detail: str
    slug: str | None = None
    label: str | None = None


def collect_doc_gaps(
    *,
    html_path: Path | None = None,
    live: dict[str, LiveGroup] | None = None,
) -> tuple[list[DocGap], list[DocGap]]:
    """Compare live tab registry to the developer catalog.

    Args:
        html_path (Path | None): Dev catalog path; defaults to :data:`DEV_MISSION_HTML`.
        live (dict[str, LiveGroup] | None): Live snapshot; built when omitted.

    Returns:
        tuple[list[DocGap], list[DocGap]]: Hard violations and orphan warnings.

    Examples:
        >>> hard, _warn = collect_doc_gaps()
        >>> isinstance(hard, list)
        True
    """
    path = html_path or DEV_MISSION_HTML
    catalog = parse_dev_mission_control_catalog(path, sanitize=False)
    group_nav = {gid for gid, _ in parse_dev_group_nav(path)}
    menu = live if live is not None else collect_live_mission_control()

    hard: list[DocGap] = []
    warnings: list[DocGap] = []

    for group_id, live_grp in menu.items():
        if group_id not in group_nav:
            hard.append(
                DocGap(
                    kind="missing_group_nav",
                    group_id=group_id,
                    detail=f"GROUP_NAV missing [{group_id!r}, {live_grp.title!r}]",
                ),
            )
        dev_grp = catalog.get(group_id)
        if dev_grp is None:
            hard.append(
                DocGap(
                    kind="missing_group",
                    group_id=group_id,
                    detail=f"GROUPS.{group_id} block missing",
                ),
            )
            continue
        dev_tabs = list(dev_grp.get("tabs") or [])
        for tab in live_grp.tabs:
            if not catalog_has_live_tab(dev_tabs, tab.label):
                hard.append(
                    DocGap(
                        kind="missing_tab",
                        group_id=group_id,
                        detail=f"no TAB() for {tab.label!r}",
                        slug=tab.slug,
                        label=tab.label,
                    ),
                )
        live_norms = {tab.label.casefold() for tab in live_grp.tabs}
        for row in dev_tabs:
            norm = str(row.get("norm", ""))
            if (
                norm
                and norm not in live_norms
                and not any(norm in ln or ln in norm for ln in live_norms)
            ):
                warnings.append(
                    DocGap(
                        kind="orphan_catalog_tab",
                        group_id=group_id,
                        detail=f"catalog TAB {row.get('label')!r} has no live registry row",
                        label=str(row.get("label")),
                    ),
                )

    catalog_ids = set(catalog)
    for gid in catalog_ids - set(menu):
        warnings.append(
            DocGap(
                kind="orphan_catalog_group",
                group_id=gid,
                detail=f"GROUPS.{gid} not in DASHBOARD_GROUPS",
            ),
        )

    return hard, warnings


def _escape_js(s: str) -> str:
    """Escape a string for embedding in a JS ``TAB(...)`` literal.

    Args:
        s (str): Plain text.

    Returns:
        str: Escaped text safe inside double quotes.

    Examples:
        >>> _escape_js('say "hi"')
        'say \\"hi\\"'
    """
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _tab_status_for_kind(kind: str) -> str:
    """Map live tab kind to dev catalog status string.

    Args:
        kind (str): ``wired``, ``post_v1``, or ``stub``.

    Returns:
        str: Dev catalog status label.

    Examples:
        >>> _tab_status_for_kind("wired")
        'Ready'
    """
    if kind == "wired":
        return "Ready"
    if kind == "post_v1":
        return "Stub"
    return "WIP"


def _group_stub(group_id: str, live_grp: LiveGroup) -> str:
    """Format a new ``GROUPS.<id>`` block with TODO prose.

    Args:
        group_id (str): Group slug.
        live_grp (LiveGroup): Live group metadata.

    Returns:
        str: JavaScript object snippet to insert before ``};``.

    Examples:
        >>> "TODO: group short" in _group_stub("core", LiveGroup("core", "Core", ()))
        True
    """
    return (
        f"      {group_id}: {{\n"
        f'        title: "{_escape_js(live_grp.title)}",\n'
        '        status: "WIP",\n'
        '        short: "TODO: group short",\n'
        '        long: "TODO: group long",\n'
        "        tabs: [\n"
        "        ],\n"
        "      },\n"
    )


def _tab_stub(tab: LiveTab) -> str:
    """Format one ``TAB(...)`` stub with TODO prose.

    Args:
        tab (LiveTab): Live registry tab.

    Returns:
        str: JavaScript ``TAB`` call snippet.

    Examples:
        >>> "TODO: short" in _tab_stub(LiveTab("overview", "Overview", "wired"))
        True
    """
    status = _tab_status_for_kind(tab.kind)
    short = "TODO: short"
    long_text = f"TODO: long (/{tab.slug})"
    return (
        f'          TAB("{_escape_js(tab.label)}", "{status}",\n'
        f'            "{_escape_js(short)}",\n'
        f'            "{_escape_js(long_text)}"),\n'
    )


def _insert_group_nav(text: str, group_id: str, nav_label: str) -> str:
    """Append one ``GROUP_NAV`` entry when missing.

    Args:
        text (str): Full dev HTML file.
        group_id (str): Group slug.
        nav_label (str): Visible sidebar group label.

    Returns:
        str: Updated HTML.

    Examples:
        >>> html = 'const GROUP_NAV = [\\n      ["core", "Core"],\\n    ];'
        >>> '["ops",' in _insert_group_nav(html, "ops", "Ops")
        True
    """
    marker = "const GROUP_NAV = ["
    start = text.find(marker)
    if start < 0:
        return text
    close = text.find("\n    ];", start)
    if close < 0:
        return text
    block = text[start:close]
    if f'["{group_id}",' in block:
        return text
    insert = f'\n      ["{group_id}", "{nav_label}"],'
    return text[:close] + insert + text[close:]


def _append_tab_to_group(text: str, group_id: str, tab: LiveTab) -> str:
    """Append one ``TAB(...)`` stub inside an existing group.

    Args:
        text (str): Full dev HTML file.
        group_id (str): Group slug.
        tab (LiveTab): Live tab to document.

    Returns:
        str: Updated HTML when a new stub was added; otherwise unchanged.

    Examples:
        >>> html = 'core: { title: "C", status: "WIP", short: "s", long: "l", tabs: [ ], },'
        >>> _append_tab_to_group(html, "core", LiveTab("x", "X", "wired"))
        'core: { title: "C", status: "WIP", short: "s", long: "l", tabs: [ ], },'
    """
    pattern = re.compile(
        rf"(\s+{re.escape(group_id)}:\s*\{{[\s\S]*?tabs:\s*\[)([\s\S]*?)(\n\s+\],)",
        re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        return text
    body = match.group(2)
    stub = _tab_stub(tab)
    if stub.strip() in body:
        return text
    new_body = body.rstrip() + "\n" + stub
    return text[: match.start(2)] + new_body + text[match.end(2) :]


def scaffold_dev_catalog(
    *,
    html_path: Path | None = None,
    live: dict[str, LiveGroup] | None = None,
) -> int:
    """Insert WIP/TODO stubs into dev HTML for structural gaps.

    Args:
        html_path (Path | None): Dev catalog path; defaults to :data:`DEV_MISSION_HTML`.
        live (dict[str, LiveGroup] | None): Live snapshot; built when omitted.

    Returns:
        int: Number of stubs inserted.

    Examples:
        >>> scaffold_dev_catalog(html_path=Path("/nonexistent"))  # doctest: +SKIP
        0
    """
    path = html_path or DEV_MISSION_HTML
    if not path.is_file():
        return 0
    hard, _ = collect_doc_gaps(html_path=path, live=live)
    if not hard:
        return 0
    text = path.read_text(encoding="utf-8")
    inserted = 0
    menu = live if live is not None else collect_live_mission_control()

    missing_groups = [g for g in hard if g.kind == "missing_group"]
    for gap in missing_groups:
        live_grp = menu.get(gap.group_id)
        if live_grp is None:
            continue
        bounds = groups_block_bounds(text)
        if bounds is None:
            continue
        _, end = bounds
        stub = _group_stub(gap.group_id, live_grp)
        if f"{gap.group_id}:" not in text:
            text = text[:end] + stub + text[end:]
            inserted += 1
            bounds = groups_block_bounds(text)
            if bounds is None:
                break
            _, end = bounds

    for gap in hard:
        if gap.kind == "missing_group_nav":
            live_grp = menu.get(gap.group_id)
            if live_grp is None:
                continue
            new_text = _insert_group_nav(text, gap.group_id, live_grp.title)
            if new_text != text:
                text = new_text
                inserted += 1

    if inserted:
        path.write_text(text, encoding="utf-8")

    hard, _ = collect_doc_gaps(html_path=path, live=live)
    text = path.read_text(encoding="utf-8")
    for gap in hard:
        if gap.kind != "missing_tab" or not gap.slug:
            continue
        live_grp = menu.get(gap.group_id)
        if live_grp is None:
            continue
        tab = next((t for t in live_grp.tabs if t.slug == gap.slug), None)
        if tab is None:
            continue
        new_text = _append_tab_to_group(text, gap.group_id, tab)
        if new_text != text:
            text = new_text
            inserted += 1

    if inserted:
        path.write_text(text, encoding="utf-8")
    return inserted


def build_docs_gap_report(
    *,
    html_path: Path | None = None,
) -> dict[str, Any]:
    """Build machine-readable docs drift snapshot.

    Args:
        html_path (Path | None): Dev catalog path; defaults to :data:`DEV_MISSION_HTML`.

    Returns:
        dict[str, Any]: Report payload for ``reports/mission-control-docs-gap.json``.

    Examples:
        >>> report = build_docs_gap_report()
        >>> "violations" in report
        True
    """
    hard, warnings = collect_doc_gaps(html_path=html_path)
    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "catalog_path": str((html_path or DEV_MISSION_HTML).relative_to(REPO)),
        "hard_violation_count": len(hard),
        "warning_count": len(warnings),
        "violations": [asdict(g) for g in hard],
        "warnings": [asdict(g) for g in warnings],
    }


def main(argv: list[str] | None = None) -> int:
    """Run docs drift check and optional scaffold.

    Args:
        argv (list[str] | None): CLI args; ``--scaffold`` writes stubs.

    Returns:
        int: ``0`` when no hard violations remain after optional scaffold.

    Examples:
        >>> main(["--help"])  # doctest: +SKIP
        0
    """
    parser = argparse.ArgumentParser(description="Mission Control.html structure sync gate")
    parser.add_argument(
        "--scaffold",
        action="store_true",
        help="Insert WIP/TODO stubs for missing groups, tabs, and GROUP_NAV",
    )
    args = parser.parse_args(argv)

    if args.scaffold:
        n = scaffold_dev_catalog()
        if n:
            print(f"mission-control-docs-scaffold: inserted {n} stub(s)", file=sys.stderr)

    report = build_docs_gap_report()
    DOCS_GAP_REPORT.parent.mkdir(parents=True, exist_ok=True)
    DOCS_GAP_REPORT.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    hard = int(report["hard_violation_count"])
    warn = int(report["warning_count"])
    print(
        f"mission-control-docs-check: {hard} violation(s), {warn} warning(s) "
        f"-> {DOCS_GAP_REPORT.relative_to(REPO)}",
        file=sys.stderr,
    )
    for gap in report["violations"]:
        print(
            f"  [{gap['kind']}] {gap['group_id']}: {gap['detail']}"
            + (f" ({gap['slug']})" if gap.get("slug") else ""),
            file=sys.stderr,
        )
    if hard:
        print("Run: make mission-control-docs-scaffold", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
