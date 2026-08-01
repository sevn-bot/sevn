"""Gate tests for ``scripts/check_removed_browser_skill_ids.py`` (#117, #127)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "check_removed_browser_skill_ids.py"


def test_removed_browser_skill_ids_check_passes_on_trunk_tree() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
