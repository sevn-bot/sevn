"""Triager Graphify orientation block (`specs/28-code-understanding.md` §2.5)."""

from __future__ import annotations

from pathlib import Path

from sevn.agent.triager.context import TriagePromptContext
from sevn.agent.triager.prompt import _suffix_segment
from sevn.code_understanding.models import (
    CodeUnderstandingSettings,
    GraphifyProfile,
    GraphifySettings,
)
from sevn.code_understanding.triager_orientation import orientation_block_for_workspace
from sevn.config.workspace_config import WorkspaceConfig


def test_orientation_empty_when_graphify_disabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ws_root = tmp_path / "operator-ws"
    ws_root.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SEVN_REPO_ROOT", raising=False)
    monkeypatch.delenv("SEVN_SOURCE_ROOT", raising=False)
    monkeypatch.setattr(
        "sevn.code_understanding.triager_orientation.resolve_sevn_checkout_for_workspace",
        lambda *_a, **_k: None,
    )
    ws = WorkspaceConfig(
        schema_version=1,
        code_understanding=CodeUnderstandingSettings(
            graphify=GraphifySettings(enabled=False),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    assert orientation_block_for_workspace(ws, content_root=ws_root) == ""


def test_orientation_in_suffix_when_profile_has_report(tmp_path: Path) -> None:
    out_dir = tmp_path / ".index" / "graphify"
    out_dir.mkdir(parents=True)
    (out_dir / "GRAPH_REPORT.md").write_text("# map\n", encoding="utf-8")
    profile = GraphifyProfile(
        id="default",
        root_path=str(tmp_path),
        output_dir=str(out_dir),
    )
    ws = WorkspaceConfig(
        schema_version=1,
        code_understanding=CodeUnderstandingSettings(
            graphify=GraphifySettings(enabled=True, profiles=[profile]),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    block = orientation_block_for_workspace(ws, content_root=tmp_path)
    assert "[code_orientation]" in block
    ctx = TriagePromptContext(current_message="hi", code_orientation_block=block)
    suffix = _suffix_segment(ctx)
    assert "Graphify profile default" in suffix
