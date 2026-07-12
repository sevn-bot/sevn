"""Evaluation graph regression (`specs/33-self-improvement.md` §10.1 Wave R)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.self_improve.eval import (
    ImproveJobResult,
    eval_report_passed,
    golden_routing_fixture_path,
    run_docker_eval_graph,
)
from sevn.self_improve.eval.replay import run_golden_routing_replay, run_live_replay_smoke
from sevn.self_improve.export import scaffold_improve_export_bundle
from sevn.self_improve.facade import ensure_preset_c_auto_merge_allowed
from sevn.workspace.layout import WorkspaceLayout

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_run_docker_eval_graph_writes_passing_report(tmp_path: Path) -> None:
    bundle = tmp_path / "job_bundle"
    ws = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    result = run_docker_eval_graph(workspace=ws, job_bundle=bundle, repo_root=_REPO_ROOT)
    assert isinstance(result, ImproveJobResult)
    assert result.passed is True
    assert result.eval_report_path.is_file()
    data = json.loads(result.eval_report_path.read_text(encoding="utf-8"))
    assert data["passed"] is True
    assert data["schema_version"] == 2
    assert "metrics" in data
    assert "thresholds" in data
    assert "deltas" in data
    assert data["metrics"]["golden_routing.intent_match_rate"] >= 0.95
    assert {seg["name"] for seg in data["segments"]} >= {
        "unit",
        "golden_routing",
        "live_replay_smoke",
    }


def test_golden_routing_replay_passes_on_wave5_corpus() -> None:
    segment = run_golden_routing_replay(repo_root=_REPO_ROOT, sample_size=20)
    assert segment.segment.status == "passed"
    assert segment.metrics.intent_match_rate >= 0.95
    assert golden_routing_fixture_path(repo_root=_REPO_ROOT).is_file()


def test_eval_report_passed_reads_json_flag(tmp_path: Path) -> None:
    report = tmp_path / "eval_report.json"
    report.write_text(json.dumps({"passed": False}), encoding="utf-8")
    assert eval_report_passed(report) is False
    report.write_text(json.dumps({"passed": True}), encoding="utf-8")
    assert eval_report_passed(report) is True


def test_preset_c_auto_merge_blocked_without_passing_eval() -> None:
    ws = WorkspaceConfig(
        schema_version=1,
        self_improve={
            "enabled": True,
            "preset": "C",
            "auto_merge_enabled": True,
            "hub": {"repo": "owner/repo"},
        },
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    with pytest.raises(RuntimeError, match="auto-merge blocked"):
        ensure_preset_c_auto_merge_allowed(workspace_config=ws, eval_report_path=None)


def test_preset_c_auto_merge_allowed_after_passing_eval(tmp_path: Path) -> None:
    ws = WorkspaceConfig(
        schema_version=1,
        self_improve={
            "enabled": True,
            "preset": "C",
            "auto_merge_enabled": True,
            "hub": {"repo": "owner/repo"},
        },
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    report = tmp_path / "eval_report.json"
    report.write_text(json.dumps({"passed": True}), encoding="utf-8")
    ensure_preset_c_auto_merge_allowed(workspace_config=ws, eval_report_path=report)


def test_live_replay_smoke_passes_with_stub_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    ws = WorkspaceConfig(
        schema_version=1,
        self_improve={"enabled": False, "eval": {"eval_network": "replay"}},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    result = run_live_replay_smoke(
        workspace=ws,
        job_bundle=tmp_path / "bundle",
        repo_root=_REPO_ROOT,
    )
    assert result.status == "passed"


def test_export_scaffold_writes_manifest(tmp_path: Path) -> None:
    layout = WorkspaceLayout(tmp_path / "sevn.json", tmp_path)
    eval_path = tmp_path / "eval_report.json"
    eval_path.write_text('{"passed": true}', encoding="utf-8")
    out = scaffold_improve_export_bundle(
        layout,
        "job-export-1",
        eval_report_path=eval_path,
        ttl_days=30,
    )
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["job_id"] == "job-export-1"
    assert (out / "eval_transcript.json").is_file()


def test_enqueue_with_export_enabled_scaffolds_bundle(tmp_path: Path) -> None:
    import asyncio
    import sqlite3

    from sevn.config.loader import load_workspace
    from sevn.self_improve.facade import enqueue_improve_job
    from sevn.self_improve.types import OwnerPrincipal
    from sevn.storage.migrate import apply_migrations

    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "self_improve": {
                    "enabled": True,
                    "preset": "A",
                    "export": {"enabled": True},
                },
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            },
        ),
        encoding="utf-8",
    )
    cfg, layout = load_workspace(sevn_json=sevn_json)
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    principal = OwnerPrincipal(principal_kind="owner", principal_id="me")

    async def _run() -> str:
        jid = await enqueue_improve_job(
            workspace_id="ws",
            experiment_id="exp",
            trigger="manual",
            correlation_id=None,
            owner_principal=principal,
            workspace_config=cfg,
            layout=layout,
            sqlite_conn=conn,
        )
        return jid  # noqa: RET504

    job_id = asyncio.run(_run())
    export_root = layout.dot_sevn / "improve" / "exports" / job_id
    assert (export_root / "manifest.json").is_file()
    conn.close()
