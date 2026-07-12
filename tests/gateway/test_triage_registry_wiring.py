"""Triager registry must reflect ``build_session_registry`` (not an empty snapshot)."""

from __future__ import annotations

from pathlib import Path

from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.triage_context import registry_snapshot_from_tool_set
from sevn.tools.registry import build_session_registry


def test_registry_snapshot_includes_file_ops_and_skills(tmp_path: Path) -> None:
    """Pre-triage snapshot lists native file tools and bundled skill summaries."""
    workspace = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    content_root = tmp_path
    (content_root / "skills" / "core").mkdir(parents=True, exist_ok=True)

    _exe, tool_set = build_session_registry(
        workspace_config=workspace,
        workspace_root=content_root,
    )
    snap = registry_snapshot_from_tool_set(tool_set, workspace=workspace)
    tool_ids = {e.identifier for e in snap.tools}
    assert {"read", "write", "edit"}.issubset(tool_ids)
    assert len(snap.skills) >= 1
