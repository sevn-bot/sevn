"""CI gate: SkillSpector static scan of bundled skills, repo skills, and tool docs.

Reads ``infra/skillspector-targets.json``, runs ``skillspector scan --no-llm`` per
target, merges JSON into ``reports/skillspector-ci-report.json``, subtracts
``infra/skillspector-baseline.json``, and exits **1** on unbaseline'd HIGH/CRITICAL.

Module: scripts.check_skillspector
Depends: json, glob, pathlib, sys, sevn.skills.security_scan

Exports:
    discover_targets — Expand target manifest globs under the repo root.
    main — CLI entry for ``make skillspector-check``.

Examples:
    >>> from pathlib import Path
    >>> REPO == Path(__file__).resolve().parents[1]
    True
"""

from __future__ import annotations

import glob
import json
import sys
from pathlib import Path
from typing import Any

from sevn.skills.security_scan import (
    load_baseline,
    normalize_skill_path,
    resolve_skillspector_command,
    scan_skill_path,
)

REPO = Path(__file__).resolve().parents[1]
TARGETS_PATH = REPO / "infra" / "skillspector-targets.json"
BASELINE_PATH = REPO / "infra" / "skillspector-baseline.json"
REPORT_PATH = REPO / "reports" / "skillspector-ci-report.json"


def discover_targets(manifest: dict[str, Any]) -> list[Path]:
    """Expand ``targets`` entries into concrete scan paths.

    Args:
        manifest (dict[str, Any]): Parsed ``skillspector-targets.json``.

    Returns:
        list[Path]: Existing directories and markdown files to scan.

    Examples:
        >>> paths = discover_targets(
        ...     {"targets": [{"kind": "file_glob", "path": "infra/skillspector-targets.json"}]}
        ... )
        >>> any(p.name == "skillspector-targets.json" for p in paths)
        True
    """
    out: list[Path] = []
    rows = manifest.get("targets")
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("kind") or "")
        pattern = str(row.get("path") or "").strip()
        if not pattern:
            continue
        if kind in {"skill_dir_glob", "file_glob"}:
            for match in sorted(glob.glob(str(REPO / pattern), recursive=False)):
                path = Path(match)
                if path.is_dir() or (kind == "file_glob" and path.is_file()):
                    out.append(path)
        elif kind == "skill_dir":
            path = REPO / pattern
            if path.is_dir():
                out.append(path)
        elif kind == "skill_file":
            path = REPO / pattern
            if path.is_file():
                out.append(path)
    return out


def _load_manifest() -> dict[str, Any]:
    """Load and validate the targets manifest.

    Returns:
        dict[str, Any]: Parsed manifest.

    Raises:
        SystemExit: When the manifest is missing or invalid JSON.

    Examples:
        >>> isinstance(_load_manifest(), dict)  # doctest: +SKIP
        True
    """
    if not TARGETS_PATH.is_file():
        print(f"check_skillspector: missing {TARGETS_PATH.relative_to(REPO)}", file=sys.stderr)
        raise SystemExit(1)
    try:
        blob = json.loads(TARGETS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"check_skillspector: invalid targets JSON — {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if not isinstance(blob, dict):
        print("check_skillspector: targets root must be a JSON object", file=sys.stderr)
        raise SystemExit(1)
    return blob


def main() -> int:
    """Run SkillSpector CI scan across configured targets.

    Returns:
        int: ``0`` when clean, ``1`` on findings or configuration errors.

    Examples:
        >>> main() in (0, 1)
        True
    """
    if resolve_skillspector_command() is None:
        print(
            "check_skillspector: SkillSpector CLI not found — "
            "install with: uv sync --extra skillspector",
            file=sys.stderr,
        )
        return 1

    manifest = _load_manifest()
    ci_options = manifest.get("ci_options")
    no_llm = True
    fail_severities: tuple[str, ...] = ("HIGH", "CRITICAL")
    if isinstance(ci_options, dict):
        if ci_options.get("no_llm") is False:
            no_llm = False
        raw_sev = ci_options.get("fail_severities")
        if isinstance(raw_sev, list) and raw_sev:
            fail_severities = tuple(str(s).upper() for s in raw_sev)

    baseline = load_baseline(BASELINE_PATH)
    targets = discover_targets(manifest)
    if not targets:
        print("check_skillspector: no scan targets discovered", file=sys.stderr)
        return 1

    aggregate_targets: list[dict[str, Any]] = []
    failures: list[str] = []

    for target in targets:
        result = scan_skill_path(
            target,
            repo_root=REPO,
            baseline=baseline,
            fail_severities=fail_severities,
            no_llm=no_llm,
        )
        rel = normalize_skill_path(target, repo_root=REPO)
        row: dict[str, Any] = {
            "path": rel,
            "risk_score": result.risk_score,
            "risk_severity": result.risk_severity,
            "finding_count": len(result.issues),
            "issues": [
                {
                    "rule_id": issue.rule_id,
                    "severity": issue.severity,
                    "file": issue.file,
                    "pattern": issue.pattern,
                }
                for issue in result.issues
            ],
        }
        if result.error:
            row["error"] = result.error
            failures.append(f"{rel}: {result.error}")
        aggregate_targets.append(row)
        for issue in result.issues:
            failures.append(
                f"{rel}: {issue.severity} {issue.rule_id}"
                + (f" ({issue.file})" if issue.file else ""),
            )

    report = {
        "schema_version": 1,
        "fail_severities": list(fail_severities),
        "no_llm": no_llm,
        "targets": aggregate_targets,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if failures:
        print("check_skillspector: HIGH/CRITICAL findings (post-baseline):", file=sys.stderr)
        for line in failures:
            print(f"  - {line}", file=sys.stderr)
        print(f"check_skillspector: report → {REPORT_PATH.relative_to(REPO)}", file=sys.stderr)
        return 1

    print(f"check_skillspector: ok ({len(targets)} targets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
