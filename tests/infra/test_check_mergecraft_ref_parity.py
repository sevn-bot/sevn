"""Smoke-test the mergeCraft ref parity script (``specs/25-cicd-full.md``)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "check_mergecraft_ref_parity.py"


def test_check_mergecraft_ref_parity_exits_zero() -> None:
    """Against the real repo, the workflow and Makefile pins match → exit 0."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_check_mergecraft_ref_parity_detects_drift(tmp_path: Path) -> None:
    """A repo copy whose Makefile pin differs from the workflow → exit 1."""
    workflow = (REPO / ".github" / "workflows" / "mergecraft.yml").read_text(encoding="utf-8")
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")

    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "mergecraft.yml").write_text(workflow, encoding="utf-8")
    # Force drift: swap the Makefile default ref to a different value.
    drifted = makefile.replace(
        "$(SEVN_MERGECRAFT_REF),b8e83a82e97ed537706d9a712e59af9ef031588f)",
        "$(SEVN_MERGECRAFT_REF),0000000000000000000000000000000000000000)",
    )
    assert drifted != makefile, "test fixture must actually change the pinned ref"
    (tmp_path / "Makefile").write_text(drifted, encoding="utf-8")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "check_mergecraft_ref_parity.py").write_text(
        SCRIPT.read_text(encoding="utf-8"), encoding="utf-8"
    )

    proc = subprocess.run(
        [sys.executable, "scripts/check_mergecraft_ref_parity.py"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "drift" in proc.stderr.lower()
