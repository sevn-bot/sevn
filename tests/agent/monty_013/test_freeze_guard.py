"""W1.2 / W1.3 — Monty ResourceLimits freeze guard contracts (D5, D13)."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

import sevn.agent.adapters._monty_limits as monty_limits_mod
from sevn.agent.adapters._monty_limits import install_monty_resource_limits
from sevn.agent.adapters.pydantic_adapter import PydanticToolRegistration
from sevn.agent.adapters.tier_b_hooks import TierBHookConfig, build_tier_b_hooks
from sevn.agent.adapters.tier_b_toolset import SevnRegistryToolset
from sevn.agent.executors.b_harness import build_tier_b_capabilities
from sevn.agent.executors.b_types import BTierDeps
from sevn.config.defaults import DEFAULT_CODEMODE_MAX_DURATION_S
from sevn.tools.base import ToolExecutor
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy


def _reset_monty_limits_install_state() -> None:
    monty_limits_mod._installed = False
    monty_limits_mod._original_checkouts.clear()


def _hook_config() -> TierBHookConfig:
    return TierBHookConfig(
        provider_round_counter=[0],
        max_rounds=2,
        count_planning=False,
        bound_tool_names=frozenset({"run_code"}),
        triager_first_reply="",
    )


def _ctx() -> ToolContext:
    return ToolContext(
        session_id="s",
        workspace_path=Path("/tmp"),
        workspace_id="w",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )


def _deps(executor: ToolExecutor | None = None) -> BTierDeps:
    return BTierDeps(
        tool_executor=executor or ToolExecutor(),
        tool_context_template=_ctx(),
        workspace_path=Path("/tmp"),
        registry_version=1,
        loaded_tools={"run_code"},
    )


def test_install_raises_when_limit_injection_target_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D5: silent no-op when the patch target vanishes is forbidden."""
    _reset_monty_limits_install_state()
    guard_exc = getattr(monty_limits_mod, "MontyLimitInstallError", None)
    assert guard_exc is not None, "MontyLimitInstallError must be defined in _monty_limits (W3)"

    from pydantic_ai_harness.code_mode import _toolset as harness_toolset

    monkeypatch.delattr(harness_toolset, "Monty", raising=False)

    with pytest.raises(guard_exc, match=r"(?i)limit|injection|Monty"):
        install_monty_resource_limits({"max_duration_secs": 1})


@pytest.mark.asyncio
async def test_codemode_hang_terminates_within_tier_b_cap() -> None:
    """Hung run_code must abort within DEFAULT_CODEMODE_MAX_DURATION_S (limits + wait_for)."""
    cap_s = min(2.0, DEFAULT_CODEMODE_MAX_DURATION_S)
    install_monty_resource_limits({"max_duration_secs": cap_s})

    exe = ToolExecutor()
    reg = PydanticToolRegistration(
        tool_names=(),
        tool_descriptions={},
        skill_names=(),
        skill_descriptions={},
    )
    toolset = SevnRegistryToolset.from_registry(
        exe,
        reg,
        codemode_enabled=True,
        triager_tools=frozenset(),
        triager_skills=frozenset(),
        codemode_web_policy=None,
    )
    hooks = build_tier_b_hooks(_hook_config())
    deps = _deps(executor=exe)
    hang_code = "x = 0\nwhile True:\n    x += 1\n"

    async def model_fn(messages: list[object], info: MagicMock) -> ModelResponse:
        for msg in messages:
            for part in getattr(msg, "parts", ()):
                if getattr(part, "part_kind", "") == "tool-return":
                    return ModelResponse(parts=[TextPart(content="recovered")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="run_code",
                    args={"code": hang_code},
                    tool_call_id="rc-hang",
                ),
            ],
        )

    agent = Agent(
        FunctionModel(model_fn),
        toolsets=[toolset],
        deps_type=BTierDeps,
        capabilities=build_tier_b_capabilities(
            hooks=hooks,
            codemode_on=True,
            codemode_limits={"max_duration_secs": cap_s},
        ),
    )

    outer_cap = cap_s + 5.0
    t0 = time.monotonic()
    try:
        await asyncio.wait_for(agent.run("hang test", deps=deps), timeout=outer_cap)
    except TimeoutError as exc:
        pytest.fail(f"turn hung past outer cap: {exc}")
    except Exception:
        pass  # expected: Monty limit or tool error terminates the hang
    elapsed = time.monotonic() - t0
    assert elapsed < outer_cap, f"turn hung {elapsed:.1f}s — exceeds tier-B cap"
