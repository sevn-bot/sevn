"""Adapter integration slice for the tools registry (`specs/11-tools-registry.md` §10.4)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from sevn.agent.adapters.pydantic_adapter import register_pydantic_tools
from sevn.config.loader import load_workspace
from sevn.config.workspace_config import parse_workspace_config
from sevn.skills.manager import SkillsManager
from sevn.tools.base import ToolCall, ToolDefinition
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy, DenyingPermissionPolicy
from sevn.tools.registry import build_session_registry
from sevn.workspace.layout import WorkspaceLayout

_MIN_ECHO_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "skills" / "min_echo"


def test_register_pydantic_descriptions_exclude_schemas_and_skill_paths() -> None:
    """Tier-B registration must stay descriptions-only (`specs/11-tools-registry.md` §2.6, §10.4)."""

    _executor, tool_set = build_session_registry(registry_version=5)
    triage = {
        "tools": ("load_tool", "run_skill_script"),
        "skills": ("lcm",),
    }
    reg = register_pydantic_tools(tool_set, triage, add_core_tools=True)
    blob = json.dumps(
        {
            "tools": dict(reg.tool_descriptions),
            "skills": dict(reg.skill_descriptions),
        },
    ).lower()
    assert "skill.md" not in blob
    assert "$schema" not in blob
    assert '"properties"' not in blob


def test_register_pydantic_tools_always_includes_file_ops() -> None:
    """Core tier-B registration always exposes read, edit, and write."""
    _executor, tool_set = build_session_registry(registry_version=5)
    triage = {"tools": (), "skills": ()}
    reg = register_pydantic_tools(tool_set, triage, add_core_tools=True)
    assert {"read", "edit", "write"}.issubset(set(reg.tool_names))


@pytest.mark.asyncio
async def test_fake_mcp_descriptor_dispatch_placeholder(tmp_path) -> None:
    """Declared MCP tools return ``MCP_UNAVAILABLE`` until IO ships."""

    descriptor = ToolDefinition(
        name="demo.server.probe",
        category="mcp",
        description="demo",
        parameters={"type": "object", "properties": {}},
        enabled=True,
    )
    executor, tool_set = build_session_registry(
        registry_version=3,
        extra_mcp=(descriptor,),
    )
    ctx = ToolContext(
        session_id="sess",
        workspace_path=tmp_path,
        workspace_id="wid",
        registry_version=tool_set.registry_version,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )
    envelope = json.loads(
        await executor.dispatch(ctx, ToolCall(name=descriptor.name, arguments={}))
    )
    assert envelope["ok"] is False
    assert envelope["code"] == ToolResultCode.MCP_UNAVAILABLE


@pytest.mark.asyncio
async def test_permission_config_denies_before_mcp_dispatch(tmp_path) -> None:
    """``PermissionConfig`` short-circuits dispatch for denied tools."""

    descriptor = ToolDefinition(
        name="demo.server.probe",
        category="mcp",
        description="demo",
        parameters={"type": "object", "properties": {}},
        enabled=True,
    )
    executor, tool_set = build_session_registry(
        registry_version=2,
        extra_mcp=(descriptor,),
    )
    ctx = ToolContext(
        session_id="sess",
        workspace_path=tmp_path,
        workspace_id="wid",
        registry_version=tool_set.registry_version,
        trace=None,
        permissions=DenyingPermissionPolicy(),
    )
    envelope = json.loads(
        await executor.dispatch(ctx, ToolCall(name=descriptor.name, arguments={}))
    )
    assert envelope["ok"] is False
    assert envelope["code"] == ToolResultCode.PERMISSION_DENIED


@pytest.mark.asyncio
async def test_workspace_tools_toggle_merges_into_plugin_loader(tmp_path, monkeypatch) -> None:
    """``sevn.json`` ``tools.<plugin>.enabled`` merges into ``load_plugin_tools`` toggles."""

    from sevn.tools import registry as registry_mod

    captured: dict[str, bool] = {}

    def _capture_load(toggles: dict[str, bool] | None = None) -> list:
        captured.clear()
        captured.update(dict(toggles or {}))
        return []

    monkeypatch.setattr(registry_mod, "load_plugin_tools", _capture_load)
    (tmp_path / "sevn.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tools": {"demo_plugin": {"enabled": False}},
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            },
        ),
        encoding="utf-8",
    )
    cfg, _lay = load_workspace(sevn_json=tmp_path / "sevn.json")
    build_session_registry(workspace_config=cfg)
    assert captured.get("demo_plugin") is False


@pytest.fixture(autouse=True)
def _reset_skills_singleton() -> None:
    SkillsManager.reset_singletons_for_tests()
    yield
    SkillsManager.reset_singletons_for_tests()


@pytest.mark.asyncio
async def test_run_skill_script_live_subprocess_with_workspace_fixture(tmp_path: Path) -> None:
    """``run_skill_script`` returns subprocess JSON when workspace has ``min_echo`` skill."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "skills" / "user").mkdir(parents=True)
    shutil.copytree(_MIN_ECHO_FIXTURE, workspace / "skills" / "user" / "min_echo")
    ws = parse_workspace_config(
        {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
    )
    layout = WorkspaceLayout(sevn_json_path=workspace / "sevn.json", content_root=workspace)
    executor, tool_set = build_session_registry(
        workspace_root=workspace,
        layout=layout,
        workspace_config=ws,
    )
    ctx = ToolContext(
        session_id="sess",
        workspace_path=workspace,
        workspace_id="wid",
        registry_version=tool_set.registry_version,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )
    envelope = json.loads(
        await executor.dispatch(
            ctx,
            ToolCall(
                name="run_skill_script",
                arguments={
                    "skill": "min_echo",
                    "script": "scripts/echo.py",
                    "argv": ["hi"],
                },
            ),
        ),
    )
    assert envelope["ok"] is True
    assert envelope["data"]["echo"] == "hi"
