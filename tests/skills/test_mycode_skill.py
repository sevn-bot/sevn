"""Bundled ``mycode`` skill script subprocess tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from sevn.data.bundled_skills import BUNDLED_SKILLS_ROOT
from sevn.skills.manager import SkillsManager

_SKILL_ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "sevn"
    / "data"
    / "bundled_skills"
    / "core"
    / "mycode"
)
_SCAN_SCRIPT = _SKILL_ROOT / "scripts" / "scan.py"


@pytest.fixture(autouse=True)
def _reset_skill_singletons() -> None:
    SkillsManager.reset_singletons_for_tests()
    yield
    SkillsManager.reset_singletons_for_tests()


def test_scan_script_writes_mycode_md(tmp_path: Path) -> None:
    """``scripts/scan.py`` writes a MYCODE.md digest under ``.sevn/``."""
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
    assert output.is_file()
    body = output.read_text(encoding="utf-8")
    assert body.startswith("# MYCODE")
    assert "sample.py" in body


def test_scan_script_default_output_uses_repo_index_dir(tmp_path: Path) -> None:
    """Default output lands under ``.index/mycode/MYCODE.md``."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "sample.py").write_text("def greet():\n    return 'hi'\n", encoding="utf-8")
    output = repo / ".index" / "mycode" / "MYCODE.md"

    proc = subprocess.run(
        [sys.executable, str(_SCAN_SCRIPT), "--root", str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert output.is_file()
    body = output.read_text(encoding="utf-8")
    assert body.startswith("# MYCODE")
    assert "sample.py" in body


def test_mycode_scan_index_alias_resolves_to_mycode(tmp_path: Path) -> None:
    """Legacy ``mycode_scan`` index alias resolves to bundled ``mycode`` skill."""
    core_root = BUNDLED_SKILLS_ROOT
    man = SkillsManager.shared(tmp_path, (core_root,))
    assert "mycode" in man.index.lines
    assert "mycode_scan" in man.index.lines
    rec = man.get_record("mycode_scan")
    assert rec.canonical_id == "mycode"
    assert (rec.skill_dir / "scripts" / "scan.py").is_file()
