from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from sevn.agent.adapters.dspy_adapter import lambda_rlm_filter, to_dspy_tools
from sevn.agent.adapters.pydantic_adapter import register_pydantic_tools
from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
from sevn.agent.triager.tool_index import build_tool_index_lines
from sevn.config.loader import load_workspace
from sevn.tools.base import (
    FunctionTool,
    ToolCall,
    ToolDefinition,
    ToolExecutor,
    enveloped_success,
)
from sevn.tools.cache import LoadedBodyCache
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.decorator import sevn_tool, tool_from_decorated
from sevn.tools.integration_classifier import is_integration_mutator
from sevn.tools.integration_gh_repo import legacy_gh_repo_integration_kwargs
from sevn.tools.paths import ensure_path_not_under_llmignore
from sevn.tools.permissions import AllowAllPermissionPolicy, DenyingPermissionPolicy
from sevn.tools.registry import (
    build_session_registry,
    merge_skill_manifests,
    plugin_entrypoint_allowed,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    return workspace_dir


@pytest.fixture
def exec_ctx(workspace: Path) -> ToolContext:
    return ToolContext(
        session_id="sess",
        workspace_path=workspace,
        workspace_id="wid",
        registry_version=42,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )


@pytest.mark.asyncio
async def test_second_brain_tools_registered_when_enabled(workspace: Path) -> None:
    (workspace / "sevn.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "second_brain": {"enabled": True},
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )
    cfg, _lay = load_workspace(sevn_json=workspace / "sevn.json")
    executor, _tool_set = build_session_registry(workspace_config=cfg)
    names = {d.name for d in executor.definitions()}
    assert "wiki_search" in names
    assert "second_brain_query" in names
    assert "second_brain_ingest_stub" not in names


@pytest.mark.asyncio
async def test_second_brain_ingest_stub_legacy_flag(workspace: Path) -> None:
    (workspace / "sevn.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "second_brain": {"enabled": True},
                "tools": {"legacy_native": {"second_brain_ingest_stub": {"enabled": True}}},
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )
    cfg, _lay = load_workspace(sevn_json=workspace / "sevn.json")
    executor, _tool_set = build_session_registry(workspace_config=cfg)
    names = {d.name for d in executor.definitions()}
    assert "second_brain_ingest_stub" in names


@pytest.mark.asyncio
async def test_abortable_tools_timeout(workspace: Path) -> None:
    executor = ToolExecutor(default_timeout_seconds=0.05)

    async def slow(_ctx: ToolContext) -> str:
        await asyncio.sleep(1.0)
        return json.dumps({"ok": True, "data": {}, "message": None})

    definition = ToolDefinition(
        name="slow",
        category="meta",
        description="slow",
        parameters={"type": "object", "properties": {}},
        abortable=True,
    )
    executor.register(FunctionTool(definition, slow))
    ctx = ToolContext(
        session_id="s",
        workspace_path=workspace,
        workspace_id="w",
        registry_version=12,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )
    envelope = json.loads(await executor.dispatch(ctx, ToolCall(name="slow", arguments={})))

    assert envelope["ok"] is False
    assert envelope["code"] == ToolResultCode.TOOL_TIMEOUT


@pytest.mark.asyncio
async def test_permissions_none_allows_dispatcher(workspace: Path) -> None:
    executor, _tool_set = build_session_registry()
    ctx = ToolContext(
        session_id="sess",
        workspace_path=workspace,
        workspace_id="wid",
        registry_version=9,
        trace=None,
        permissions=None,
    )
    envelope = json.loads(
        await executor.dispatch(ctx, ToolCall(name="run_skill_script", arguments={}))
    )
    assert envelope["ok"] is False
    assert envelope["code"] == ToolResultCode.VALIDATION_ERROR


@pytest.mark.asyncio
async def test_load_tool_returns_capabilities(exec_ctx: ToolContext) -> None:
    executor, _tool_set = build_session_registry(registry_version=exec_ctx.registry_version)

    envelope = json.loads(
        await executor.dispatch(
            exec_ctx,
            ToolCall(name="load_tool", arguments={"name": "run_skill_script"}),
            timeout_seconds=5.0,
        ),
    )
    assert envelope["ok"] is True
    capabilities = envelope["data"]["capabilities"]
    assert isinstance(capabilities, list)
    assert len(capabilities) > 0
    assert capabilities[0]["id"]


@pytest.mark.asyncio
async def test_load_tool_includes_long_description_from_workspace(
    exec_ctx: ToolContext, workspace: Path
) -> None:
    """``load_tool`` resolves ``long_description_file`` against the workspace overlay first."""
    tools_dir = workspace / "tools"
    tools_dir.mkdir()
    overlay_body = "OPERATOR OVERLAY for log_query"
    _ = (tools_dir / "log_query.md").write_text(overlay_body, encoding="utf-8")

    executor, _tool_set = build_session_registry(registry_version=exec_ctx.registry_version)
    envelope = json.loads(
        await executor.dispatch(
            exec_ctx,
            ToolCall(name="load_tool", arguments={"name": "log_query"}),
            timeout_seconds=5.0,
        ),
    )
    assert envelope["ok"] is True
    assert envelope["data"]["long_description"] == overlay_body
    assert envelope["data"]["schema"]["long_description_file"] == "tools/log_query.md"


@pytest.mark.asyncio
async def test_load_tool_falls_back_to_packaged_template(
    exec_ctx: ToolContext, workspace: Path
) -> None:
    """When no workspace overlay exists, the packaged template is used.

    The packaged ``log_query`` long description is large enough to trip the
    ``maybe_spill_large_payload`` threshold; assert that the spilled file (or the
    inline envelope) carries the expected text.
    """
    executor, _tool_set = build_session_registry(registry_version=exec_ctx.registry_version)
    envelope = json.loads(
        await executor.dispatch(
            exec_ctx,
            ToolCall(name="load_tool", arguments={"name": "log_query"}),
            timeout_seconds=5.0,
        ),
    )
    assert envelope["ok"] is True
    data = envelope["data"]
    spill_ref = data.get("spill_path") or data.get("path")
    if spill_ref and "size" in data:
        spilled = json.loads((workspace / spill_ref).read_text(encoding="utf-8"))
        long_description = spilled.get("long_description")
    else:
        long_description = data.get("long_description")
    assert long_description is not None
    assert "log_query" in long_description.lower()


@pytest.mark.asyncio
async def test_load_tool_omits_long_description_when_field_unset(
    exec_ctx: ToolContext,
) -> None:
    """Tools without ``long_description_file`` do not get a ``long_description`` key."""
    executor, _tool_set = build_session_registry(registry_version=exec_ctx.registry_version)
    envelope = json.loads(
        await executor.dispatch(
            exec_ctx,
            ToolCall(name="load_tool", arguments={"name": "run_skill_script"}),
            timeout_seconds=5.0,
        ),
    )
    assert envelope["ok"] is True
    assert "long_description" not in envelope["data"]


@pytest.mark.asyncio
async def test_load_tool_rejects_disabled_tool(exec_ctx: ToolContext) -> None:
    executor, _tool_set = build_session_registry(registry_version=exec_ctx.registry_version)

    envelope = json.loads(
        await executor.dispatch(
            exec_ctx,
            ToolCall(name="load_tool", arguments={"name": "integration_call"}),
            timeout_seconds=5.0,
        ),
    )

    assert envelope["ok"] is False
    assert envelope["code"] == ToolResultCode.UNKNOWN_TOOL


@pytest.mark.asyncio
async def test_disabled_tool_dispatch_explicit_code(exec_ctx: ToolContext) -> None:
    executor, _tool_set = build_session_registry(registry_version=exec_ctx.registry_version)

    envelope = json.loads(
        await executor.dispatch(
            exec_ctx,
            ToolCall(
                name="integration_call", arguments={"service": "x", "method": "y", "args": {}}
            ),
        ),
    )

    assert envelope["ok"] is False
    assert envelope["code"] == ToolResultCode.DISABLED_TOOL


@pytest.mark.asyncio
async def test_mcp_stub_returns_placeholder(workspace: Path) -> None:
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
        workspace_path=workspace,
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
async def test_load_tool_mcp_capabilities_reference_tools_list_name(workspace: Path) -> None:
    descriptor = ToolDefinition(
        name="router.cursor.search",
        category="mcp",
        description="MCP search tool",
        parameters={"type": "object", "properties": {}},
        enabled=True,
    )
    executor, tool_set = build_session_registry(
        registry_version=3,
        extra_mcp=(descriptor,),
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
            ToolCall(name="load_tool", arguments={"name": descriptor.name}),
        ),
    )
    assert envelope["ok"] is True
    cap0 = envelope["data"]["capabilities"][0]
    assert cap0["id"] == "router.cursor.search"
    assert "MCP tools/list" in cap0["parameters_overview"]


