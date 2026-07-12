"""Docker evaluation seam (`specs/33-self-improvement.md` §10.4)."""

from __future__ import annotations

from pathlib import Path

from sevn.config.workspace_config import WorkspaceConfig
from sevn.self_improve.eval import (
    GOLDEN_ROUTING_CORPUS_REL,
    golden_routing_fixture_path,
    run_docker_eval_graph,
    run_live_replay_smoke,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_run_docker_eval_graph_returns_improve_job_result(tmp_path: Path) -> None:
    ws = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    result = run_docker_eval_graph(
        workspace=ws,
        job_bundle=tmp_path / "bundle",
        repo_root=_REPO_ROOT,
    )
    assert result.passed is True
    assert result.eval_report_path.name == "eval_report.json"


def test_golden_routing_fixture_path_points_at_wave5_corpus() -> None:
    path = golden_routing_fixture_path(repo_root=Path("/repo"))
    assert path.as_posix().endswith(GOLDEN_ROUTING_CORPUS_REL)
    assert path.name == "golden_routing.jsonl"


def test_live_replay_smoke_skipped_offline() -> None:
    ws = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    result = run_live_replay_smoke(workspace=ws, job_bundle=Path("/tmp/x"))
    assert result.status == "skipped"


def test_live_replay_smoke_fails_replay_without_stub(monkeypatch) -> None:
    monkeypatch.delenv("SEVN_TRIAGER_STUB", raising=False)
    ws = WorkspaceConfig(
        schema_version=1,
        self_improve={"enabled": False, "eval": {"eval_network": "replay"}},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    result = run_live_replay_smoke(
        workspace=ws,
        job_bundle=Path("/tmp/x"),
        repo_root=_REPO_ROOT,
    )
    assert result.status == "failed"


def test_live_replay_smoke_passes_in_replay_with_stub(monkeypatch) -> None:
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    ws = WorkspaceConfig(
        schema_version=1,
        self_improve={"enabled": False, "eval": {"eval_network": "replay"}},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    result = run_live_replay_smoke(
        workspace=ws,
        job_bundle=Path("/tmp/x"),
        repo_root=_REPO_ROOT,
    )
    assert result.status == "passed"
