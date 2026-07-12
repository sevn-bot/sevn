"""Bundled ``mycode`` scan script stdout/stderr contract tests (reactive-plum Wave 5)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_SCAN_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "sevn"
    / "data"
    / "bundled_skills"
    / "core"
    / "mycode"
    / "scripts"
    / "scan.py"
)


def test_scan_script_emits_single_json_line_on_stdout(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "sample.py").write_text("def greet():\n    return 'hi'\n", encoding="utf-8")
    output = repo / ".sevn" / "MYCODE.md"

    proc = subprocess.run(
        [sys.executable, str(_SCAN_SCRIPT), "--root", str(repo), "--output", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    stdout_lines = [line for line in proc.stdout.splitlines() if line.strip()]
    assert len(stdout_lines) == 1
    payload = json.loads(stdout_lines[0])
    assert payload["ok"] is True
    assert payload["path"] == str(output.resolve())
    assert output.is_file()
    assert "Scanning" in proc.stderr
