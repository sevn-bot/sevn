"""Tests for ``sevn.skills.security_scan`` (mocked subprocess)."""

from __future__ import annotations

import json
from pathlib import Path

from sevn.skills.security_scan import (
    BaselineSuppression,
    ScanIssue,
    apply_baseline,
    load_baseline,
    normalize_skill_path,
    parse_skillspector_report,
    run_skillspector_subprocess,
    scan_skill_path,
    write_workspace_scan_summary,
)


def test_parse_skillspector_report_extracts_issues() -> None:
    """SkillSpector JSON ``issues`` rows normalize to ScanIssue objects."""
    issues, score, severity = parse_skillspector_report(
        {
            "issues": [
                {
                    "id": "E2",
                    "severity": "HIGH",
                    "location": {"file": "scripts/run.py"},
                    "pattern": "Env Variable Harvesting",
                },
            ],
            "risk_assessment": {"score": 72, "severity": "HIGH"},
        },
    )
    assert issues[0].rule_id == "E2"
    assert issues[0].file == "scripts/run.py"
    assert score == 72
    assert severity == "HIGH"


def test_apply_baseline_drops_matching_rule_ids() -> None:
    """Baseline keys suppress issues by skill_path + rule_id."""
    remaining = apply_baseline(
        [ScanIssue("E2", "HIGH"), ScanIssue("P1", "CRITICAL")],
        skill_path="src/sevn/data/bundled_skills/core/last30days",
        baseline=[
            BaselineSuppression(
                "src/sevn/data/bundled_skills/core/last30days",
                "E2",
                "reviewed",
                "2026-06-14",
            ),
        ],
    )
    assert [issue.rule_id for issue in remaining] == ["P1"]


def test_run_skillspector_subprocess_parses_stdout(monkeypatch: object, tmp_path: Path) -> None:
    """Subprocess wrapper returns parsed JSON from stdout."""
    target = tmp_path / "skill"
    target.mkdir()
    payload = {"issues": [], "risk_assessment": {"score": 0, "severity": "LOW"}}

    class _Completed:
        returncode = 0
        stdout = json.dumps(payload)
        stderr = ""

    monkeypatch.setattr(
        "sevn.skills.security_scan.subprocess.run",
        lambda *_args, **_kwargs: _Completed(),
    )

    parsed = run_skillspector_subprocess(target, command=["skillspector"])
    assert parsed["issues"] == []


def test_scan_skill_path_missing_cli(tmp_path: Path, monkeypatch: object) -> None:
    """Missing SkillSpector CLI surfaces scanner_available=False."""
    monkeypatch.setattr("sevn.skills.security_scan.resolve_skillspector_command", lambda: None)
    target = tmp_path / "skill"
    target.mkdir()
    result = scan_skill_path(target)
    assert result.scanner_available is False
    assert result.error is not None


def test_load_baseline_from_file(tmp_path: Path) -> None:
    """Baseline JSON loads suppressions with normalized skill paths."""
    path = tmp_path / "baseline.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "suppressions": [
                    {
                        "skill_path": "core/last30days/",
                        "rule_id": "E2",
                        "reason": "ok",
                        "reviewed": "2026-06-14",
                    },
                ],
            },
        ),
        encoding="utf-8",
    )
    rows = load_baseline(path)
    assert rows[0].skill_path == "core/last30days"
    assert rows[0].rule_id == "E2"


def test_normalize_skill_path_strips_trailing_slash() -> None:
    """Baseline keys use stable posix paths."""
    assert normalize_skill_path("skills/user/foo/") == "skills/user/foo"


def test_write_workspace_scan_summary(tmp_path: Path) -> None:
    """Operator scans persist a compact summary under .sevn/."""
    out = write_workspace_scan_summary(
        tmp_path,
        scanned_paths=["skills/user/demo"],
        total_findings=1,
        high_critical=1,
    )
    assert out.is_file()
    blob = json.loads(out.read_text(encoding="utf-8"))
    assert blob["high_critical"] == 1
