"""Smoke-test the infra parity script (``specs/25-cicd-full.md`` §10.4)."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_check_infra_parity_exits_zero() -> None:
    proc = subprocess.run(
        ["uv", "run", "python", "scripts/check_infra_parity.py"],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
