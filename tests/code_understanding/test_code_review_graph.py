"""Tests for code-review-graph MCP registration (`specs/28-code-understanding.md` §10.7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sevn.code_understanding.code_review_graph_mcp import (
    build_serve_argv,
    code_review_graph_mcp_enabled,
    mcp_stdio_entry,
    merge_code_review_graph_mcp_server,
    read_only_tool_names,
    resolve_repo_root,
    validate_repo_root,
)
from sevn.code_understanding.graphify_mcp import build_effective_mcp_servers
from sevn.code_understanding.models import (
    CodeReviewGraphSettings,
    CodeUnderstandingSettings,
)
from sevn.config.defaults import CODE_REVIEW_GRAPH_READ_ONLY_TOOLS
from sevn.config.workspace_config import WorkspaceConfig


def _enabled_workspace() -> WorkspaceConfig:
    return WorkspaceConfig(
        schema_version=1,
        code_understanding=CodeUnderstandingSettings(
            code_review_graph=CodeReviewGraphSettings(
                enabled=True,
                mcp={"enabled": True},
            ),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )


def test_code_review_graph_mcp_disabled_by_default() -> None:
    assert (
        code_review_graph_mcp_enabled(
            WorkspaceConfig(
                schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
            )
        )
        is False
    )


def test_code_review_graph_mcp_requires_explicit_opt_in(tmp_path: Path) -> None:
    ws = WorkspaceConfig(
        schema_version=1,
        code_understanding=CodeUnderstandingSettings(
            code_review_graph=CodeReviewGraphSettings(enabled=True, mcp={"enabled": False}),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    assert code_review_graph_mcp_enabled(ws) is False
    assert mcp_stdio_entry(ws, tmp_path) is None


def test_read_only_tool_list_matches_spec_minimum() -> None:
    names = read_only_tool_names()
    assert names == list(CODE_REVIEW_GRAPH_READ_ONLY_TOOLS)
    assert "apply_refactor_tool" not in names
    assert "get_minimal_context_tool" in names


def test_read_only_preset_builds_serve_argv_with_tools(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    argv = build_serve_argv(CodeReviewGraphSettings(tool_preset="read_only"), repo)
    assert argv[0:3] == ["serve", "--repo", str(repo.resolve())]
    tools_idx = argv.index("--tools")
    tools_csv = argv[tools_idx + 1]
    assert "get_minimal_context_tool" in tools_csv
    assert "apply_refactor_tool" not in tools_csv


def test_full_preset_omits_tools_flag(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    argv = build_serve_argv(CodeReviewGraphSettings(tool_preset="full"), repo)
    assert argv == ["serve", "--repo", str(repo.resolve())]


def test_repo_root_defaults_to_content_root(tmp_path: Path) -> None:
    assert resolve_repo_root(CodeReviewGraphSettings(), tmp_path) == tmp_path.resolve()


def test_validate_repo_root_rejects_outside_workspace(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(ValueError, match=r"code_review_graph: repo_root .* outside workspace"):
        validate_repo_root(outside, ws)


def test_validate_repo_root_rejects_llmignore(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    blocked = ws / ".llmignore" / "blocked" / "secret"
    blocked.parent.mkdir(parents=True)
    blocked.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="code_review_graph: repo_root rejected"):
        validate_repo_root(blocked, ws)


def test_mcp_stdio_entry_when_enabled(tmp_path: Path) -> None:
    ws = _enabled_workspace()
    entry = mcp_stdio_entry(ws, tmp_path)
    assert entry is not None
    assert entry["command"] == "code-review-graph"
    args = entry["args"]
    assert isinstance(args, list)
    assert args[0] == "serve"
    assert "--tools" in args


def test_merge_into_config_doc(tmp_path: Path) -> None:
    ws = _enabled_workspace()
    doc: dict[str, object] = {"mcp_servers": {"linear": {"command": "mcp-linear", "args": []}}}
    merge_code_review_graph_mcp_server(doc, workspace=ws, content_root=tmp_path)
    servers = doc["mcp_servers"]
    assert isinstance(servers, dict)
    assert "code_review_graph" in servers
    assert servers["linear"]["command"] == "mcp-linear"


def test_build_effective_mcp_servers_layers_synthetic(tmp_path: Path) -> None:
    ws = WorkspaceConfig.model_validate(
        {
            "schema_version": 1,
            "mcp_servers": {
                "linear": {"command": "mcp-linear", "args": []},
            },
            "code_understanding": {
                "code_review_graph": {
                    "enabled": True,
                    "mcp": {"enabled": True},
                },
            },
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    merged = build_effective_mcp_servers(ws, tmp_path)
    assert "linear" in merged
    assert "code_review_graph" in merged
