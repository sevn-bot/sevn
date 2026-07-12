"""Tests for ``scripts/check_tools_skills_inventory.py`` worksheet parsing."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.check_tools_skills_inventory import (
    REPO,
    SKILLS_WORKSHEET,
    TOOLS_WORKSHEET,
    build_gap_report,
    parse_skills_worksheet,
    parse_tools_worksheet,
)

_WORKSHEETS_PRESENT = TOOLS_WORKSHEET.is_file() and SKILLS_WORKSHEET.is_file()
_SKIP_WORKSHEETS = pytest.mark.skipif(
    not _WORKSHEETS_PRESENT,
    reason="plan/architecture worksheets are gitignored and absent in CI checkout",
)


@_SKIP_WORKSHEETS
def test_parse_tools_worksheet_includes_meta_and_file_ops() -> None:
    rows = parse_tools_worksheet()
    names = {row.name for row in rows}
    assert "load_tool" in names
    assert "read" in names
    assert "sandbox_exec" in names
    assert "lcm_grep" not in names
    assert "agent" not in names


@_SKIP_WORKSHEETS
def test_parse_skills_worksheet_includes_core_rows() -> None:
    rows = parse_skills_worksheet()
    names = {row.name for row in rows}
    assert "lcm" in names
    assert "sessions_management" in names
    assert "mycode" in names


@_SKIP_WORKSHEETS
def test_build_gap_report_writes_expected_keys(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "gap.json"
    monkeypatch.setattr(
        "scripts.check_tools_skills_inventory.GAP_REPORT",
        out,
    )
    report = build_gap_report()
    assert report["tool_keep_count"] > 0
    assert report["skill_keep_count"] > 0
    assert report["total_gap_count"] == report["tool_gap_count"] + report["skill_gap_count"]
    assert (REPO / "plan" / "architecture" / "04-tools-inventory-decisions.md").is_file()
