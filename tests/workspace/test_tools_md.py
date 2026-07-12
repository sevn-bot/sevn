"""Workspace TOOLS.md registry sync (`sevn.workspace.tools_md`)."""

from __future__ import annotations

from pathlib import Path

from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.triage_context import registry_snapshot_from_tool_set
from sevn.onboarding.seed import seed_narrative_templates
from sevn.tools.registry import build_session_registry
from sevn.workspace.layout import WorkspaceLayout
from sevn.workspace.tools_md import (
    REGISTRY_BEGIN_MARKER,
    read_tools_md_body,
    render_registry_markdown,
    sync_tools_md,
    sync_tools_md_for_config,
)


def test_render_registry_markdown_lists_native_tools() -> None:
    _exe, tool_set = build_session_registry(
        workspace_config=WorkspaceConfig(
            schema_version=1,
            workspace_root=".",
            gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
        ),
    )
    body = render_registry_markdown(tool_set)
    assert "### Native tools" in body
    assert "**read**" in body
    assert "**load_tool**" in body
    assert "Readiness tags" in body
    assert "(`needs_key`)" in body or "needs_key" in body


def test_sync_tools_md_writes_and_updates(tmp_path: Path) -> None:
    _exe, tool_set = build_session_registry(
        workspace_config=WorkspaceConfig(
            schema_version=1,
            workspace_root=".",
            gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
        ),
    )
    assert sync_tools_md(tmp_path, tool_set) is True
    text = (tmp_path / "TOOLS.md").read_text(encoding="utf-8")
    assert REGISTRY_BEGIN_MARKER in text
    assert "**read**" in text
    assert sync_tools_md(tmp_path, tool_set) is False


def test_registry_snapshot_loads_tools_md_body(tmp_path: Path) -> None:
    _exe, tool_set = build_session_registry(
        workspace_config=WorkspaceConfig(
            schema_version=1,
            workspace_root=".",
            gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
        ),
    )
    sync_tools_md(tmp_path, tool_set)
    snap = registry_snapshot_from_tool_set(
        tool_set,
        workspace=WorkspaceConfig(
            schema_version=1,
            workspace_root=".",
            gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
        ),
        content_root=tmp_path,
    )
    assert snap.tools_md_body is not None
    assert "**read**" in snap.tools_md_body


def test_seed_narrative_templates_populates_tools_md(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    merged = {
        "schema_version": 1,
        "workspace_root": ".",
        "agent": {"display_name": "Nova"},
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    seed_narrative_templates(sevn_json, merged)
    layout = WorkspaceLayout.from_config(sevn_json, WorkspaceConfig.model_validate(merged))
    body = read_tools_md_body(layout.content_root)
    assert body is not None
    assert REGISTRY_BEGIN_MARKER in body
    assert "**read**" in body


def test_sync_tools_md_for_config(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, cfg)
    assert sync_tools_md_for_config(sevn_json, cfg, layout=layout) is True
    assert "**read**" in (layout.content_root / "TOOLS.md").read_text(encoding="utf-8")
