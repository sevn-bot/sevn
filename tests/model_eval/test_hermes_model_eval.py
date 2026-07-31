"""Hermes model eval suite and replay report tests (#91, W32)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from sevn.config.workspace_config import WorkspaceConfig
from sevn.model_eval.config import D21_DECISION, hermes_model_eval_enabled
from sevn.model_eval.replay import run_replay_comparison_report
from sevn.model_eval.suite import hermes_eval_suite_case_ids, scenario_classes

_SKILL_ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "sevn"
    / "data"
    / "bundled_skills"
    / "core"
    / "hermes-model-eval"
)


def test_d21_decision_recorded() -> None:
    """W32.1: D21 gate documents golden_llm-only path."""
    assert "spy_hermes" in D21_DECISION
    assert "golden_llm" in D21_DECISION


def test_suite_covers_scenario_classes() -> None:
    """W32.3: fixed suite spans tool_call, coding, summarization, policy."""
    classes = scenario_classes()
    assert set(classes) == {"tool_call", "coding", "summarization", "policy_approval"}
    suite = hermes_eval_suite_case_ids()
    assert "read_01" in suite
    assert "summarize_01" in suite
    assert "policy_approval_01" in suite


def test_replay_report_passes_tokenlessly() -> None:
    """W32.2/W32.4: tokenless replay report runs on golden_llm harness."""
    report = run_replay_comparison_report()
    assert report.mode == "replay"
    assert report.overall_pass_rate >= 1.0
    assert len(report.cases) == len(hermes_eval_suite_case_ids())


def test_hermes_model_eval_default_off() -> None:
    """D9: skill toggle defaults off."""
    assert hermes_model_eval_enabled(WorkspaceConfig.minimal()) is False


def test_list_suite_script_emits_json() -> None:
    """Bundled list_suite.py prints scenario map."""
    script = _SKILL_ROOT / "scripts" / "list_suite.py"
    proc = subprocess.run(
        [sys.executable, str(script)],
        check=True,
        capture_output=True,
        text=True,
        cwd=str(_SKILL_ROOT / "scripts"),
    )
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["ok"] is True
    assert "tool_call" in payload["scenarios"]


def test_replay_report_script_emits_json() -> None:
    """Bundled replay_report.py runs tokenless comparison."""
    script = _SKILL_ROOT / "scripts" / "replay_report.py"
    proc = subprocess.run(
        [sys.executable, str(script), "--case-id", "read_01"],
        check=True,
        capture_output=True,
        text=True,
        cwd=str(_SKILL_ROOT / "scripts"),
    )
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["ok"] is True
    assert payload["mode"] == "replay"
