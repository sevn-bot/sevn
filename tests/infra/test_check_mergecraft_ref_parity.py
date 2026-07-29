"""Smoke-test the mergeCraft ref parity script (``specs/25-cicd-full.md``)."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "check_mergecraft_ref_parity.py"


def test_check_mergecraft_ref_parity_exits_zero() -> None:
    """Against the real repo, the workflow and Makefile refs match → exit 0."""
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
    # Force drift: swap the Makefile default ref to a different value. Matched by
    # pattern rather than by literal so this fixture survives future ref changes
    # (SHA -> branch and back) without needing an edit here.
    drifted, count = re.subn(
        r"(MERGECRAFT_REF\s*\?=\s*\$\(if\s*\$\(SEVN_MERGECRAFT_REF\)\s*,\s*"
        r"\$\(SEVN_MERGECRAFT_REF\)\s*,\s*)[^),\s]+(\s*\))",
        r"\1definitely-not-the-workflow-ref\2",
        makefile,
    )
    assert count == 1, "test fixture must match exactly one MERGECRAFT_REF default"
    assert drifted != makefile, "test fixture must actually change the ref"
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
