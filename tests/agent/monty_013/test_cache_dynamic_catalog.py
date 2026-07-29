"""W1.8 — CacheStabilityMonitor + CodeMode dynamic_catalog toggles (D9, W7)."""

from __future__ import annotations

import json

import pytest
from pydantic_ai.capabilities.hooks import Hooks

from sevn.agent.adapters.tier_b_codemode import build_codemode_capability
from sevn.agent.executors.b_harness import build_tier_b_capabilities
from tests.agent.monty_013.conftest import capability_class_names, load_capability_baseline


@pytest.mark.xfail(reason="green after W7: cache monitor toggle default-off (D9)", strict=False)
def test_cache_monitor_toggle_default_is_off() -> None:
    from sevn.config import defaults

    assert hasattr(defaults, "DEFAULT_TIER_B_CACHE_STABILITY_MONITOR_ENABLED")
    assert defaults.DEFAULT_TIER_B_CACHE_STABILITY_MONITOR_ENABLED is False


@pytest.mark.xfail(reason="green after W7: dynamic_catalog toggle default-off (D9)", strict=False)
def test_dynamic_catalog_toggle_default_is_off() -> None:
    from sevn.config import defaults

    assert hasattr(defaults, "DEFAULT_CODEMODE_DYNAMIC_CATALOG")
    assert defaults.DEFAULT_CODEMODE_DYNAMIC_CATALOG is False


@pytest.mark.xfail(
    reason="green after W7: default-off cache monitor is inventory no-op", strict=False
)
def test_cache_monitor_disabled_leaves_inventory_unchanged() -> None:
    baseline = load_capability_baseline()
    expected = baseline["scenarios"]["codemode_on"]["class_names"]
    hooks = Hooks()

    caps = build_tier_b_capabilities(
        hooks=hooks,
        codemode_on=True,
        cache_stability_monitor_enabled=False,  # type: ignore[call-arg]
    )
    assert capability_class_names(caps) == expected


@pytest.mark.xfail(
    reason="green after W7: dynamic_catalog keeps run_code schema stable", strict=False
)
def test_dynamic_catalog_true_keeps_run_code_tool_def_byte_stable() -> None:
    cap = build_codemode_capability(dynamic_catalog=True)  # type: ignore[call-arg]
    assert getattr(cap, "dynamic_catalog", False) is True

    first = json.dumps(
        cap.tool_def if hasattr(cap, "tool_def") else cap.get_tool_def(), sort_keys=True
    )

    cap.register_discovered_tool(name="new_tool", schema={"type": "object"})
    second = json.dumps(
        cap.tool_def if hasattr(cap, "tool_def") else cap.get_tool_def(), sort_keys=True
    )

    assert first == second, (
        "run_code tool definition must stay byte-stable when dynamic_catalog=True"
    )
