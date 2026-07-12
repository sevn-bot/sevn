"""W7 — provider-adaptive WebSearch/WebFetch + Thinking capabilities."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic_ai import RunContext
from pydantic_ai.capabilities import Thinking, WebSearch
from pydantic_ai.usage import RunUsage

from sevn.agent.adapters.tier_b_capabilities import (
    WebEgressDomainPolicy,
    build_web_thinking_extra_capabilities,
    provider_supports_native_web_fetch,
    provider_supports_native_web_search,
    resolve_thinking_effort,
    resolve_web_egress_domain_policy,
    url_passes_domain_policy,
)
from sevn.agent.adapters.tier_b_model import apply_minimax_anthropic_request_hygiene
from sevn.agent.executors.b_harness import build_tier_b_capabilities
from sevn.agent.executors.b_types import BTierDeps
from sevn.config.workspace_config import WorkspaceConfig
from sevn.tools.base import FunctionTool, ToolDefinition, ToolExecutor, enveloped_success
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.web import register_web_tools


def _ctx() -> ToolContext:
    return ToolContext(
        session_id="s",
        workspace_path=Path("/tmp"),
        workspace_id="w",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )


def _executor_with_web() -> ToolExecutor:
    exe = ToolExecutor()
    register_web_tools(exe)
    return exe


def test_provider_native_web_search_minimax_vs_anthropic() -> None:
    assert provider_supports_native_web_search("minimax/MiniMax-M2", None) is False
    assert provider_supports_native_web_search("anthropic/claude-sonnet-4-20250514", None) is True
    assert provider_supports_native_web_fetch("bedrock/anthropic.claude-3-haiku", None) is False
    assert provider_supports_native_web_fetch("anthropic/claude-sonnet-4-20250514", None) is True


def test_resolve_web_egress_domain_policy_from_agent_web() -> None:
    ws = WorkspaceConfig.model_validate(
        {
            "schema_version": 1,
            "agent": {
                "web": {
                    "allowed_domains": ["python.org"],
                    "blocked_domains": ["evil.com"],
                },
            },
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    policy = resolve_web_egress_domain_policy(ws)
    assert policy.allowed_domains == ("python.org",)
    assert policy.blocked_domains == ("evil.com",)


def test_url_passes_domain_policy() -> None:
    policy = WebEgressDomainPolicy(
        allowed_domains=("python.org",),
        blocked_domains=("evil.com",),
    )
    assert url_passes_domain_policy("https://docs.python.org/3/", policy) is True
    assert url_passes_domain_policy("https://evil.com/x", policy) is False
    assert url_passes_domain_policy("https://example.com/", policy) is False


def test_build_web_thinking_extra_minimax_uses_local_serp() -> None:
    ws = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    extras, thinking = build_web_thinking_extra_capabilities(
        workspace=ws,
        model_id="minimax/MiniMax-M2",
        tool_executor=_executor_with_web(),
        triage_tools=("serp",),
    )
    assert thinking is False
    assert len(extras) == 1
    cap = extras[0]
    assert isinstance(cap, WebSearch)
    assert cap.native is False
    assert cap.local is not False


def test_build_web_thinking_extra_skips_web_capabilities_when_codemode_enabled() -> None:
    ws = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    extras, _ = build_web_thinking_extra_capabilities(
        workspace=ws,
        model_id="anthropic/claude-sonnet-4-20250514",
        tool_executor=_executor_with_web(),
        triage_tools=("serp", "get_page_content"),
        codemode_enabled=True,
    )
    assert extras == []


def test_build_web_thinking_extra_anthropic_uses_native_search() -> None:
    ws = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    extras, _ = build_web_thinking_extra_capabilities(
        workspace=ws,
        model_id="anthropic/claude-sonnet-4-20250514",
        tool_executor=_executor_with_web(),
        triage_tools=("serp",),
    )
    assert len(extras) == 1
    cap = extras[0]
    assert isinstance(cap, WebSearch)
    assert cap.native is not False


def test_build_web_thinking_extra_skips_without_web_tools() -> None:
    ws = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    extras, _ = build_web_thinking_extra_capabilities(
        workspace=ws,
        model_id="anthropic/claude-sonnet-4-20250514",
        tool_executor=_executor_with_web(),
        triage_tools=("read",),
    )
    assert extras == []


def test_thinking_effort_mapping(tmp_path: Path) -> None:
    cfg = tmp_path / "LLM_params_config.json"
    cfg.write_text(
        json.dumps(
            {
                "tier_b": {
                    "minimax_thinking": {
                        "enabled": True,
                        "type": "enabled",
                        "budget_tokens": 8192,
                    },
                },
            },
        ),
        encoding="utf-8",
    )
    effort = resolve_thinking_effort("tier_b", "minimax/MiniMax-M2", content_root=tmp_path)
    assert effort == "high"

    extras, thinking_flag = build_web_thinking_extra_capabilities(
        workspace=WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        ),
        model_id="minimax/MiniMax-M2",
        tool_executor=_executor_with_web(),
        triage_tools=("read",),
        content_root=tmp_path,
    )
    assert thinking_flag is True
    assert any(isinstance(c, Thinking) for c in extras)


def test_apply_minimax_hygiene_skips_thinking_when_capability_active() -> None:
    body: dict[str, object] = {"temperature": 1.0}
    apply_minimax_anthropic_request_hygiene(
        body,
        model_id="minimax/MiniMax-M2",
        agent="tier_b",
        content_root=None,
        has_tools=False,
        thinking_via_capability=True,
    )
    assert "thinking" not in body


@pytest.mark.asyncio
async def test_local_serp_dispatches_via_executor_and_filters_domains() -> None:
    from sevn.agent.adapters.tier_b_capabilities import build_serp_local_tool

    exe = ToolExecutor()

    async def _serp(
        _ctx: ToolContext, *, query: str, count: int = 5, region: str | None = None
    ) -> str:
        _ = _ctx, region
        payload = {
            "query": query,
            "count": 2,
            "results": [
                {"title": "good", "url": "https://python.org", "description": ""},
                {"title": "bad", "url": "https://evil.com", "description": ""},
            ],
        }
        return enveloped_success(payload)

    exe.register(
        FunctionTool(
            ToolDefinition(
                name="serp",
                category="web",
                description="search",
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            ),
            _serp,
        ),
    )
    tool = build_serp_local_tool(
        exe,
        policy=WebEgressDomainPolicy(blocked_domains=("evil.com",)),
    )
    assert tool is not None
    deps = BTierDeps(
        tool_executor=exe,
        tool_context_template=_ctx(),
        workspace_path=Path("/tmp"),
        registry_version=1,
        loaded_tools={"serp"},
    )
    ctx = RunContext(deps=deps, model=MagicMock(), usage=RunUsage())
    raw = await tool.function(ctx, query="python")
    blob = json.loads(raw)
    assert blob["ok"] is True
    assert blob["data"]["count"] == 1
    assert blob["data"]["results"][0]["url"] == "https://python.org"


@pytest.mark.asyncio
async def test_local_get_page_content_blocks_disallowed_host() -> None:
    from sevn.agent.adapters.tier_b_capabilities import build_get_page_content_local_tool

    exe = ToolExecutor()
    calls: list[str] = []

    async def _gpc(_ctx: ToolContext, *, url: str, max_length: int | None = None) -> str:
        _ = _ctx, max_length
        calls.append(url)
        return enveloped_success({"url": url, "markdown": "hi"})

    exe.register(
        FunctionTool(
            ToolDefinition(
                name="get_page_content",
                category="web",
                description="fetch",
                parameters={
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            ),
            _gpc,
        ),
    )
    tool = build_get_page_content_local_tool(
        exe,
        policy=WebEgressDomainPolicy(blocked_domains=("evil.com",)),
    )
    assert tool is not None
    deps = BTierDeps(
        tool_executor=exe,
        tool_context_template=_ctx(),
        workspace_path=Path("/tmp"),
        registry_version=1,
        loaded_tools={"get_page_content"},
    )
    ctx = RunContext(deps=deps, model=MagicMock(), usage=RunUsage())
    blocked = await tool.function(ctx, url="https://evil.com/page")
    assert json.loads(blocked)["ok"] is False
    assert calls == []

    allowed = await tool.function(ctx, url="https://python.org/doc")
    assert json.loads(allowed)["ok"] is True
    assert calls == ["https://python.org/doc"]


def test_registry_toolset_tags_web_tools_codemode_with_egress_policy() -> None:
    from sevn.agent.adapters.pydantic_adapter import PydanticToolRegistration
    from sevn.agent.adapters.tier_b_capabilities import WebEgressDomainPolicy
    from sevn.agent.adapters.tier_b_toolset import SevnRegistryToolset

    exe = _executor_with_web()
    reg = PydanticToolRegistration(
        tool_names=("get_page_content", "serp", "read"),
        tool_descriptions={"get_page_content": "g", "serp": "s", "read": "r"},
        skill_names=(),
        skill_descriptions={},
    )
    toolset = SevnRegistryToolset.from_registry(
        exe,
        reg,
        codemode_enabled=True,
        triager_tools=frozenset({"get_page_content", "serp"}),
        triager_skills=frozenset(),
        codemode_web_policy=WebEgressDomainPolicy(blocked_domains=("evil.com",)),
    )
    tagged = {t.name: (t.metadata or {}) for t in toolset.tools.values()}
    assert tagged["get_page_content"].get("code_mode") is True
    assert tagged["serp"].get("code_mode") is True
    assert tagged.get("read", {}).get("code_mode") is not True


def test_build_tier_b_capabilities_includes_web_thinking_extra() -> None:
    from pydantic_ai.capabilities.hooks import Hooks

    extra = [WebSearch(native=False, local=True)]
    caps = build_tier_b_capabilities(hooks=Hooks(), extra=extra)
    assert any(isinstance(c, WebSearch) for c in caps)
