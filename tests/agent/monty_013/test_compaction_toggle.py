"""W1.7 — harness history compaction menu behind default-off toggle (D9, W6)."""

from __future__ import annotations

import pytest
from pydantic_ai.capabilities.hooks import Hooks

from sevn.agent.executors.b_harness import build_tier_b_capabilities
from tests.agent.monty_013.conftest import capability_class_names, load_capability_baseline


def _compaction_flag_name() -> str:
    return "DEFAULT_TIER_B_HISTORY_COMPACTION_ENABLED"


def test_compaction_toggle_default_is_off() -> None:
    from sevn.config import defaults

    assert hasattr(defaults, _compaction_flag_name())
    assert getattr(defaults, _compaction_flag_name()) is False


def test_compaction_disabled_does_not_change_inventory() -> None:
    baseline = load_capability_baseline()
    expected = baseline["scenarios"]["codemode_off"]["class_names"]
    hooks = Hooks()

    caps_off = build_tier_b_capabilities(
        hooks=hooks,
        history_compaction_enabled=False,  # type: ignore[call-arg]
    )
    caps_default = build_tier_b_capabilities(hooks=hooks)

    assert capability_class_names(caps_off) == expected
    assert capability_class_names(caps_default) == expected


@pytest.mark.asyncio
async def test_compaction_enabled_reduces_oversized_history() -> None:
    from sevn.agent.adapters.tier_b_compaction import compact_history_if_enabled

    messages = [{"role": "user", "content": "x" * 100_000} for _ in range(50)]
    compacted = await compact_history_if_enabled(messages, enabled=True)
    assert len(compacted) < len(messages)
    assert sum(len(str(m.get("content", ""))) for m in compacted) < sum(
        len(str(m.get("content", ""))) for m in messages
    )
