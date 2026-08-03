#!/usr/bin/env python3
"""Xenon + C901 complexity ratchet gate (D11 / ``make complexity-ratchet``).

Module: scripts.quality.complexity_ratchet_gate
Depends: json, subprocess, sys, pathlib

Exports:
    load_baseline — load xenon/C901 ratchet document.
    run_xenon — invoke xenon with grade ceilings.
    xenon_passes — return True when xenon exits zero.
    main — CLI entry for ``make complexity-ratchet`` and ``make complexity-target``.

Examples:
    >>> load_baseline()["xenon_baseline"]["absolute"]
    'F'
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BASELINE_PATH = Path(__file__).resolve().parent / "complexity_ratchet_baseline.json"

_GRADE_TO_NUM = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6}


def load_baseline(path: Path = BASELINE_PATH) -> dict[str, object]:
    """Load xenon/C901 ratchet document from JSON.

    Args:
        path (Path): Baseline JSON path.

    Returns:
        dict[str, object]: Parsed baseline.

    Examples:
        >>> load_baseline()["c901_max_complexity_baseline"] >= 100
        True
    """
    return json.loads(path.read_text(encoding="utf-8"))


def run_xenon(spec: dict[str, object]) -> subprocess.CompletedProcess[str]:
    """Invoke xenon with grade ceilings from *spec*.

    Args:
        spec (dict[str, object]): Xenon threshold dict (absolute/modules/average keys).

    Returns:
        subprocess.CompletedProcess[str]: Completed xenon process.

    Examples:
        >>> isinstance(run_xenon({"absolute": "F", "modules": "F", "average": "A", "max_average_num": 5}).returncode, int)
        True
    """
    cmd = [
        "uv",
        "run",
        "xenon",
        "src",
        "-b",
        str(spec["absolute"]),
        "-m",
        str(spec["modules"]),
        "-a",
        str(spec["average"]),
        "--max-average-num",
        str(spec.get("max_average_num", 5)),
        "-i",
        "*/bundled_skills/*",
    ]
    return subprocess.run(
        cmd,
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )


def xenon_passes(spec: dict[str, object]) -> bool:
    """Return True when xenon exits zero for *spec*.

    Args:
        spec (dict[str, object]): Xenon threshold dict.

    Returns:
        bool: True when xenon succeeds.

    Examples:
        >>> xenon_passes({"absolute": "F", "modules": "F", "average": "A", "max_average_num": 5})
        True
    """
    proc = run_xenon(spec)
    return proc.returncode == 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry for complexity ratchet checks.

    Args:
        argv (list[str] | None): Optional argv override (tests).

    Returns:
        int: Exit code (0 = pass).

    Examples:
        >>> main(["--help"]) in (0, 1)
        True
    """
    parser = argparse.ArgumentParser(description="Complexity ratchet gate (#150 / D11)")
    parser.add_argument(
        "--target",
        action="store_true",
        help="Check xenon release target (C/B) — advisory until flip",
    )
    args = parser.parse_args(argv)

    if not BASELINE_PATH.is_file():
        print(f"Missing baseline: {BASELINE_PATH}", file=sys.stderr)
        return 1

    baseline = load_baseline()
    xenon_baseline = baseline["xenon_baseline"]
    xenon_target = baseline["xenon_target"]
    if not isinstance(xenon_baseline, dict) or not isinstance(xenon_target, dict):
        print("Invalid xenon sections in baseline JSON", file=sys.stderr)
        return 1

    if args.target:
        proc = run_xenon(xenon_target)
        if proc.returncode == 0:
            print(
                "Complexity target OK "
                f"(xenon absolute={xenon_target['absolute']} "
                f"modules={xenon_target['modules']}) — ready to flip blocking gate"
            )
            return 0
        print(
            "Complexity target not yet met (advisory — D11):",
            file=sys.stderr,
        )
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-5:]
        for line in tail:
            print(f"  {line}", file=sys.stderr)
        return 1

    if not xenon_passes(xenon_baseline):
        print("Complexity baseline xenon check failed", file=sys.stderr)
        return 1

    c901_ceiling = int(baseline["c901_max_complexity_baseline"])
    steps = baseline.get("c901_max_complexity_ratchet_steps", [])
    print(
        "Complexity ratchet baseline OK "
        f"(xenon {xenon_baseline['absolute']}/{xenon_baseline['modules']}, "
        f"C901 max {c901_ceiling})"
    )
    if isinstance(steps, list) and steps:
        print(f"C901 ratchet steps: {c901_ceiling} → {' → '.join(str(s) for s in steps)}")
    target_abs = str(xenon_target["absolute"])
    target_mod = str(xenon_target["modules"])
    if not xenon_passes(xenon_target):
        print(
            f"Xenon release target ({target_abs}/{target_mod}) not yet met — "
            "advisory until flip (D11)"
        )
    else:
        print(f"Xenon release target ({target_abs}/{target_mod}) already satisfied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
