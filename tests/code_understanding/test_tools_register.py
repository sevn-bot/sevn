"""Tests for ``register_code_understanding_tools`` (`specs/28-code-understanding.md` §2.2)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sevn.config.workspace_config import parse_workspace_config
from sevn.tools.base import ToolCall
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import build_session_registry


def _ctx(tmp: Path) -> ToolContext:
    return ToolContext(
        session_id="s",
        workspace_path=tmp,
        workspace_id="w",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
        turn_id="t",
    )


def test_cgr_tools_not_registered_without_legacy_flag(tmp_path: Path) -> None:
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "code_understanding": {
                "code_graph_rag": {"enabled": True},
                "roam_code": {"enabled": False},
            },
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    exe, _ts = build_session_registry(workspace_config=cfg)
    names = {d.name for d in exe.definitions()}
    assert "code_graph_rag_read_export" not in names
    assert "code_graph_rag_cli" not in names
    assert "roam_code" not in names


def test_cgr_tools_register_when_legacy_flag_enabled(tmp_path: Path) -> None:
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "code_understanding": {
                "code_graph_rag": {"enabled": True},
                "roam_code": {"enabled": False},
            },
            "tools": {"legacy_native": {"code_graph_rag": {"enabled": True}}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    exe, _ts = build_session_registry(workspace_config=cfg)
    names = {d.name for d in exe.definitions()}
    assert "code_graph_rag_read_export" in names
    assert "code_graph_rag_cli" in names
    assert "roam_code" not in names


def test_roam_tool_not_registered_without_legacy_flag(tmp_path: Path) -> None:
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "code_understanding": {
                "code_graph_rag": {"enabled": False},
                "roam_code": {"enabled": True},
            },
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    exe, _ts = build_session_registry(workspace_config=cfg)
    names = {d.name for d in exe.definitions()}
    assert "roam_code" not in names
    assert "code_graph_rag_read_export" not in names


def test_roam_tool_registers_when_legacy_flag_enabled(tmp_path: Path) -> None:
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "code_understanding": {
                "code_graph_rag": {"enabled": False},
                "roam_code": {"enabled": True},
            },
            "tools": {"legacy_native": {"roam_code": {"enabled": True}}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    exe, _ts = build_session_registry(workspace_config=cfg)
    names = {d.name for d in exe.definitions()}
    assert "roam_code" in names


@pytest.mark.asyncio
async def test_cgr_read_export_error_names_layer(tmp_path: Path) -> None:
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "code_understanding": {"code_graph_rag": {"enabled": True}},
            "tools": {"legacy_native": {"code_graph_rag": {"enabled": True}}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    exe, _ts = build_session_registry(workspace_config=cfg)
    raw = await exe.dispatch(
        _ctx(tmp_path),
        ToolCall(name="code_graph_rag_read_export", arguments={}),
        timeout_seconds="default",
    )
    blob = json.loads(raw)
    assert blob["ok"] is False
    assert "code_graph_rag" in blob["error"]


@pytest.mark.asyncio
async def test_cgr_read_export_reads_repo_index_cache_when_available(tmp_path: Path) -> None:
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "code_understanding": {"code_graph_rag": {"enabled": True}},
            "tools": {"legacy_native": {"code_graph_rag": {"enabled": True}}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    exe, _ts = build_session_registry(workspace_config=cfg)
    export_dir = tmp_path / ".index" / "code_graph_rag"
    export_dir.mkdir(parents=True)
    (export_dir / "export.json").write_text('{"nodes":[{"id":"n1"}]}', encoding="utf-8")
    ctx = _ctx(tmp_path)
    raw = await exe.dispatch(
        ctx,
        ToolCall(name="code_graph_rag_read_export", arguments={}),
        timeout_seconds="default",
    )
    blob = json.loads(raw)
    assert blob["ok"] is True
    data = blob.get("data", {})
    assert isinstance(data, dict)
    assert "nodes" in str(data.get("preview", ""))


@pytest.mark.asyncio
async def test_roam_code_success_contains_layer_prefix(tmp_path: Path) -> None:
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "code_understanding": {"roam_code": {"enabled": True}},
            "tools": {"legacy_native": {"roam_code": {"enabled": True}}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )

    exe, _ts = build_session_registry(workspace_config=cfg)
    with patch(
        "sevn.code_understanding.tools_register.run_roam_query_async",
        new=AsyncMock(return_value=(True, "roam_code: layer answer")),
    ):
        raw = await exe.dispatch(
            _ctx(tmp_path),
            ToolCall(name="roam_code", arguments={"query": "x"}),
            timeout_seconds="default",
        )
    blob = json.loads(raw)
    assert blob["ok"] is True
    assert "roam_code:" in str(blob.get("data", {}).get("text", ""))
