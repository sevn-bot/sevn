"""Improve worker blocks patch without plan when spec-kit stage is on."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest  # noqa: TC002 — monkeypatch fixture

from sevn.config.workspace_config import (
    SelfImproveHubWorkspaceConfig,
    SelfImproveSpecKitConfig,
    SelfImproveWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.self_improve.eval import ImproveJobResult
from sevn.self_improve.facade import enqueue_improve_job
from sevn.self_improve.jobs.store import fetch_job_row
from sevn.self_improve.jobs.worker import ImproveJobWorker
from sevn.self_improve.paths import job_bundle_dir
from sevn.self_improve.types import ImproveJobId, OwnerPrincipal
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout


def _fake_eval_runner(
    *,
    workspace: object,
    job_bundle: Path,
    repo_root: Path | None = None,
) -> ImproveJobResult:
    _ = workspace
    _ = repo_root
    job_bundle.mkdir(parents=True, exist_ok=True)
    report_path = job_bundle / "eval_report.json"
    report_path.write_text(json.dumps({"passed": True}), encoding="utf-8")
    return ImproveJobResult(passed=True, eval_report_path=report_path, segments=())


def test_preset_b_writes_plan_before_patch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEVN_PATCH_AUTHOR_STUB", "1")
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "self_improve": {
                    "enabled": True,
                    "preset": "B",
                    "spec_kit": {"enabled": True, "require_plan_before_patch": True},
                },
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            },
        ),
        encoding="utf-8",
    )
    cfg = WorkspaceConfig(
        schema_version=1,
        self_improve=SelfImproveWorkspaceConfig(
            enabled=True,
            preset="B",
            hub=SelfImproveHubWorkspaceConfig(repo="sevn-bot/sevn"),
            spec_kit=SelfImproveSpecKitConfig(enabled=True, require_plan_before_patch=True),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, cfg)
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    principal = OwnerPrincipal(principal_kind="owner", principal_id="me")
    worker = ImproveJobWorker(
        sqlite_conn=conn,
        workspace_config=cfg,
        layout=layout,
        workspace_id="ws",
        eval_runner=_fake_eval_runner,
    )

    async def _run() -> ImproveJobId:
        job_id = await enqueue_improve_job(
            workspace_id="ws",
            experiment_id="exp",
            trigger="manual",
            correlation_id=None,
            owner_principal=principal,
            workspace_config=cfg,
            layout=layout,
            sqlite_conn=conn,
            improve_job_worker=worker,
        )
        assert await worker.process_once() is True
        return job_id

    job_id = asyncio.run(_run())
    bundle = job_bundle_dir(layout, str(job_id))
    plan = bundle / "spec-kit" / "plan.md"
    assert plan.is_file()
    body_path = bundle / "patch" / "diff.patch"
    assert body_path.is_file()
    diff_text = body_path.read_text(encoding="utf-8")
    assert "spec_kit_plan_excerpt" in diff_text
    assert "Self-improve plan" in diff_text or "job-" in diff_text
    row = fetch_job_row(conn, job_id=ImproveJobId(job_id))
    assert row is not None
    assert row.state == "awaiting_review"
    conn.close()
