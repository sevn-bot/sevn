"""Improve job worker integration (`plan/full-tracing-eval-wave-plan.md` Wave E-1)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

import pytest  # noqa: TC002 — runtime fixtures and monkeypatch

from sevn.config.loader import load_workspace
from sevn.config.workspace_config import (
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    SelfImproveHubWorkspaceConfig,
    SelfImproveWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.self_improve.eval import ImproveJobResult
from sevn.self_improve.facade import enqueue_improve_job
from sevn.self_improve.jobs.store import fetch_job_row
from sevn.self_improve.jobs.worker import ImproveJobWorker
from sevn.self_improve.paths import job_bundle_dir
from sevn.self_improve.proposer.agent import PatchProposal
from sevn.self_improve.types import ImproveJobId, OwnerPrincipal
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout

if TYPE_CHECKING:
    from sevn.agent.tracing.sink import TraceEvent


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
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "passed": True,
                "segments": [],
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )
    return ImproveJobResult(passed=True, eval_report_path=report_path, segments=())


def test_worker_transitions_to_awaiting_review_with_fake_eval(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "self_improve": {"enabled": True, "preset": "A"},
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )
    cfg, layout = load_workspace(sevn_json=sevn_json)
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
    row = fetch_job_row(conn, job_id=ImproveJobId(job_id))
    assert row is not None
    assert row.state == "awaiting_review"
    assert row.eval_report_path is not None
    bundle = job_bundle_dir(layout, str(job_id))
    assert (bundle / "shortlist.json").is_file()
    assert (bundle / "eval_report.json").is_file()
    report = json.loads((bundle / "eval_report.json").read_text(encoding="utf-8"))
    assert report["passed"] is True
    conn.close()


def test_worker_blocks_when_eval_fails(tmp_path: Path) -> None:
    def _failing_eval(
        *,
        workspace: object,
        job_bundle: Path,
        repo_root: Path | None = None,
    ) -> ImproveJobResult:
        _ = workspace
        _ = repo_root
        job_bundle.mkdir(parents=True, exist_ok=True)
        report_path = job_bundle / "eval_report.json"
        report_path.write_text(json.dumps({"passed": False}), encoding="utf-8")
        return ImproveJobResult(passed=False, eval_report_path=report_path, segments=())

    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "self_improve": {"enabled": True, "preset": "A"},
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )
    cfg, layout = load_workspace(sevn_json=sevn_json)
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    principal = OwnerPrincipal(principal_kind="owner", principal_id="me")
    worker = ImproveJobWorker(
        sqlite_conn=conn,
        workspace_config=cfg,
        layout=layout,
        workspace_id="ws",
        eval_runner=_failing_eval,
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
        )
        await worker.process_once()
        return job_id

    job_id = asyncio.run(_run())
    row = fetch_job_row(conn, job_id=ImproveJobId(job_id))
    assert row is not None
    assert row.state == "blocked"
    assert row.blocked_reason == "eval_failed"
    conn.close()


class _RecordingSink:
    """Capture trace emit payloads for worker assertions."""

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def emit(self, event: TraceEvent) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        return None

    async def close(self) -> None:
        return None


def test_worker_preset_b_mocked_agent_emits_patch_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SEVN_PATCH_AUTHOR_STUB", raising=False)

    async def _fake_agent(**kwargs: object) -> PatchProposal:
        _ = kwargs
        return PatchProposal(
            target_path="workspace/prompts/seimprove-mock.md",
            content="# improved prompt\n",
        )

    monkeypatch.setattr(
        "sevn.self_improve.proposer.agent.run_patch_proposal_agent",
        _fake_agent,
    )

    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "self_improve": {
                    "enabled": True,
                    "preset": "B",
                    "hub": {"repo": "owner/repo"},
                },
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )
    cfg = WorkspaceConfig(
        schema_version=1,
        self_improve=SelfImproveWorkspaceConfig(
            enabled=True,
            preset="B",
            hub=SelfImproveHubWorkspaceConfig(repo="owner/repo"),
        ),
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, cfg)
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    principal = OwnerPrincipal(principal_kind="owner", principal_id="me")
    sink = _RecordingSink()
    worker = ImproveJobWorker(
        sqlite_conn=conn,
        workspace_config=cfg,
        layout=layout,
        workspace_id="ws",
        eval_runner=_fake_eval_runner,
        trace_sink=sink,
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
    meta = json.loads((bundle / "patch" / "meta.json").read_text(encoding="utf-8"))
    assert meta["author"] == "pydantic_agent"
    diff_text = (bundle / "patch" / "diff.patch").read_text(encoding="utf-8")
    assert "improved prompt" in diff_text
    assert "self_improve_deterministic_stub" not in diff_text
    row = fetch_job_row(conn, job_id=ImproveJobId(job_id))
    assert row is not None
    assert row.state == "awaiting_review"
    kinds = [event.kind for event in sink.events]
    assert "self_improve.patch_ready" in kinds
    conn.close()
