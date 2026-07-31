"""W23.6 — human denial reasons reach the model (#80 → W26).

Exercises sync ``SkipToolExecution`` and deferred ``ToolDenied`` paths in tier-B guardrails.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import RunContext
from pydantic_ai.exceptions import SkipToolExecution
from pydantic_ai.tools import ToolDenied
from pydantic_ai.usage import RunUsage

from sevn.agent.adapters.tier_b_guardrails import (
    TierBApprovalGuardrail,
    TierBPermissionGuardrail,
)
from sevn.agent.adapters.tier_b_hooks import TierBHookConfig, check_permission_before_dispatch
from sevn.agent.executors.b_types import BTierDeps
from sevn.tools.base import FunctionTool, ToolDefinition, ToolExecutor, enveloped_success
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy


def _hook_config() -> TierBHookConfig:
    return TierBHookConfig(
        provider_round_counter=[0],
        max_rounds=3,
        count_planning=False,
        bound_tool_names=frozenset(),
        triager_first_reply="",
    )


def _deps(*, permissions: AllowAllPermissionPolicy | None = None) -> BTierDeps:
    exe = ToolExecutor()
    exe.register(
        FunctionTool(
            ToolDefinition(
                name="delete",
                category="file",
                description="delete",
                parameters={"type": "object", "properties": {}},
                requires_human=False,
            ),
            lambda _ctx: enveloped_success({"deleted": True}),
        ),
    )
    return BTierDeps(
        tool_executor=exe,
        tool_context_template=ToolContext(
            session_id="sess-deny-feedback",
            workspace_path=Path("/tmp"),
            workspace_id="w",
            registry_version=1,
            trace=None,
            permissions=permissions or AllowAllPermissionPolicy(),
        ),
        workspace_path=Path("/tmp"),
        registry_version=1,
        loaded_tools={"delete"},
    )


def _run_ctx(deps: BTierDeps) -> RunContext[BTierDeps]:
    return RunContext(deps=deps, model=MagicMock(), usage=RunUsage())


@pytest.mark.asyncio
@pytest.mark.xfail(
    reason="green after W26: SkipToolExecution carries operator denial reason", strict=False
)
async def test_permission_guardrail_skip_envelope_includes_human_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sync path: ``SkipToolExecution`` JSON includes the operator's denial reason."""
    from sevn.tools.deny_rules import enveloped_deny_with_reason

    deps = _deps()
    human_reason = "Do not delete production configs without a ticket"
    denial = enveloped_deny_with_reason(tool_name="delete", reason=human_reason)

    def _deny(_deps: BTierDeps, tool_name: str) -> str | None:
        return denial if tool_name == "delete" else None

    monkeypatch.setattr(
        "sevn.agent.adapters.tier_b_guardrails.check_permission_before_dispatch",
        _deny,
    )
    guard = TierBPermissionGuardrail(_hook_config())
    ctx = _run_ctx(deps)
    with pytest.raises(SkipToolExecution) as exc_info:
        await guard.check_tool_access(ctx, tool_name="delete", args={})
    blob = json.loads(str(exc_info.value))
    assert blob.get("message") == human_reason or human_reason in str(blob)


@pytest.mark.asyncio
@pytest.mark.xfail(
    reason="green after W26: ToolDenied carries operator denial reason", strict=False
)
async def test_approval_guardrail_tool_denied_includes_human_reason() -> None:
    """Deferred path: ``ToolDenied.message`` includes the operator's denial reason."""
    bridge = MagicMock()
    bridge.await_operator_verdict = AsyncMock(return_value="deny")
    bridge.await_approval = None
    bridge.record_session_ack = MagicMock()

    deps = _deps()
    deps.approval_bridge = bridge
    ctx = _run_ctx(deps)

    guard = TierBApprovalGuardrail(_hook_config())
    denied = await guard.resolve(ctx, tool_name="delete", args={"path": "/etc/sevn.json"})
    assert isinstance(denied, ToolDenied)
    assert "ticket" in denied.message.lower() or "operator" in denied.message.lower()


@pytest.mark.asyncio
@pytest.mark.xfail(
    reason="green after W26: check_permission_before_dispatch merges deny rules", strict=False
)
async def test_check_permission_surfaces_configured_deny_reason() -> None:
    """Pre-dispatch hook returns PERMISSION_DENIED with the configured deny reason."""
    deps = _deps()
    ws_permissions = {
        "default_profile": "open",
        "profiles": {"open": {"mode": "abac"}},
        "deny_rules": [
            {"tool": "delete", "reason": "operator blocked delete in this session"},
        ],
    }
    deps.workspace_permissions = ws_permissions  # type: ignore[attr-defined]
    denial = check_permission_before_dispatch(deps, "delete")
    assert denial is not None
    blob = json.loads(denial)
    assert blob["message"] == "operator blocked delete in this session"
