"""Gate tests for ``scripts/check_removed_browser_skill_ids.py`` (#117, #127)."""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "check_removed_browser_skill_ids.py"


def _run_script(*, cwd: Path = REPO) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def test_removed_browser_skill_ids_check_passes_on_trunk_tree() -> None:
    proc = _run_script()
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_removed_browser_skill_ids_check_detects_forbidden_directory(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    bundled = tmp_path / "src" / "sevn" / "data" / "bundled_skills" / "core" / "playwright-browser"
    bundled.mkdir(parents=True)
    check = importlib.import_module("scripts.check_removed_browser_skill_ids")
    monkeypatch.setattr(check, "REPO", tmp_path)
    monkeypatch.setattr(
        check, "BUNDLED_ROOT", tmp_path / "src" / "sevn" / "data" / "bundled_skills"
    )
    monkeypatch.setattr(
        check, "TOOLS_REGISTRY", tmp_path / "src" / "sevn" / "tools" / "registry.py"
    )
    assert check.main() == 1


def test_removed_browser_skill_ids_check_detects_forbidden_substring(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    skill_root = tmp_path / "src" / "sevn" / "data" / "bundled_skills" / "core" / "demo-skill"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text("see also x-use migration\n", encoding="utf-8")
    check = importlib.import_module("scripts.check_removed_browser_skill_ids")
    monkeypatch.setattr(check, "REPO", tmp_path)
    monkeypatch.setattr(
        check, "BUNDLED_ROOT", tmp_path / "src" / "sevn" / "data" / "bundled_skills"
    )
    monkeypatch.setattr(
        check, "TOOLS_REGISTRY", tmp_path / "src" / "sevn" / "tools" / "registry.py"
    )
    assert check.main() == 1


def test_removed_browser_skill_ids_check_ignores_false_positive_substring(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    skill_root = tmp_path / "src" / "sevn" / "data" / "bundled_skills" / "core" / "demo-skill"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text("configure max-users limit\n", encoding="utf-8")
    check = importlib.import_module("scripts.check_removed_browser_skill_ids")
    monkeypatch.setattr(check, "REPO", tmp_path)
    monkeypatch.setattr(
        check, "BUNDLED_ROOT", tmp_path / "src" / "sevn" / "data" / "bundled_skills"
    )
    monkeypatch.setattr(
        check, "TOOLS_REGISTRY", tmp_path / "src" / "sevn" / "tools" / "registry.py"
    )
    assert check.main() == 0