def test_legacy_gh_repo_maps_to_integration_call() -> None:
    got = legacy_gh_repo_integration_kwargs("gh_repo_get", args={"owner": "a", "repo": "b"})
    assert got is not None
    assert got["service"] == "github"
    assert got["method"] == "repos.get"
    assert got["args"] == {"owner": "a", "repo": "b"}


@pytest.mark.asyncio
async def test_bundled_canvas_skill_in_merged_manifests() -> None:
    merged = merge_skill_manifests(None)
    assert "canvas" in merged
    assert "bundled" in merged["canvas"].lower()


@pytest.mark.asyncio
async def test_permission_denied_short_circuits(workspace: Path) -> None:
    executor, _tool_set = build_session_registry()
    ctx = ToolContext(
        session_id="sess",
        workspace_path=workspace,
        workspace_id="wid",
        registry_version=1,
        trace=None,
        permissions=DenyingPermissionPolicy(),
    )

    envelope = json.loads(
        await executor.dispatch(ctx, ToolCall(name="run_skill_script", arguments={}))
    )

    assert envelope["ok"] is False
    assert envelope["code"] == ToolResultCode.PERMISSION_DENIED


@pytest.mark.asyncio
async def test_dspytools_aliases_match_executor(workspace: Path) -> None:
    executor, _tool_set = build_session_registry()
    ctx = ToolContext(
        session_id="sess",
        workspace_path=workspace,
        workspace_id="wid",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )
    shimmed = to_dspy_tools(executor, ctx, include_disabled=True)
    executor_names = {definition.name for definition in executor.definitions()}
    filtered = lambda_rlm_filter(shimmed, allowlist=frozenset(list(executor_names)[:5]))
    assert set(filtered) <= executor_names


