"""Spec-kit allowlist (`specs/35-bot-evolution.md` EV-3/EV-6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.evolution import spec_kit
from sevn.workspace.layout import WorkspaceLayout


def test_allowlist_rejects_shell_argv(tmp_path: Path) -> None:
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(tmp_path / "sevn.json", cfg)
    with pytest.raises(ValueError, match="forbidden"):
        spec_kit.run_specify_allowlisted(
            "plan",
            ["sh", "-c", "echo pwn"],
            tmp_path,
            owner_principal="owner",
            ws=cfg,
            layout=layout,
            dry_run=True,
        )


def test_dry_run_plan_appends_audit_row(tmp_path: Path) -> None:
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(tmp_path / "sevn.json", cfg)
    result = spec_kit.run_specify_allowlisted(
        "plan",
        [],
        tmp_path,
        owner_principal="owner",
        ws=cfg,
        layout=layout,
        dry_run=True,
    )
    assert result.status == "dry_run"
    runs_path = layout.dot_sevn / "spec-kit" / "runs.jsonl"
    assert runs_path.is_file()
    row = json.loads(runs_path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert row["command"] == "plan"
