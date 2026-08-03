#!/usr/bin/env python3
"""Coverage floor ratchet for security/auth paths (D11 / ``make coverage-ratchet``).

Module: scripts.quality.coverage_ratchet_gate
Depends: coverage, json, pathlib, sys

Exports:
    load_baseline — load frozen coverage floors from JSON.
    module_key_for_file — map a source path to a baselined module key.
    measure_coverage — compute overall and per-module coverage from ``.coverage``.
    check_ratchet — fail on regression below documented floors.
    target_gaps — list security/auth modules below the 90% release target.
    main — CLI entry for ``make coverage-ratchet``.

Examples:
    >>> load_baseline()["overall_floor_pct"] >= 0
    True
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import coverage

REPO = Path(__file__).resolve().parents[2]
BASELINE_PATH = Path(__file__).resolve().parent / "coverage_ratchet_baseline.json"

_MODULE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("src/sevn/proxy/", "sevn.proxy"),
    ("src/sevn/security/", "sevn.security"),
    ("src/sevn/gateway/auth.py", "sevn.gateway.auth"),
    ("src/sevn/triggers/auth.py", "sevn.triggers.auth"),
    ("src/sevn/ui/dashboard/services/auth.py", "sevn.ui.dashboard.services.auth"),
)


def load_baseline(path: Path = BASELINE_PATH) -> dict[str, object]:
    """Load frozen coverage floors from JSON.

    Args:
        path (Path): Baseline JSON path.

    Returns:
        dict[str, object]: Parsed baseline document.

    Examples:
        >>> isinstance(load_baseline(), dict)
        True
    """
    return json.loads(path.read_text(encoding="utf-8"))


def module_key_for_file(filename: str) -> str | None:
    """Map a measured file path to a baselined module key.

    Args:
        filename (str): Repo-relative or absolute path.

    Returns:
        str | None: Module key when the file belongs to a tracked security/auth path.

    Examples:
        >>> module_key_for_file("src/sevn/proxy/auth.py")
        'sevn.proxy'
        >>> module_key_for_file("/x/src/sevn/gateway/menu.py") is None
        True
    """
    normalized = filename.replace("\\", "/")
    if normalized.startswith("src/"):
        normalized = normalized[len("src/") :]
    for prefix, key in _MODULE_PREFIXES:
        check = prefix[len("src/") :] if prefix.startswith("src/") else prefix
        if check.endswith(".py"):
            if normalized.endswith(check):
                return key
        elif normalized.startswith(check):
            return key
    return None


def _pct(covered: int, total: int) -> float:
    """Return coverage percentage rounded to one decimal place.

    Args:
        covered (int): Executed line count.
        total (int): Executable line count.

    Returns:
        float: Percent covered (100.0 when *total* is zero).

    Examples:
        >>> _pct(9, 10)
        90.0
    """
    if total == 0:
        return 100.0
    return round(100.0 * covered / total, 1)


def measure_coverage(data_file: Path | None = None) -> tuple[float, dict[str, float]]:
    """Compute overall and per-module coverage from a ``coverage`` data file.

    Args:
        data_file (Path | None): Optional ``.coverage`` path (defaults to repo CWD).

    Returns:
        tuple[float, dict[str, float]]: Overall percent and module-key percents.

    Examples:
        >>> isinstance(measure_coverage.__name__, str)
        True
    """
    cov = coverage.Coverage(data_file=str(data_file) if data_file else None)
    cov.load()

    totals = {"covered": 0, "total": 0}
    modules: dict[str, dict[str, int]] = {}
    src_root = REPO / "src" / "sevn"

    for path in sorted(src_root.rglob("*.py")):
        rel = path.relative_to(REPO).as_posix()
        if "/bundled_skills/" in rel:
            continue
        try:
            analysis = cov.analysis2(str(path))
        except coverage.CoverageException:
            continue
        _, executable, _excluded, missing, _ = analysis
        if not executable:
            continue
        covered = len(executable) - len(missing)
        total = len(executable)
        totals["covered"] += covered
        totals["total"] += total
        key = module_key_for_file(rel)
        if key is None:
            continue
        bucket = modules.setdefault(key, {"covered": 0, "total": 0})
        bucket["covered"] += covered
        bucket["total"] += total

    overall = _pct(totals["covered"], totals["total"])
    module_pct = {key: _pct(v["covered"], v["total"]) for key, v in sorted(modules.items())}
    return overall, module_pct


def check_ratchet(
    observed_overall: float,
    observed_modules: dict[str, float],
    baseline: dict[str, object],
) -> list[str]:
    """Return regressions when coverage falls below documented floors.

    Args:
        observed_overall (float): Measured tree coverage percent.
        observed_modules (dict[str, float]): Measured module percents.
        baseline (dict[str, object]): Frozen baseline JSON.

    Returns:
        list[str]: Empty when clean; otherwise human-readable regressions.

    Examples:
        >>> b = {"overall_floor_pct": 68.0, "modules": {"sevn.proxy": {"floor_pct": 66.0}}}
        >>> check_ratchet(70.0, {"sevn.proxy": 67.0}, b) == []
        True
        >>> check_ratchet(67.0, {"sevn.proxy": 65.0}, b)[0].startswith("overall:")
        True
    """
    regressions: list[str] = []
    overall_floor = float(baseline["overall_floor_pct"])
    if observed_overall + 1e-9 < overall_floor:
        regressions.append(
            f"overall: {observed_overall:.1f}% < floor {overall_floor:.1f}% "
            f"(-{overall_floor - observed_overall:.1f})"
        )

    modules = baseline.get("modules", {})
    if not isinstance(modules, dict):
        return regressions

    for key, spec in sorted(modules.items()):
        if not isinstance(spec, dict):
            continue
        floor = float(spec["floor_pct"])
        observed = observed_modules.get(key)
        if observed is None:
            regressions.append(f"{key}: missing from coverage report")
            continue
        if observed + 1e-9 < floor:
            regressions.append(
                f"{key}: {observed:.1f}% < floor {floor:.1f}% (-{floor - observed:.1f})"
            )
    return regressions


def target_gaps(
    observed_modules: dict[str, float],
    baseline: dict[str, object],
) -> list[str]:
    """List security/auth modules still below the 90% release target.

    Args:
        observed_modules (dict[str, float]): Measured module percents.
        baseline (dict[str, object]): Baseline JSON with target_pct entries.

    Returns:
        list[str]: Advisory gap lines (does not fail the gate).

    Examples:
        >>> gaps = target_gaps({"sevn.proxy": 68.0}, {"modules": {"sevn.proxy": {"target_pct": 90}}})
        >>> gaps[0].startswith("sevn.proxy:")
        True
    """
    gaps: list[str] = []
    modules = baseline.get("modules", {})
    if not isinstance(modules, dict):
        return gaps
    for key, spec in sorted(modules.items()):
        if not isinstance(spec, dict):
            continue
        target = float(spec.get("target_pct", baseline.get("security_auth_target_pct", 90)))
        observed = observed_modules.get(key)
        if observed is None:
            continue
        if observed + 1e-9 < target:
            gaps.append(f"{key}: {observed:.1f}% → target {target:.0f}%")
    return gaps


def main(argv: list[str] | None = None) -> int:
    """CLI entry for ``make coverage-ratchet``.

    Args:
        argv (list[str] | None): Optional argv override (tests).

    Returns:
        int: Exit code (0 = pass).

    Examples:
        >>> main(["--help"]) in (0, 1)
        True
    """
    parser = argparse.ArgumentParser(description="Coverage ratchet gate (#150 / D11)")
    parser.add_argument(
        "--data-file",
        type=Path,
        default=REPO / ".coverage",
        help="coverage data file (default: repo .coverage)",
    )
    args = parser.parse_args(argv)

    if not BASELINE_PATH.is_file():
        print(f"Missing baseline: {BASELINE_PATH}", file=sys.stderr)
        return 1
    if not args.data_file.is_file():
        print(
            f"Missing {args.data_file} — run `make coverage` first",
            file=sys.stderr,
        )
        return 1

    baseline = load_baseline()
    overall, modules = measure_coverage(args.data_file)
    regressions = check_ratchet(overall, modules, baseline)
    if regressions:
        print("Coverage ratchet failed (regression vs baseline):", file=sys.stderr)
        for line in regressions:
            print(f"  {line}", file=sys.stderr)
        return 1

    gaps = target_gaps(modules, baseline)
    print(f"Coverage ratchet OK (overall {overall:.1f}%, floor {baseline['overall_floor_pct']}%)")
    if gaps:
        print("Security/auth target gaps (advisory until 90% — D11):")
        for line in gaps:
            print(f"  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
