"""Tests for advisory markdown link checker (D18; green after W8)."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_markdown_links.py"


def _load_check_markdown_links_main():
    if not SCRIPT_PATH.is_file():
        pytest.fail("scripts/check_markdown_links.py not implemented (green after W8)")
    spec = importlib.util.spec_from_file_location("check_markdown_links", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.main


def test_main_reports_good_and_broken_links(capsys: pytest.CaptureFixture[str]) -> None:
    """D18: ``check_markdown_links.main`` reports broken links and exits non-zero."""
    main = _load_check_markdown_links_main()
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        good = repo / "docs" / "good.md"
        good.parent.mkdir(parents=True)
        target = repo / "docs" / "target.md"
        target.write_text("# Target\n", encoding="utf-8")
        good.write_text("[ok](target.md)\n", encoding="utf-8")
        bad = repo / "docs" / "bad.md"
        bad.write_text("[missing](../nowhere/missing.md)\n", encoding="utf-8")
        exit_code = main([str(good.relative_to(repo)), str(bad.relative_to(repo))], repo_root=repo)
        captured = capsys.readouterr()
        assert exit_code != 0
        assert "bad.md" in captured.out or "bad.md" in captured.err
        assert "missing" in captured.out.lower() or "missing" in captured.err.lower()
