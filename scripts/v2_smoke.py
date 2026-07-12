"""Sequential v2 user-path smoke (`plan/v2-release-scope.md`).

Module: scripts.v2_smoke
Depends: subprocess, sys

Runs v1 regression plus v2 gates; exits non-zero on the first failure.
Invoked only via ``make v2-smoke`` (see ``Makefile``).

Exports:
    main — CLI entry; runs v1-smoke then v2 gates sequentially.

Examples:
    >>> len(_GATES)
    6
"""

from __future__ import annotations

import subprocess
import sys

# (label, pytest node id)
_GATES: tuple[tuple[str, str], ...] = (
    (
        "v2.1 Second Brain package",
        "tests/second_brain/",
    ),
    (
        "v2.2 code understanding package",
        "tests/code_understanding/",
    ),
    (
        "v2.3 Triager Graphify orientation wiring",
        "tests/code_understanding/test_triager_orientation.py",
    ),
    (
        "v2.4 service manager install (dry-run)",
        "tests/cli/test_service_manager.py",
    ),
    (
        "v2.5 Page Agent intent endpoint",
        "tests/ui/dashboard/test_page_agent.py",
    ),
    (
        "v2.6 gateway Prometheus metrics",
        "tests/gateway/test_metrics.py",
    ),
)


def main() -> int:
    """Run v1-smoke then v2 gates sequentially.

    Returns:
        int: ``0`` when all gates pass, else the failing subprocess exit code.

    Examples:
        >>> main.__name__
        'main'
    """
    print("v2-smoke: v1 regression then v2 gates (plan/v2-release-scope.md)\n")
    v1 = subprocess.run([sys.executable, "scripts/v1_smoke.py"], check=False)
    if v1.returncode != 0:
        print("\nv2-smoke: FAILED during v1-smoke regression", file=sys.stderr)
        return v1.returncode
    print()
    for label, target in _GATES:
        print(f"=== {label} ===")
        print(f"    {target}\n")
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            target,
            "-v",
            "--tb=short",
            "--strict-markers",
        ]
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            print(f"\nv2-smoke: FAILED at gate: {label}", file=sys.stderr)
            return result.returncode
        print()
    print("v2-smoke: all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
