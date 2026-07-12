"""W7 — ``load_tool`` explicit grant under CodeMode (httpx-fetch plan D11)."""

from __future__ import annotations

from pathlib import Path

from pydantic_ai.messages import ToolCallPart

from sevn.agent.adapters.tier_b_hooks import apply_load_tool_grant
from sevn.agent.adapters.tool_part_filter import MutableToolAllowlist, filter_tool_call_parts
from sevn.agent.executors.b_types import BTierDeps, SteerInject
from sevn.agent.grounding import steer_for_codemode_loaded_tool
from sevn.tools.base import ToolExecutor
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy


def _deps(
    *,
    allowlist: MutableToolAllowlist,
    steer: SteerInject | None = None,
) -> BTierDeps:
    return BTierDeps(
        tool_executor=ToolExecutor(),
        tool_context_template=ToolContext(
            session_id="s",
            workspace_path=Path("/tmp"),
            workspace_id="w",
            registry_version=1,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
        ),
        workspace_path=Path("/tmp"),
        registry_version=1,
        tool_allowlist=allowlist,
        steer_buffer=steer,
    )


def test_grant_load_tool_bypasses_codemode_web_block() -> None:
    allow = MutableToolAllowlist(
        base=frozenset({"load_tool", "run_code"}),
        registry_names=frozenset({"load_tool", "run_code", "get_page_content", "serp"}),
        codemode_blocks_web_autogrants=True,
    )
    assert allow.grant_registry_tool("get_page_content") is False
    assert allow.grant_load_tool("get_page_content") is True
    assert "get_page_content" in allow.effective
    assert "get_page_content" in allow.load_granted


def test_load_tool_grant_keeps_web_tool_in_filtered_stream() -> None:
    allow = MutableToolAllowlist(
        base=frozenset({"load_tool", "run_code"}),
        registry_names=frozenset({"load_tool", "run_code", "get_page_content"}),
        codemode_blocks_web_autogrants=True,
    )
    allow.grant_load_tool("get_page_content")
    parts = [
        ToolCallPart(
            tool_name="get_page_content", args='{"url":"https://example.com"}', tool_call_id="g1"
        ),
    ]
    kept = filter_tool_call_parts(parts, allowed_tool_names=allow, log_prefix="tier_b")
    assert [p.tool_name for p in kept] == ["get_page_content"]  # type: ignore[attr-defined]


def test_apply_load_tool_grant_injects_codemode_steer_for_web_tool() -> None:
    allow = MutableToolAllowlist(
        base=frozenset({"load_tool", "run_code"}),
        registry_names=frozenset({"load_tool", "run_code", "get_page_content"}),
        codemode_blocks_web_autogrants=True,
    )
    steer = SteerInject()
    deps = _deps(allowlist=allow, steer=steer)
    apply_load_tool_grant(deps, "get_page_content")
    pending = steer.pop_pending()
    assert pending is not None
    assert pending == steer_for_codemode_loaded_tool("get_page_content")
    assert "run_code" in pending


def test_apply_load_tool_grant_no_steer_for_non_web_tool_under_codemode() -> None:
    allow = MutableToolAllowlist(
        base=frozenset({"load_tool", "run_code"}),
        registry_names=frozenset({"load_tool", "run_code", "glob"}),
        codemode_blocks_web_autogrants=True,
    )
    steer = SteerInject()
    deps = _deps(allowlist=allow, steer=steer)
    apply_load_tool_grant(deps, "glob")
    assert "glob" in allow.effective
    assert steer.pop_pending() is None
