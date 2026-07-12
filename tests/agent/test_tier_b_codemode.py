"""W8 — tier-B CodeMode triager-scoped + trust boundary."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import SkipToolExecution
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RunUsage
from pydantic_monty import MontyRepl, MontyRuntimeError

from sevn.agent.adapters.pydantic_adapter import PydanticToolRegistration
from sevn.agent.adapters.tier_b_codemode import (
    CODEMODE_NATIVE_TOOL_NAMES,
    build_codemode_capability,
    is_codemode_eligible_tool,
)
from sevn.agent.adapters.tier_b_hooks import (
    TierBHookConfig,
    build_tier_b_hooks,
    permission_before_tool_execute,
)
from sevn.agent.adapters.tier_b_tools import _make_registry_tool
from sevn.agent.adapters.tier_b_toolset import SevnRegistryToolset
from sevn.agent.executors.b_harness import build_tier_b_capabilities
from sevn.agent.executors.b_types import BTierDeps
from sevn.config.model_resolution import codemode_enabled
from sevn.config.workspace_config import WorkspaceConfig
from sevn.tools.base import FunctionTool, ToolDefinition, ToolExecutor, enveloped_success
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy


def _ctx() -> ToolContext:
    return ToolContext(
        session_id="s",
        workspace_path=Path("/tmp"),
        workspace_id="w",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )


def _deps(*, loaded: set[str] | None = None, executor: ToolExecutor | None = None) -> BTierDeps:
    return BTierDeps(
        tool_executor=executor or ToolExecutor(),
        tool_context_template=_ctx(),
        workspace_path=Path("/tmp"),
        registry_version=1,
        loaded_tools=loaded or set(),
    )


def _hook_config(**overrides: object) -> TierBHookConfig:
    base = {
        "provider_round_counter": [0],
        "max_rounds": 2,
        "count_planning": False,
        "bound_tool_names": frozenset({"glob", "read"}),
        "triager_first_reply": "",
    }
    base.update(overrides)
    return TierBHookConfig(**base)  # type: ignore[arg-type]


def _register_file_tools(exe: ToolExecutor) -> None:
    async def _glob_body(ctx: ToolContext, glob_pattern: str = "**/*") -> str:
        return enveloped_success({"paths": ["notes.md"]})

    async def _read_body(ctx: ToolContext, path: str = "") -> str:
        return enveloped_success({"text": "# Notes\n"})

    exe.register(
        FunctionTool(
            ToolDefinition(
                name="glob",
                category="file",
                description="glob",
                parameters={
                    "type": "object",
                    "properties": {"glob_pattern": {"type": "string"}},
                },
            ),
            _glob_body,
        )
    )
    exe.register(
        FunctionTool(
            ToolDefinition(
                name="read",
                category="file",
                description="read",
                parameters={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            ),
            _read_body,
        )
    )


def test_codemode_enabled_defaults_false() -> None:
    assert (
        codemode_enabled(
            WorkspaceConfig(
                schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
            )
        )
        is False
    )


def test_codemode_enabled_reads_agent_flag() -> None:
    cfg = WorkspaceConfig(
        schema_version=1,
        agent={"codemode": {"enabled": True}},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    assert codemode_enabled(cfg) is True


def test_codemode_enabled_defaults_true_for_minimax() -> None:
    cfg = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    assert codemode_enabled(cfg, model_id="minimax/m3") is True
    assert codemode_enabled(cfg, model_id="minimax/MiniMax-M1-80k") is True


def test_codemode_enabled_explicit_false_overrides_minimax_default() -> None:
    cfg = WorkspaceConfig(
        schema_version=1,
        agent={"codemode": {"enabled": False}},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    assert codemode_enabled(cfg, model_id="minimax/m3") is False


def test_codemode_enabled_non_minimax_model_unchanged() -> None:
    cfg = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    assert codemode_enabled(cfg, model_id="anthropic/claude-sonnet-4-20250514") is False
    assert codemode_enabled(cfg, model_id="openai/gpt-4o") is False


def test_is_codemode_eligible_excludes_meta_tools() -> None:
    for name in CODEMODE_NATIVE_TOOL_NAMES:
        assert (
            is_codemode_eligible_tool(
                name,
                triager_tools=frozenset({name, "glob"}),
                triager_skills=frozenset(),
            )
            is False
        )


def test_skill_runner_eligible_only_with_triager_skills() -> None:
    assert (
        is_codemode_eligible_tool(
            "run_skill_script",
            triager_tools=frozenset({"read"}),
            triager_skills=frozenset(),
        )
        is False
    )
    assert (
        is_codemode_eligible_tool(
            "run_skill_script",
            triager_tools=frozenset({"read"}),
            triager_skills=frozenset({"pdf"}),
        )
        is True
    )


def test_build_tier_b_capabilities_codemode_off_by_default() -> None:
    hooks = build_tier_b_hooks(_hook_config())
    caps = build_tier_b_capabilities(hooks=hooks)
    assert all(c.__class__.__name__ != "CodeMode" for c in caps)


def test_build_tier_b_capabilities_codemode_on() -> None:
    hooks = build_tier_b_hooks(_hook_config())
    caps = build_tier_b_capabilities(hooks=hooks, codemode_on=True)
    assert caps[-1].__class__.__name__ == "CodeMode"
    assert build_codemode_capability().__class__.__name__ == "CodeMode"


def test_build_codemode_capability_honors_max_retries_override() -> None:
    cap = build_codemode_capability(max_retries=5)
    assert cap.max_retries == 5


def test_registry_toolset_tags_triager_tools_for_codemode() -> None:
    exe = ToolExecutor()
    _register_file_tools(exe)
    reg = PydanticToolRegistration(
        tool_names=("glob", "read", "load_tool"),
        tool_descriptions={"glob": "g", "read": "r", "load_tool": "l"},
        skill_names=(),
        skill_descriptions={},
    )
    toolset = SevnRegistryToolset.from_registry(
        exe,
        reg,
        codemode_enabled=True,
        triager_tools=frozenset({"glob", "read"}),
        triager_skills=frozenset(),
    )
    tagged = {t.name: (t.metadata or {}) for t in toolset.tools.values()}
    assert tagged["glob"].get("code_mode") is True
    assert tagged["read"].get("code_mode") is True
    assert tagged.get("load_tool", {}).get("code_mode") is not True


def test_monty_rejects_import_httpx() -> None:
    repl = MontyRepl()
    with pytest.raises(MontyRuntimeError, match="httpx"):
        repl.feed_start("import httpx")


@pytest.mark.asyncio
async def test_codemode_web_composite_run_code_single_round_trip() -> None:
    from sevn.agent.adapters.pydantic_adapter import PydanticToolRegistration
    from sevn.agent.adapters.tier_b_capabilities import WebEgressDomainPolicy
    from sevn.agent.adapters.tier_b_toolset import SevnRegistryToolset

    exe = ToolExecutor()
    invoked: list[str] = []

    async def _gpc(ctx: ToolContext, *, url: str, max_length: int | None = None) -> str:
        _ = ctx, max_length
        invoked.append(f"gpc:{url}")
        return enveloped_success({"url": url, "markdown": "headline"})

    async def _serp(
        ctx: ToolContext, *, query: str, count: int = 5, region: str | None = None
    ) -> str:
        _ = ctx, count, region
        invoked.append(f"serp:{query}")
        return enveloped_success({"query": query, "count": 1, "results": []})

    for name, body in (("get_page_content", _gpc), ("serp", _serp)):
        exe.register(
            FunctionTool(
                ToolDefinition(
                    name=name,
                    category="web",
                    description=name,
                    parameters={
                        "type": "object",
                        "properties": {
                            "url" if name == "get_page_content" else "query": {"type": "string"},
                        },
                        "required": ["url" if name == "get_page_content" else "query"],
                    },
                ),
                body,
            )
        )

    reg = PydanticToolRegistration(
        tool_names=("get_page_content", "serp"),
        tool_descriptions={"get_page_content": "g", "serp": "s"},
        skill_names=(),
        skill_descriptions={},
    )
    toolset = SevnRegistryToolset.from_registry(
        exe,
        reg,
        codemode_enabled=True,
        triager_tools=frozenset({"get_page_content", "serp"}),
        triager_skills=frozenset(),
        codemode_web_policy=WebEgressDomainPolicy(),
    )
    hooks = build_tier_b_hooks(
        _hook_config(bound_tool_names=frozenset({"get_page_content", "serp", "run_code"})),
    )
    deps = _deps(loaded={"get_page_content", "serp", "run_code"}, executor=exe)
    composite_code = (
        'await get_page_content(url="https://www.dutchnews.nl")\n'
        'await serp(query="Netherlands news today")'
    )

    async def model_fn(messages: list[object], info: MagicMock) -> ModelResponse:
        for msg in messages:
            for part in getattr(msg, "parts", ()):
                if getattr(part, "part_kind", "") == "tool-return":
                    return ModelResponse(parts=[TextPart(content="done")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="run_code",
                    args={"code": composite_code},
                    tool_call_id="rc1",
                ),
            ],
        )

    agent = Agent(
        FunctionModel(model_fn),
        toolsets=[toolset],
        deps_type=BTierDeps,
        capabilities=build_tier_b_capabilities(hooks=hooks, codemode_on=True),
    )
    result = await agent.run("composite web", deps=deps)
    assert invoked == [
        "gpc:https://www.dutchnews.nl",
        "serp:Netherlands news today",
    ]
    run_code_calls = [
        part
        for msg in result.all_messages()
        for part in msg.parts
        if getattr(part, "part_kind", "") == "tool-call" and part.tool_name == "run_code"
    ]
    assert len(run_code_calls) == 1


@pytest.mark.asyncio
async def test_codemode_composite_run_code_single_round_trip() -> None:
    exe = ToolExecutor()
    invoked: list[str] = []

    async def _glob_body(ctx: ToolContext, glob_pattern: str = "**/*") -> str:
        invoked.append("glob")
        return enveloped_success({"paths": ["notes.md"]})

    async def _read_body(ctx: ToolContext, path: str = "") -> str:
        invoked.append("read")
        return enveloped_success({"text": "# Notes\n"})

    exe.register(
        FunctionTool(
            ToolDefinition(
                name="glob",
                category="file",
                description="glob",
                parameters={
                    "type": "object",
                    "properties": {"glob_pattern": {"type": "string"}},
                },
            ),
            _glob_body,
        )
    )
    exe.register(
        FunctionTool(
            ToolDefinition(
                name="read",
                category="file",
                description="read",
                parameters={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            ),
            _read_body,
        )
    )
    reg = PydanticToolRegistration(
        tool_names=("glob", "read"),
        tool_descriptions={"glob": "g", "read": "r"},
        skill_names=(),
        skill_descriptions={},
    )
    toolset = SevnRegistryToolset.from_registry(
        exe,
        reg,
        codemode_enabled=True,
        triager_tools=frozenset({"glob", "read"}),
        triager_skills=frozenset(),
    )
    hooks = build_tier_b_hooks(_hook_config(bound_tool_names=frozenset({"glob", "read"})))
    deps = _deps(loaded={"glob", "read", "run_code"}, executor=exe)

    composite_code = 'await glob(glob_pattern="*.md")\nawait read(path="notes.md")'

    async def model_fn(messages: list[object], info: MagicMock) -> ModelResponse:
        for msg in messages:
            for part in getattr(msg, "parts", ()):
                if getattr(part, "part_kind", "") == "tool-return":
                    return ModelResponse(parts=[TextPart(content="done")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="run_code",
                    args={"code": composite_code},
                    tool_call_id="rc1",
                ),
            ],
        )

    agent = Agent(
        FunctionModel(model_fn),
        toolsets=[toolset],
        deps_type=BTierDeps,
        capabilities=build_tier_b_capabilities(hooks=hooks, codemode_on=True),
    )
    result = await agent.run("composite", deps=deps)
    assert invoked == ["glob", "read"]
    run_code_calls = [
        part
        for msg in result.all_messages()
        for part in msg.parts
        if getattr(part, "part_kind", "") == "tool-call" and part.tool_name == "run_code"
    ]
    assert len(run_code_calls) == 1


@pytest.mark.asyncio
async def test_codemode_log_query_dispatches() -> None:
    assert is_codemode_eligible_tool(
        "log_query",
        triager_tools=frozenset({"log_query"}),
        triager_skills=frozenset(),
    )
    exe = ToolExecutor()
    invoked: list[str] = []

    async def _log_query_body(
        ctx: ToolContext,
        pattern: str | None = None,
        file: str = "gateway.log",
    ) -> str:
        _ = ctx, file
        invoked.append("log_query")
        return enveloped_success(
            {"lines": ["ERROR boot failed"]},
            message="matched boot pattern",
        )

    exe.register(
        FunctionTool(
            ToolDefinition(
                name="log_query",
                category="log",
                description="log query",
                parameters={
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "file": {"type": "string", "default": "gateway.log"},
                    },
                },
            ),
            _log_query_body,
        )
    )
    reg = PydanticToolRegistration(
        tool_names=("log_query",),
        tool_descriptions={"log_query": "audit logs"},
        skill_names=(),
        skill_descriptions={},
    )
    toolset = SevnRegistryToolset.from_registry(
        exe,
        reg,
        codemode_enabled=True,
        triager_tools=frozenset({"log_query"}),
        triager_skills=frozenset(),
    )
    hooks = build_tier_b_hooks(_hook_config(bound_tool_names=frozenset({"log_query"})))
    deps = _deps(loaded={"log_query", "run_code"}, executor=exe)

    composite_code = 'result = await log_query(pattern="boot")\nprint(result)'

    async def model_fn(messages: list[object], info: MagicMock) -> ModelResponse:
        for msg in messages:
            for part in getattr(msg, "parts", ()):
                if getattr(part, "part_kind", "") == "tool-return":
                    return ModelResponse(parts=[TextPart(content="done")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="run_code",
                    args={"code": composite_code},
                    tool_call_id="rc1",
                ),
            ],
        )

    agent = Agent(
        FunctionModel(model_fn),
        toolsets=[toolset],
        deps_type=BTierDeps,
        capabilities=build_tier_b_capabilities(hooks=hooks, codemode_on=True),
    )
    result = await agent.run("log query composite", deps=deps)
    assert "log_query" in invoked
    transcript = str(result.all_messages())
    assert "ERROR boot failed" in transcript
    run_code_calls = [
        part
        for msg in result.all_messages()
        for part in msg.parts
        if getattr(part, "part_kind", "") == "tool-call" and part.tool_name == "run_code"
    ]
    assert len(run_code_calls) == 1
    assert "2013" not in transcript
    assert "tool call and result not match" not in transcript
    assert "retry-prompt" not in transcript


@pytest.mark.asyncio
async def test_codemode_sandbox_denied_tool_hits_permission_hook() -> None:
    exe = ToolExecutor()

    async def _ping_body(ctx: ToolContext) -> str:
        return enveloped_success({"pong": True})

    exe.register(
        FunctionTool(
            ToolDefinition(
                name="ping_tool",
                category="test",
                description="ping",
                parameters={"type": "object", "properties": {}},
            ),
            _ping_body,
        )
    )
    reg = PydanticToolRegistration(
        tool_names=("ping_tool",),
        tool_descriptions={"ping_tool": "ping"},
        skill_names=(),
        skill_descriptions={},
    )
    toolset = SevnRegistryToolset.from_registry(
        exe,
        reg,
        codemode_enabled=True,
        triager_tools=frozenset({"ping_tool"}),
        triager_skills=frozenset(),
    )
    hooks = build_tier_b_hooks(_hook_config(bound_tool_names=frozenset({"ping_tool"})))
    deps = _deps(loaded={"run_code"}, executor=exe)

    async def model_fn(messages: list[object], info: MagicMock) -> ModelResponse:
        for msg in messages:
            for part in getattr(msg, "parts", ()):
                if getattr(part, "part_kind", "") in {"tool-return", "retry-prompt"}:
                    return ModelResponse(parts=[TextPart(content="stop")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="run_code",
                    args={"code": "await ping_tool()"},
                    tool_call_id="rc2",
                ),
            ],
        )

    agent = Agent(
        FunctionModel(model_fn),
        toolsets=[toolset],
        deps_type=BTierDeps,
        capabilities=build_tier_b_capabilities(hooks=hooks, codemode_on=True),
    )
    result = await agent.run("deny", deps=deps)
    transcript = str(result.all_messages())
    assert "TOOL_NOT_PROVISIONED" in transcript or "not provisioned" in transcript.lower()


@pytest.mark.asyncio
async def test_permission_hook_skip_inside_codemode_path() -> None:
    from pydantic_ai.capabilities import ValidatedToolArgs
    from pydantic_ai.tools import ToolDefinition as PAToolDefinition

    ctx = RunContext(deps=_deps(), model=MagicMock(), usage=RunUsage())
    call = ToolCallPart(tool_name="serp", args={"query": "x"}, tool_call_id="tc1")
    tool_def = PAToolDefinition(
        name="serp",
        parameters_json_schema={"type": "object", "properties": {}},
        description="search",
    )
    with pytest.raises(SkipToolExecution) as exc:
        await permission_before_tool_execute(
            ctx,
            call=call,
            tool_def=tool_def,
            args=ValidatedToolArgs({}),
        )
    blob = json.loads(exc.value.result)
    assert blob["code"] == ToolResultCode.TOOL_NOT_PROVISIONED


def test_codemode_playbook_covers_log_query_and_get_page_content() -> None:
    from sevn.prompts.tier_b import tier_b_codemode_playbook_prompt

    body = tier_b_codemode_playbook_prompt()
    assert "await log_query" in body
    assert "await get_page_content" in body
    assert "run_code" in body
    assert "asyncio.gather" in body
    assert "search_in_file" in body
    assert "list_dir" in body


def test_delete_tool_not_tagged_codemode() -> None:
    defn = ToolDefinition(
        name="delete",
        category="file",
        description="delete",
        parameters={"type": "object", "properties": {}},
        requires_human=True,
    )
    tool = _make_registry_tool(defn, code_mode=False)
    assert tool.requires_approval is True
    assert (tool.metadata or {}).get("code_mode") is not True
