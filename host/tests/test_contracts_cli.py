"""Contract export and drift check (D18, D21)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from support.repo import repo_root


def test_contracts_export_writes_files(tmp_path: Path) -> None:
    from sevn.cli import app
    from typer.testing import CliRunner

    result = CliRunner().invoke(app, ["contracts", "export", "--root", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    schema = tmp_path / "contracts" / "protocol.schema.json"
    methods = tmp_path / "web" / "src" / "contracts" / "methods.ts"
    text = schema.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert text == json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n"
    method_text = methods.read_text(encoding="utf-8")
    for name in ("system.info", "system.ping", "sync.since"):
        assert name in method_text
    assert "mutating" in method_text


def test_contracts_check_detects_drift() -> None:
    root = repo_root()
    schema = root / "contracts" / "protocol.schema.json"
    original = schema.read_text(encoding="utf-8")
    script = root / "scripts" / "check_contracts.py"

    def run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603
            [sys.executable, str(script)],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )

    clean = run()
    assert clean.returncode == 0, clean.stderr
    schema.write_text(original + "\n", encoding="utf-8")
    try:
        drifted = run()
        assert drifted.returncode == 1
    finally:
        schema.write_text(original, encoding="utf-8")
