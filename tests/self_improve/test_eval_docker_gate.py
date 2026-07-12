"""Docker-required eval gate (`plan/full-tracing-eval-wave-plan.md` E-0A)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from sevn.config.workspace_config import WorkspaceConfig
from sevn.self_improve.eval import (
    ImproveJobResult,
    eval_docker_required,
    eval_in_process_override,
    run_docker_eval_graph,
)
from sevn.self_improve.eval.docker import IMPROVE_EVALS_COMPOSE_FILE, IMPROVE_EVALS_SERVICE
from sevn.self_improve.eval.replay import EvalSegmentResult

if TYPE_CHECKING:
    import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_eval_docker_required_defaults_true() -> None:
    ws = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    assert eval_docker_required(ws) is True


def test_eval_docker_required_respects_workspace_flag() -> None:
    ws = WorkspaceConfig(
        schema_version=1,
        self_improve={"enabled": True, "eval": {"docker_required": False}},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    assert eval_docker_required(ws) is False


def test_eval_in_process_override_truthy_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEVN_IMPROVE_EVAL_IN_PROCESS", raising=False)
    assert eval_in_process_override() is False
    monkeypatch.setenv("SEVN_IMPROVE_EVAL_IN_PROCESS", "1")
    assert eval_in_process_override() is True


def test_run_docker_eval_graph_delegates_to_compose_when_required(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SEVN_IMPROVE_EVAL_IN_PROCESS", raising=False)
    bundle = tmp_path / "bundle"
    bundle.mkdir(parents=True, exist_ok=True)
    report = bundle / "eval_report.json"
    stub = ImproveJobResult(
        passed=True,
        eval_report_path=report,
        segments=(EvalSegmentResult(name="unit", status="passed", detail="ok"),),
    )
    ws = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    with patch(
        "sevn.self_improve.eval.docker.run_eval_in_docker", return_value=stub
    ) as docker_eval:
        result = run_docker_eval_graph(
            workspace=ws,
            job_bundle=bundle,
            repo_root=_REPO_ROOT,
        )
    docker_eval.assert_called_once()
    assert result.passed is True


def test_run_docker_eval_graph_in_process_when_override_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEVN_IMPROVE_EVAL_IN_PROCESS", "1")
    ws = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    bundle = tmp_path / "bundle"
    with patch("sevn.self_improve.eval.docker.run_eval_in_docker") as docker_eval:
        result = run_docker_eval_graph(
            workspace=ws,
            job_bundle=bundle,
            repo_root=_REPO_ROOT,
        )
    docker_eval.assert_not_called()
    assert result.passed is True
    assert result.eval_report_path.is_file()


def test_run_eval_in_docker_invokes_compose() -> None:
    from sevn.self_improve.eval.docker import run_eval_in_docker

    # Under repo root for compose bind-mount; /.sevn/ is gitignored (local test artefact).
    bundle = _REPO_ROOT / ".sevn" / "improve" / "eval-compose-test" / "bundle"
    bundle.mkdir(parents=True, exist_ok=True)
    report = bundle / "eval_report.json"
    report.write_text(
        '{"passed": true, "segments": [{"name": "unit", "status": "passed", "detail": "ok"}]}',
        encoding="utf-8",
    )
    ws = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    with patch("sevn.self_improve.eval.docker.subprocess.run") as proc_run:
        proc_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = run_eval_in_docker(workspace=ws, job_bundle=bundle, repo_root=_REPO_ROOT)
    proc_run.assert_called_once()
    cmd = proc_run.call_args[0][0]
    assert cmd[0] == "docker"
    assert any(IMPROVE_EVALS_COMPOSE_FILE in part for part in cmd)
    assert IMPROVE_EVALS_SERVICE in cmd
    assert str(bundle.relative_to(_REPO_ROOT)) in cmd
    assert result.passed is True
