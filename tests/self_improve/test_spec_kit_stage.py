"""Spec-kit improve plan stage (`specs/33-self-improvement.md` §4.1 stage 4a)."""

from __future__ import annotations

import json
from pathlib import Path

from sevn.config.workspace_config import (
    SelfImproveSpecKitConfig,
    SelfImproveWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.self_improve.spec_kit_stage import (
    improve_spec_kit_dir,
    run_improve_spec_kit_plan,
    spec_kit_plan_stage_enabled,
    write_context_pack,
)
from sevn.workspace.layout import WorkspaceLayout


def test_spec_kit_plan_stage_enabled_when_configured() -> None:
    ws = WorkspaceConfig(
        schema_version=1,
        self_improve=SelfImproveWorkspaceConfig(
            spec_kit=SelfImproveSpecKitConfig(enabled=True, require_plan_before_patch=True),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    assert spec_kit_plan_stage_enabled(ws) is True


def test_run_improve_spec_kit_plan_writes_plan_md(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    ws = WorkspaceConfig(
        schema_version=1,
        self_improve=SelfImproveWorkspaceConfig(
            spec_kit=SelfImproveSpecKitConfig(enabled=True, require_plan_before_patch=True),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, ws)
    bundle = tmp_path / ".sevn" / "improve" / "job-1"
    write_context_pack(
        bundle,
        job_id="job-1",
        shortlist={
            "schema_version": 1,
            "candidates": [],
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    plan_path = run_improve_spec_kit_plan(
        job_id="job-1",
        job_bundle=bundle,
        ws=ws,
        layout=layout,
        dry_run=True,
    )
    assert plan_path == improve_spec_kit_dir(bundle) / "plan.md"
    assert plan_path.is_file()
    text = plan_path.read_text(encoding="utf-8")
    assert "job-1" in text
    context = json.loads((bundle / "context_pack.json").read_text(encoding="utf-8"))
    assert context["job_id"] == "job-1"
