#!/usr/bin/env python3
"""Ratchet gate for Ruff advisory rule families (D3 / ``make ruff-extra``).

Module: scripts.quality.ruff_advisory_gate
Depends: json, pathlib, re, subprocess, sys

Exports:
    strip_ansi — remove ANSI color codes from ruff terminal output.
    parse_statistics — parse ``ruff check --statistics`` stdout into rule counts.
    parse_json_diagnostics — count violations per rule from ruff JSON output.
    load_baseline — load frozen per-rule ceilings from JSON.
    check_ratchet — fail when any rule count exceeds its baseline ceiling.
    run_ruff_statistics — run ruff advisory select and return per-rule counts.
    write_baseline — capture current advisory counts as the ratchet baseline.
    main — CLI entry for ``make ruff-extra``.

Examples:
    >>> parse_statistics("123\\tPLR2004\\tmagic-value\\n")["PLR2004"]
    123
    >>> check_ratchet({"PLR2004": 10}, {"PLR2004": 10}) == []
    True
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BASELINE_PATH = Path(__file__).resolve().parent / "ruff_advisory_baseline.json"

_ADVISORY_SELECT = "SLF,BLE,PTH,C4,PERF,FURB,TRY,EM,ARG,N,PL,FBT,ERA,ISC,ICN,C901"

RUFF_PATHS = (
    "src",
    "tests",
    "scripts",
)

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_STAT_LINE = re.compile(r"^\s*(\d+)\s+([A-Z]+\d+)\s+")


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from ruff output.

    Args:
        text (str): Raw terminal text.

    Returns:
        str: Plain text without color codes.

    Examples:
        >>> strip_ansi("\\x1b[1m42\\x1b[0m")
        '42'
    """
    return _ANSI.sub("", text)


def parse_statistics(stdout: str) -> dict[str, int]:
    """Parse ``ruff check --statistics`` stdout into rule counts.

    Args:
        stdout (str): Raw ruff statistics text.

    Returns:
        dict[str, int]: Rule code → violation count.

    Examples:
        >>> parse_statistics("123\\tPLR2004\\tmagic-value\\n")["PLR2004"]
        123
    """
    counts: dict[str, int] = {}
    for line in strip_ansi(stdout).splitlines():
        match = _STAT_LINE.match(line)
        if not match:
            continue
        counts[match.group(2)] = int(match.group(1))
    return counts


def parse_json_diagnostics(raw: str) -> dict[str, int]:
    """Count violations per rule from ``ruff check --output-format json``.

    Args:
        raw (str): JSON array of diagnostic objects.

    Returns:
        dict[str, int]: Rule code → violation count.

    Examples:
        >>> parse_json_diagnostics('[{"code": "PLR2004"}, {"code": "PLR2004"}]')
        {'PLR2004': 2}
    """
    diagnostics = json.loads(raw or "[]")
    codes = (item.get("code") for item in diagnostics if isinstance(item, dict))
    return dict(Counter(code for code in codes if code))


def load_baseline(path: Path = BASELINE_PATH) -> dict[str, int]:
    """Load frozen per-rule ceilings from JSON.

    Args:
        path (Path): Baseline JSON path.

    Returns:
        dict[str, int]: Rule code → maximum allowed violations.

    Examples:
        >>> import tempfile
        >>> with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        ...     _ = fh.write('{"rules": {"PLR2004": 5}}')
        ...     tmp = Path(fh.name)
        >>> load_baseline(tmp)
        {'PLR2004': 5}
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    rules = data.get("rules", data)
    return {str(code): int(count) for code, count in rules.items()}


def check_ratchet(
    observed: dict[str, int],
    baseline: dict[str, int],
) -> list[str]:
    """Return human-readable regressions when counts exceed baseline.

    Args:
        observed (dict[str, int]): Current ruff statistics.
        baseline (dict[str, int]): Frozen per-rule ceilings.

    Returns:
        list[str]: Empty when clean; otherwise one message per regression.

    Examples:
        >>> check_ratchet({"PLR2004": 10}, {"PLR2004": 10}) == []
        True
        >>> check_ratchet({"PLR2004": 11}, {"PLR2004": 10})[0].startswith("PLR2004:")
        True
    """
    regressions: list[str] = []
    for code, ceiling in sorted(baseline.items()):
        count = observed.get(code, 0)
        if count > ceiling:
            regressions.append(f"{code}: {count} > baseline {ceiling} (+{count - ceiling})")
    for code, count in sorted(observed.items()):
        if code not in baseline:
            regressions.append(f"{code}: {count} (new rule — update baseline or fix)")
    return regressions


def run_ruff_statistics() -> dict[str, int]:
    """Run ruff with advisory select and return per-rule counts.

    Returns:
        dict[str, int]: Rule code → violation count.

    Examples:
        >>> isinstance(run_ruff_statistics(), dict)
        True
    """
    cmd = [
        "uv",
        "run",
        "ruff",
        "check",
        "--select",
        _ADVISORY_SELECT,
        "--output-format",
        "json",
        *RUFF_PATHS,
    ]
    proc = subprocess.run(
        cmd,
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode not in (0, 1):
        msg = (proc.stdout + proc.stderr).strip() or f"ruff exited {proc.returncode}"
        raise RuntimeError(f"ruff advisory check failed: {msg}")
    return parse_json_diagnostics(proc.stdout)


def write_baseline(path: Path = BASELINE_PATH) -> dict[str, int]:
    """Capture current advisory counts as the ratchet baseline.

    Args:
        path (Path): Output JSON path.

    Returns:
        dict[str, int]: Written rule counts.

    Examples:
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     out = Path(tmp) / "baseline.json"
        ...     counts = write_baseline(out)
        ...     out.is_file() and isinstance(counts, dict)
        True
    """
    counts = run_ruff_statistics()
    payload = {
        "generated": "2026-06-17",
        "select": _ADVISORY_SELECT,
        "rules": counts,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return counts


def main(argv: list[str] | None = None) -> int:
    """CLI entry for ``make ruff-extra``.

    Args:
        argv (list[str] | None): Optional argv override (tests).

    Returns:
        int: Exit code (0 = pass).

    Examples:
        >>> main(["--help"]) in (0, 1)
        True
    """
    parser = argparse.ArgumentParser(description="Ruff advisory ratchet gate (D3 / W6)")
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Regenerate ruff_advisory_baseline.json from current tree",
    )
    args = parser.parse_args(argv)

    if args.write_baseline:
        counts = write_baseline()
        total = sum(counts.values())
        print(f"Wrote {BASELINE_PATH} ({len(counts)} rules, {total} violations)")
        return 0

    if not BASELINE_PATH.is_file():
        print(f"Missing baseline: {BASELINE_PATH} — run with --write-baseline", file=sys.stderr)
        return 1

    observed = run_ruff_statistics()
    baseline = load_baseline()
    regressions = check_ratchet(observed, baseline)
    if regressions:
        print("Ruff advisory ratchet failed (new violations vs baseline):", file=sys.stderr)
        for line in regressions:
            print(f"  {line}", file=sys.stderr)
        return 1

    total = sum(observed.values())
    print(f"Ruff advisory ratchet OK ({len(observed)} rules, {total} baselined violations)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