def test_pydantic_surfaces_exclude_schema_literals() -> None:
    _executor, tool_set = build_session_registry()
    triager = TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="ok",
        tools=("run_skill_script",),
        skills=("pdf",),
        mcp_servers_required=[],
        confidence=0.75,
        requires_vision=False,
        requires_document=False,
    )
    registration = register_pydantic_tools(tool_set, triager)

    flattened = json.dumps(registration.tool_descriptions)
    assert '"type"' not in flattened.lower()
    skill_blob = json.dumps(registration.skill_descriptions)
    assert "SKILL.md" not in skill_blob
    assert "$schema" not in flattened + skill_blob
    assert '"properties"' not in flattened + skill_blob


@pytest.mark.asyncio
async def test_decorated_registration_roundtrip(exec_ctx: ToolContext) -> None:
    @sevn_tool(
        name="fancy",
        category="meta",
        description="fancy",
        parameters={
            "type": "object",
            "properties": {"phrase": {"type": "string"}},
            "required": ["phrase"],
        },
    )
    async def fancy(ctx: ToolContext, *, phrase: str) -> str:
        _ = ctx

        return enveloped_success({"phrase": phrase})

    executor = ToolExecutor(default_timeout_seconds=2.0)
    executor.register(tool_from_decorated(fancy))

    payload = json.loads(
        await executor.dispatch(exec_ctx, ToolCall(name="fancy", arguments={"phrase": "hi"})),
    )
    assert payload["data"]["phrase"] == "hi"


def test_integration_mutator_classifier() -> None:
    assert is_integration_mutator("slack", "chat.post_message") is True
    assert is_integration_mutator("slack", "auth.test") is False


def test_loaded_body_cache_lru() -> None:

    cache = LoadedBodyCache(capacity=2)
    registry_version = 9
    cache.set("tool", "a", registry_version, "one")

    cache.set("tool", "b", registry_version, "two")
    cache.set("tool", "c", registry_version, "three")
    assert cache.get("tool", "a", registry_version) is None
    cache.get("tool", "b", registry_version)


def test_llmignore_rejects_blocked_paths(workspace: Path) -> None:
    bad = workspace / ".llmignore" / "blocked" / "x.txt"
    bad.parent.mkdir(parents=True)

    with pytest.raises(PermissionError):
        ensure_path_not_under_llmignore(bad, workspace)


def test_tool_index_blocks_present() -> None:
    _executor, tool_set = build_session_registry()
    lines = build_tool_index_lines(tool_set)
    assert any(line.startswith("::TOOLS") for line in lines)
    assert "::SKILLS" in "\n".join(lines)


def test_build_session_registry_workspace_includes_bundled_core_skill(
    tmp_path: Path,
) -> None:
    """Workspace-aware factory indexes bundled ``canvas`` / ``second_brain`` skills."""
    from sevn.config.workspace_config import parse_workspace_config
    from sevn.skills.manager import SkillsManager
    from sevn.workspace.layout import WorkspaceLayout

    SkillsManager.reset_singletons_for_tests()
    root = tmp_path / "ws"
    root.mkdir()
    (root / "skills").mkdir()
    ws = parse_workspace_config(
        {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
    )
    layout = WorkspaceLayout(root / "sevn.json", root)
    _executor, tool_set = build_session_registry(
        workspace_root=root,
        layout=layout,
        workspace_config=ws,
    )
    assert {"canvas", "second_brain"} & set(tool_set.skill_descriptions)
    assert tool_set.registry_version >= 1


def test_plugin_toggle_helper() -> None:
    assert plugin_entrypoint_allowed("magic.tool", {})
    assert plugin_entrypoint_allowed("magic.tool", {"magic": True}) is True
    assert plugin_entrypoint_allowed("magic.tool", {"magic": False}) is False
