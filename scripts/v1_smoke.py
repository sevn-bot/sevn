"""Sequential v1 user-path smoke (`plan/v1-release-scope.md`).

Module: scripts.v1_smoke
Depends: subprocess, sys

Runs seven pytest gates in order; exits non-zero on the first failure.
Invoked only via ``make v1-smoke`` (see ``Makefile``).

Exports:
    main — CLI entry; runs the seven v1 release gates sequentially.

Examples:
    >>> len(_GATES)
    7
"""

from __future__ import annotations

import subprocess
import sys

# (label, pytest node id)
_GATES: tuple[tuple[str, str], ...] = (
    (
        "1. onboard → valid sevn.json",
        "tests/onboarding/test_fresh_machine.py::test_onboard_config_fresh_machine_writes_valid_sevn_json",
    ),
    (
        "2. gateway daemon boots (lifecycle + boot sweep)",
        "tests/gateway/test_lifecycle.py::test_boot_sweep_invoked",
    ),
    (
        "3. channel turn (Triager → tier-B reply)",
        "tests/agent/test_e2e_single_message.py::test_e2e_single_message_triager_to_tier_b_reply",
    ),
    (
        "4. Mission Control real data (traces + session API)",
        "tests/ui/dashboard/test_real_data.py::test_traces_and_session_api_calls_return_seeded_rows",
    ),
    (
        "5. ActiveRunSnapshot survives restart",
        "tests/agent/test_active_run_snapshot_resume.py::test_active_run_snapshot_survives_restart_and_boot_sweep",
    ),
    (
        "6. schema upgrade preserves workspace (sevn migrate path)",
        "tests/onboarding/test_onboarding.py::test_upgrade_schema_inplace_v1_to_v2_backup_and_validate",
    ),
    (
        "7. tier-C turn (Triager → C/D harness reply)",
        "tests/agent/test_e2e_tier_c_smoke.py::test_e2e_tier_c_smoke_triager_to_cd_reply",
    ),
)


def main() -> int:
    """Run all v1 gates sequentially; return process exit code.

    Returns:
        int: ``0`` when all gates pass, else the failing pytest exit code.

    Examples:
        >>> main.__name__
        'main'
    """
    print("v1-smoke: probing seven user paths from plan/v1-release-scope.md\n")
    for label, node in _GATES:
        print(f"=== {label} ===")
        print(f"    {node}\n")
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            node,
            "-v",
            "--tb=short",
            "--strict-markers",
        ]
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            print(f"\nv1-smoke: FAILED at gate: {label}", file=sys.stderr)
            return result.returncode
        print()
    print("v1-smoke: all seven gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
