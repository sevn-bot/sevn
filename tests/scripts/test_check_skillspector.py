"""Tests for ``scripts/check_skillspector.py`` (mocked subprocess)."""

from __future__ import annotations

import json
from pathlib import Path

import scripts.check_skillspector as checker

from sevn.skills.security_scan import ScanIssue, ScanResult


def test_main_passes_when_findings_are_baslined(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """Baseline suppressions must allow CI to pass on known bundled findings."""
    skill_dir = tmp_path / "core" / "last30days"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: last30days\n---\n", encoding="utf-8")

    targets = {
        "schema_version": 1,
        "targets": [{"id": "bundled-core", "kind": "skill_dir_glob", "path": "core/*/"}],
        "ci_options": {"no_llm": True, "fail_severities": ["HIGH", "CRITICAL"]},
    }
    baseline = {
        "schema_version": 1,
        "suppressions": [
            {
                "skill_path": "core/last30days",
                "rule_id": "E2",
                "reason": "test baseline",
                "reviewed": "2026-06-14",
            },
        ],
    }
    (tmp_path / "infra").mkdir()
    (tmp_path / "infra" / "skillspector-targets.json").write_text(
        json.dumps(targets),
        encoding="utf-8",
    )
    (tmp_path / "infra" / "skillspector-baseline.json").write_text(
        json.dumps(baseline),
        encoding="utf-8",
    )

    monkeypatch.setattr(checker, "REPO", tmp_path)
    monkeypatch.setattr(checker, "TARGETS_PATH", tmp_path / "infra" / "skillspector-targets.json")
    monkeypatch.setattr(checker, "BASELINE_PATH", tmp_path / "infra" / "skillspector-baseline.json")
    monkeypatch.setattr(
        checker, "REPORT_PATH", tmp_path / "reports" / "skillspector-ci-report.json"
    )
    monkeypatch.setattr(checker, "resolve_skillspector_command", lambda: ["skillspector"])

    def _fake_scan(path: Path, **kwargs: object) -> ScanResult:
        _ = kwargs
        return ScanResult(path=path)

    monkeypatch.setattr(checker, "scan_skill_path", _fake_scan)

    assert checker.main() == 0
    assert (tmp_path / "reports" / "skillspector-ci-report.json").is_file()


def test_main_fails_on_unbaseline_high_critical(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """Unbaseline'd HIGH/CRITICAL findings must exit non-zero."""
    skill_dir = tmp_path / "core" / "bad-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: bad-skill\n---\n", encoding="utf-8")

    targets = {
        "schema_version": 1,
        "targets": [{"id": "bundled-core", "kind": "skill_dir_glob", "path": "core/*/"}],
        "ci_options": {"no_llm": True, "fail_severities": ["HIGH", "CRITICAL"]},
    }
    (tmp_path / "infra").mkdir()
    (tmp_path / "infra" / "skillspector-targets.json").write_text(
        json.dumps(targets), encoding="utf-8"
    )
    (tmp_path / "infra" / "skillspector-baseline.json").write_text(
        json.dumps({"schema_version": 1, "suppressions": []}),
        encoding="utf-8",
    )

    monkeypatch.setattr(checker, "REPO", tmp_path)
    monkeypatch.setattr(checker, "TARGETS_PATH", tmp_path / "infra" / "skillspector-targets.json")
    monkeypatch.setattr(checker, "BASELINE_PATH", tmp_path / "infra" / "skillspector-baseline.json")
    monkeypatch.setattr(
        checker, "REPORT_PATH", tmp_path / "reports" / "skillspector-ci-report.json"
    )
    monkeypatch.setattr(checker, "resolve_skillspector_command", lambda: ["skillspector"])
    monkeypatch.setattr(
        checker,
        "scan_skill_path",
        lambda path, **kwargs: ScanResult(
            path=path,
            issues=[ScanIssue("P1", "CRITICAL", file="SKILL.md")],
            risk_score=100,
            risk_severity="CRITICAL",
        ),
    )

    assert checker.main() == 1
