"""Smoke-test the pullfrog-py ref parity script (``specs/25-cicd-full.md``)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "check_pullfrog_ref_parity.py"


def test_check_pullfrog_ref_parity_exits_zero() -> None:
    """Against the real repo, the workflow and Makefile pins match → exit 0."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_check_pullfrog_ref_parity_detects_drift(tmp_path: Path) -> None:
    """A repo copy whose Makefile pin differs from the workflow → exit 1."""
    workflow = (REPO / ".github" / "workflows" / "pullfrog.yml").read_text(encoding="utf-8")
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")

    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "pullfrog.yml").write_text(workflow, encoding="utf-8")
    # Force drift: swap the Makefile default ref to a different value.
    drifted = makefile.replace(
        "$(SEVN_PULLFROG_PY_REF),dc98633049a6f473124e013ffd1e446d7e10b70a)",
        "$(SEVN_PULLFROG_PY_REF),0000000000000000000000000000000000000000)",
    )
    assert drifted != makefile, "test fixture must actually change the pinned ref"
    (tmp_path / "Makefile").write_text(drifted, encoding="utf-8")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "check_pullfrog_ref_parity.py").write_text(
        SCRIPT.read_text(encoding="utf-8"), encoding="utf-8"
    )

    proc = subprocess.run(
        [sys.executable, "scripts/check_pullfrog_ref_parity.py"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "drift" in proc.stderr.lower()
