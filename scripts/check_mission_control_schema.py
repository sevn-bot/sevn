#!/usr/bin/env python3
"""Drift gate: Mission Control dashboard schema vs live code.

Module: scripts.check_mission_control_schema
Depends: argparse, json, sys, scripts.mission_control_schema_lib

Exports:
    SchemaGap — one schema drift violation record.
    build_schema_gap_report — machine-readable drift snapshot.
    collect_schema_gaps — compute registry/route/selector/golden violations.
    main — CLI entry.
    scaffold_tab_descriptors — insert WIP stubs for missing slugs.

Examples:
    >>> from scripts.check_mission_control_schema import SchemaGap
    >>> gap = SchemaGap(kind="missing_tab", slug="x", detail="missing")
    >>> gap.kind
    'missing_tab'
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.mission_control_schema_lib import (  # noqa: E402
    APP_JS_PATH,
    GOLDEN_PATH,
    META_SCHEMA_PATH,
    SCHEMA_GAP_REPORT,
    build_schema_document,
    collect_api_v1_routes,
    endpoint_matches_route,
    normalize_schema_for_compare,
    selector_token_in_app_js,
    selector_tokens,
)

from sevn.ui.dashboard.dashboard_schema import (  # noqa: E402
    DASHBOARD_SHELL,
    DASHBOARD_TAB_DESCRIPTORS,
    missing_descriptor_slugs,
)
from sevn.ui.dashboard.tab_registry import WIRED_SLUGS, tab_slug  # noqa: E402

__all__ = [
    "SchemaGap",
    "build_schema_gap_report",
    "collect_schema_gaps",
    "main",
    "scaffold_tab_descriptors",
]

DASHBOARD_SCHEMA_PY = _REPO / "src" / "sevn" / "ui" / "dashboard" / "dashboard_schema.py"


@dataclass(frozen=True)
class SchemaGap:
    """One schema drift violation."""

    kind: str
    detail: str
    slug: str | None = None
    selector: str | None = None
    endpoint: str | None = None
    method: str | None = None


def _iter_selectors_from_tab(tab: dict[str, Any]) -> list[tuple[str, str]]:
    """Collect ``(context, selector)`` pairs from one tab descriptor.

    Args:
        tab (dict[str, Any]): Tab descriptor payload.

    Returns:
        list[tuple[str, str]]: Selector strings with context labels.

    Examples:
        >>> tab = {"views": [{"selector": "#x"}], "key_selectors": {"k": "#y"}}
        >>> len(_iter_selectors_from_tab(tab)) >= 2
        True
    """
    pairs: list[tuple[str, str]] = []
    for view in tab.get("views") or []:
        sel = str(view.get("selector", ""))
        if sel:
            pairs.append((f"view:{view.get('id', '?')}", sel))
    for action in tab.get("actions") or []:
        sel = str(action.get("selector", ""))
        if sel:
            pairs.append((f"action:{action.get('id', '?')}", sel))
    for key, sel in (tab.get("key_selectors") or {}).items():
        if sel:
            pairs.append((f"key:{key}", str(sel)))
    return pairs


def collect_schema_gaps(
    *, app_js_text: str | None = None
) -> tuple[list[SchemaGap], list[SchemaGap]]:
    """Compare declarative schema + golden against live registry, routes, and SPA.

    Args:
        app_js_text (str | None): SPA source; loaded from disk when omitted.

    Returns:
        tuple[list[SchemaGap], list[SchemaGap]]: Hard violations and warnings.

    Examples:
        >>> hard, _warn = collect_schema_gaps(app_js_text='getElementById("login-panel")')
        >>> isinstance(hard, list)
        True
    """
    app_js = app_js_text if app_js_text is not None else APP_JS_PATH.read_text(encoding="utf-8")
    routes = collect_api_v1_routes()
    hard: list[SchemaGap] = []
    warnings: list[SchemaGap] = []

    for slug in sorted(missing_descriptor_slugs()):
        hard.append(
            SchemaGap(
                kind="missing_tab_descriptor",
                slug=slug,
                detail=f"registry slug {slug!r} missing from DASHBOARD_TAB_DESCRIPTORS",
            ),
        )

    for slug in sorted(WIRED_SLUGS - set(DASHBOARD_TAB_DESCRIPTORS)):
        hard.append(
            SchemaGap(
                kind="missing_wired_tab",
                slug=slug,
                detail=f"wired slug {slug!r} missing from schema descriptors",
            ),
        )

    doc = build_schema_document()
    for slug, tab in sorted(DASHBOARD_TAB_DESCRIPTORS.items()):
        for endpoint in tab.get("read_endpoints") or []:
            if not endpoint_matches_route(method="GET", endpoint=endpoint, routes=routes):
                hard.append(
                    SchemaGap(
                        kind="missing_read_endpoint",
                        slug=slug,
                        endpoint=endpoint,
                        method="GET",
                        detail=f"read endpoint not in live routes: GET {endpoint}",
                    ),
                )
        for action in tab.get("actions") or []:
            method = str(action.get("method", "GET"))
            endpoint = str(action.get("endpoint", ""))
            if endpoint and not endpoint_matches_route(
                method=method,
                endpoint=endpoint,
                routes=routes,
            ):
                hard.append(
                    SchemaGap(
                        kind="missing_action_endpoint",
                        slug=slug,
                        endpoint=endpoint,
                        method=method,
                        detail=f"action endpoint not in live routes: {method} {endpoint}",
                    ),
                )
            if action.get("destructive") is not True:
                label = str(action.get("label", "")).casefold()
                action_id = str(action.get("id", "")).casefold()
                if any(
                    token in label or token in action_id
                    for token in ("delete", "kill", "restore", "restart", "uninstall")
                ):
                    warnings.append(
                        SchemaGap(
                            kind="destructive_not_flagged",
                            slug=slug,
                            detail=f"action {action.get('id')!r} looks destructive but destructive=false",
                        ),
                    )
        for context, selector in _iter_selectors_from_tab(tab):
            for token in selector_tokens(selector):
                if not selector_token_in_app_js(token, app_js_text=app_js):
                    hard.append(
                        SchemaGap(
                            kind="missing_selector",
                            slug=slug,
                            selector=selector,
                            detail=f"{context} selector token {token!r} not found in app.js",
                        ),
                    )

    for context, selector in [
        ("shell", sel) for sel in (DASHBOARD_SHELL.get("key_selectors") or {}).values()
    ]:
        for token in selector_tokens(str(selector)):
            if not selector_token_in_app_js(token, app_js_text=app_js):
                hard.append(
                    SchemaGap(
                        kind="missing_shell_selector",
                        selector=str(selector),
                        detail=f"shell {context} token {token!r} not found in app.js",
                    ),
                )

    for action in DASHBOARD_SHELL.get("system_menu_actions") or []:
        method = str(action.get("method", "GET"))
        endpoint = str(action.get("endpoint", ""))
        if endpoint and not endpoint_matches_route(method=method, endpoint=endpoint, routes=routes):
            hard.append(
                SchemaGap(
                    kind="missing_shell_endpoint",
                    endpoint=endpoint,
                    method=method,
                    detail=f"shell action endpoint not in live routes: {method} {endpoint}",
                ),
            )

    if GOLDEN_PATH.is_file():
        committed = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        if normalize_schema_for_compare(committed) != normalize_schema_for_compare(doc):
            hard.append(
                SchemaGap(
                    kind="golden_stale",
                    detail="infra/mission-control.schema.json is stale vs live merge",
                ),
            )
    else:
        hard.append(
            SchemaGap(
                kind="golden_missing",
                detail="infra/mission-control.schema.json not committed",
            ),
        )

    return hard, warnings


def _tab_stub_block(*, slug: str, group: str, title: str) -> str:
    """Format one ``_tab(...)`` scaffold entry for a missing slug.

    Args:
        slug (str): Tab slug.
        group (str): Group slug.
        title (str): Display title.

    Returns:
        str: Python source snippet.

    Examples:
        >>> "TODO" in _tab_stub_block(slug="new-tab", group="core", title="New Tab")
        True
    """
    safe_title = title.replace('"', '\\"')
    return (
        f'    "{slug}": _tab(\n'
        f'        group="{group}",\n'
        f'        title="{safe_title}",\n'
        "        # TODO(W1 scaffold): fill views/actions/endpoints from inventory\n"
        "    ),\n"
    )


def scaffold_tab_descriptors() -> int:
    """Insert WIP ``_tab(...)`` stubs for registry slugs missing from descriptors.

    Returns:
        int: Number of stubs inserted.

    Examples:
        >>> scaffold_tab_descriptors() >= 0
        True
    """
    missing = missing_descriptor_slugs()
    if not missing:
        return 0
    text = DASHBOARD_SCHEMA_PY.read_text(encoding="utf-8")
    marker = "DASHBOARD_TAB_DESCRIPTORS: dict[str, TabDescriptor] = {"
    start = text.find(marker)
    if start < 0:
        return 0
    from sevn.ui.dashboard.tab_registry import DASHBOARD_GROUPS

    group_by_slug = {
        tab_slug(name): tab_slug(group_name)
        for group_name, names in DASHBOARD_GROUPS
        for name in names
    }
    title_by_slug = {
        tab_slug(name): name for _group_name, names in DASHBOARD_GROUPS for name in names
    }
    insert_at = text.rfind("\n}", start)
    if insert_at < 0:
        return 0
    stubs = ""
    inserted = 0
    for slug in missing:
        stub = _tab_stub_block(
            slug=slug,
            group=group_by_slug.get(slug, "core"),
            title=title_by_slug.get(slug, slug),
        )
        if f'"{slug}":' not in text:
            stubs += stub
            inserted += 1
    if not stubs:
        return 0
    new_text = text[:insert_at] + "\n" + stubs + text[insert_at:]
    DASHBOARD_SCHEMA_PY.write_text(new_text, encoding="utf-8")
    return inserted


def _repo_relative(path: Path) -> str:
    """Return ``path`` relative to repo root when possible.

    Args:
        path (Path): File path.

    Returns:
        str: Repo-relative path or absolute string fallback.

    Examples:
        >>> _repo_relative(_REPO / "Makefile")
        'Makefile'
    """
    try:
        return str(path.relative_to(_REPO))
    except ValueError:
        return str(path)


def build_schema_gap_report() -> dict[str, Any]:
    """Build machine-readable schema drift snapshot.

    Returns:
        dict[str, Any]: Report payload for ``reports/mission-control-schema-gap.json``.

    Examples:
        >>> report = build_schema_gap_report()
        >>> "violations" in report
        True
    """
    hard, warnings = collect_schema_gaps()
    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "golden_path": _repo_relative(GOLDEN_PATH),
        "meta_schema_path": _repo_relative(META_SCHEMA_PATH),
        "hard_violation_count": len(hard),
        "warning_count": len(warnings),
        "violations": [asdict(g) for g in hard],
        "warnings": [asdict(g) for g in warnings],
    }


def main(argv: list[str] | None = None) -> int:
    """Run schema drift check and optional scaffold.

    Args:
        argv (list[str] | None): CLI args; ``--scaffold`` writes descriptor stubs.

    Returns:
        int: ``0`` when no hard violations remain after optional scaffold.

    Examples:
        >>> main(["--help"])  # doctest: +SKIP
        0
    """
    parser = argparse.ArgumentParser(description="Mission Control dashboard schema drift gate")
    parser.add_argument(
        "--scaffold",
        action="store_true",
        help="Insert WIP _tab(...) stubs for registry slugs missing from dashboard_schema.py",
    )
    args = parser.parse_args(argv)

    if args.scaffold:
        n = scaffold_tab_descriptors()
        if n:
            print(f"mission-control-schema-scaffold: inserted {n} stub(s)", file=sys.stderr)

    report = build_schema_gap_report()
    SCHEMA_GAP_REPORT.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_GAP_REPORT.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    hard = int(report["hard_violation_count"])
    warn = int(report["warning_count"])
    print(
        f"mission-control-schema-check: {hard} violation(s), {warn} warning(s) "
        f"-> {_repo_relative(SCHEMA_GAP_REPORT)}",
        file=sys.stderr,
    )
    for gap in report["violations"]:
        suffix = ""
        if gap.get("slug"):
            suffix += f" slug={gap['slug']}"
        if gap.get("selector"):
            suffix += f" selector={gap['selector']!r}"
        if gap.get("endpoint"):
            suffix += f" endpoint={gap['method']} {gap['endpoint']}"
        print(f"  [{gap['kind']}] {gap['detail']}{suffix}", file=sys.stderr)

    if hard:
        print("Run: make mission-control-schema-generate", file=sys.stderr)
        return 1

    if META_SCHEMA_PATH.is_file() and GOLDEN_PATH.is_file():
        import subprocess

        result = subprocess.run(
            [
                "uv",
                "run",
                "check-jsonschema",
                f"--schemafile={META_SCHEMA_PATH}",
                str(GOLDEN_PATH),
            ],
            cwd=_REPO,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(result.stderr, file=sys.stderr)
            return result.returncode

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
