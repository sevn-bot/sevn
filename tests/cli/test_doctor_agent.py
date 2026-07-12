"""Doctor ``--with-agent`` orchestrator tests (W4 — mocked model, no live LLM)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sevn.agent.diagnostics.runtime import DiagnosticPlan, DiagnosticStep
from sevn.cli.app import app
from sevn.cli.doctor.agent import run_doctor_with_agent
from sevn.cli.doctor.checks import CheckResult, DoctorCheck
from sevn.cli.doctor.probes import DoctorRunOptions
from sevn.cli.doctor.sections import section_for, title_for


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _install_doctor_workspace(home: Path) -> None:
    ws = home / "workspace"
    ws.mkdir(parents=True)
    (ws / "sevn.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            },
        ),
        encoding="utf-8",
    )
    (ws / ".llmignore").mkdir()


def _warn_llmignore_result() -> CheckResult:
    result = CheckResult()
    result.add(
        DoctorCheck(
            "llmignore",
            section_for("llmignore"),
            title_for("llmignore"),
            False,
            severity="warn",
            detail="missing blocked/",
        ),
    )
    return result


def test_run_doctor_with_agent_confirm_gating_blocks_without_yes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    _install_doctor_workspace(home)
    monkeypatch.setenv("SEVN_HOME", str(home))

    from sevn.config.workspace_config import WorkspaceConfig

    class _Bw:
        layout = type("L", (), {"content_root": home / "workspace"})()
        config = WorkspaceConfig.minimal()

    plan = DiagnosticPlan(
        summary="fix layout",
        steps=[
            DiagnosticStep(
                check_ids=["llmignore"],
                title="Create .llmignore",
                action_type="auto_fix",
            ),
        ],
    )
    result = _warn_llmignore_result()
    refreshed, report = run_doctor_with_agent(
        bw=_Bw(),
        result=result,
        yes=False,
        interactive=False,
        probe_options=DoctorRunOptions(),
        plan_override=plan,
    )
    assert refreshed.checks[0].id == "llmignore"
    assert report.steps[0].status == "skipped"


def test_run_doctor_with_agent_yes_applies_auto_fix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os
    import time

    home = tmp_path / "home"
    ws = home / "workspace"
    ws.mkdir(parents=True)
    (ws / "sevn.json").write_text('{"schema_version":1}', encoding="utf-8")
    monkeypatch.setenv("SEVN_HOME", str(home))
    lock_path = home / "run" / "sevn-cli.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("999999\n", encoding="utf-8")
    os.utime(lock_path, (time.time() - 7200, time.time() - 7200))

    from sevn.config.workspace_config import WorkspaceConfig

    class _Bw:
        layout = type("L", (), {"content_root": ws})()
        config = WorkspaceConfig.minimal()
        sevn_json_path = ws / "sevn.json"

    def _noop_probes(_bw: object, _result: CheckResult, *, options: object) -> None:
        _ = _bw, options

    monkeypatch.setattr("sevn.cli.doctor.agent.run_doctor_probes", _noop_probes)

    plan = DiagnosticPlan(
        summary="clear stale lock",
        steps=[
            DiagnosticStep(
                check_ids=["operator_lock"],
                title="Remove stale operator lock",
                action_type="auto_fix",
            ),
        ],
    )
    result = CheckResult()
    result.add(
        DoctorCheck(
            "operator_lock",
            section_for("operator_lock"),
            title_for("operator_lock"),
            False,
            severity="warn",
            detail="stale lock",
        ),
    )
    _refreshed, report = run_doctor_with_agent(
        bw=_Bw(),
        result=result,
        yes=True,
        interactive=False,
        probe_options=DoctorRunOptions(),
        plan_override=plan,
    )
    assert report.steps[0].status == "applied"


def test_run_doctor_with_agent_rejects_non_allowlisted_command() -> None:
    from sevn.config.workspace_config import WorkspaceConfig

    class _Bw:
        layout = type("L", (), {"content_root": Path("/tmp")})()
        config = WorkspaceConfig.minimal()

    plan = DiagnosticPlan(
        summary="bad cmd",
        steps=[
            DiagnosticStep(
                check_ids=["gateway_health"],
                title="Run shell",
                action_type="sevn_command",
                command="curl http://evil",
            ),
        ],
    )
    _result, report = run_doctor_with_agent(
        bw=_Bw(),
        result=_warn_llmignore_result(),
        yes=True,
        interactive=False,
        probe_options=DoctorRunOptions(),
        plan_override=plan,
    )
    assert report.steps[0].status == "rejected"


def test_doctor_with_agent_json_shape(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    _install_doctor_workspace(home)
    monkeypatch.setenv("SEVN_HOME", str(home))

    def _fake_probes(_bw: object, result: CheckResult, *, options: object) -> None:
        _ = _bw, options
        result.add(
            DoctorCheck(
                "llmignore",
                section_for("llmignore"),
                title_for("llmignore"),
                False,
                severity="warn",
                detail="missing blocked/",
            ),
        )

    plan = DiagnosticPlan(
        summary="plan",
        steps=[
            DiagnosticStep(
                check_ids=["llmignore"],
                title="manual review",
                action_type="manual",
                explanation="operator must review",
            ),
        ],
    )

    monkeypatch.setattr("sevn.cli.commands.doctor.run_doctor_probes", _fake_probes)

    def _with_plan_override(**kwargs: object) -> object:
        return run_doctor_with_agent(**{**kwargs, "plan_override": plan})  # type: ignore[arg-type]

    monkeypatch.setattr("sevn.cli.commands.doctor.run_doctor_with_agent", _with_plan_override)
    result = runner.invoke(app, ["doctor", "--with-agent", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    data = payload["data"]
    assert "agent_plan" in data
    assert data["agent_plan"]["summary"] == "plan"
    assert data["agent_steps"][0]["status"] == "manual"
