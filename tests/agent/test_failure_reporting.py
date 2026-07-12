"""Wave W3: tier-B tool failures produce operator reports, not empty/no-data answers (D8)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sevn.agent.executors.b_types import BTierDeps
from sevn.prompts.fallbacks import format_tier_b_operator_failure_report
from sevn.tools.base import FunctionTool, ToolDefinition, ToolExecutor, enveloped_failure
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.meta_loaders import attach_meta_loaders
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import merge_skill_manifests, snapshot_tool_set


def _make_failing_executor() -> tuple[ToolExecutor, Any]:
    exe = ToolExecutor(default_timeout_seconds=30.0)

    async def _tick_fail(_ctx: ToolContext) -> str:
        return enveloped_failure("disk read timeout", code=ToolResultCode.TIMEOUT)

    tick_def = ToolDefinition(
        name="tick",
        category="meta",
        description="Harness tool that always fails.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
    )
    exe.register(FunctionTool(tick_def, _tick_fail))
    merged = merge_skill_manifests(None)
    native_map = {d.name: d for d in exe.definitions()}
    attach_meta_loaders(
        exe,
        native_definitions=dict(native_map),
        mcp_definitions={},
        skill_descriptions=merged,
        mcp_tool_names=frozenset(),
    )
    ts = snapshot_tool_set(
        exe,
        registry_version=88,
        skill_descriptions=merged,
        skill_inventory={},
        mcp_definitions=(),
        mcp_names=frozenset(),
    )
    return exe, ts


def test_operator_failure_report_template_names_tool() -> None:
    """Static report names the tool and invites retry — never claims missing data."""
    msg = format_tier_b_operator_failure_report(
        tool_name="history",
        tool_error="connection reset",
    )
    lowered = msg.lower()
    assert "history" in msg
    assert "connection reset" in msg
    assert "try again" in lowered
    assert "no history" not in lowered
    assert "no data" not in lowered


def test_b_harness_no_answer_report_includes_last_tool_failure(tmp_path: Path) -> None:
    """Empty-output path uses the last ``ok=false`` tool for the operator report (W3.4)."""
    exe, _ts = _make_failing_executor()
    deps = BTierDeps(
        tool_executor=exe,
        tool_context_template=ToolContext(
            session_id="s-fail",
            workspace_path=tmp_path,
            workspace_id="w",
            registry_version=88,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
            turn_id="t-fail",
        ),
        workspace_path=tmp_path,
        registry_version=88,
    )
    deps.note_tool_failure("history", "connection reset")
    report = format_tier_b_operator_failure_report(
        failure_detail="no assistant output produced",
        tool_name=deps.last_tool_failure_name,
        tool_error=deps.last_tool_failure_detail,
    )
    lowered = report.lower()
    assert "history" in report
    assert "connection reset" in report
    assert "try again" in lowered
    assert "no history" not in lowered
    assert "no data" not in lowered
