"""Tests for ``scripts/quality/check_stale_xfail.py``."""

from __future__ import annotations

from pathlib import Path

from scripts.quality.check_stale_xfail import find_stale_xfail_violations


def test_find_stale_xfail_violations_flags_strict_false(tmp_path: Path) -> None:
    marker = "@pytest.mark.xfail(reason=" + '"green after W5", strict=False)'
    bad = tmp_path / "test_bad.py"
    bad.write_text(
        f"{marker}\ndef test_example():\n    assert True\n",
        encoding="utf-8",
    )
    good = tmp_path / "test_good.py"
    good.write_text(
        '@pytest.mark.xfail(reason="known upstream bug", strict=True)\n'
        "def test_other():\n"
        "    assert False\n",
        encoding="utf-8",
    )
    hits = find_stale_xfail_violations(tmp_path)
    assert len(hits) == 1
    assert hits[0].path.name == "test_bad.py"
    assert "strict=False" in hits[0].reason


def test_repo_tests_have_no_stale_xfail_markers() -> None:
    assert find_stale_xfail_violations() == []
