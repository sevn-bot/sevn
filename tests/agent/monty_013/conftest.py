"""Shared fixtures for monty-013 / pydantic-ai v2 upgrade contract tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from pydantic_ai.capabilities.hooks import Hooks

from sevn.agent.executors.b_harness import build_tier_b_capabilities

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pydantic_ai.capabilities.abstract import AbstractCapability

    from sevn.agent.executors.b_types import BTierDeps

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BASELINE_PATH = _REPO_ROOT / ".ignorelocal/waves/monty-013-capability-baseline.json"


def repo_root() -> Path:
    """Return the repository root (worktree)."""
    return _REPO_ROOT


def baseline_path() -> Path:
    """Path to the W0.2 capability inventory snapshot."""
    return _BASELINE_PATH


def load_capability_baseline() -> dict[str, Any]:
    """Load the frozen W0.2 capability baseline JSON."""
    return json.loads(baseline_path().read_text(encoding="utf-8"))


def snapshot_capability(cap: AbstractCapability[BTierDeps]) -> dict[str, Any]:
    """Serialize one capability for inventory comparison."""
    entry: dict[str, Any] = {
        "class": cap.__class__.__name__,
        "module": cap.__class__.__module__,
        "defer_loading": bool(getattr(cap, "defer_loading", False)),
    }
    if cap.__class__.__name__ in ("CodeMode", "SevnAsyncCodeMode"):
        entry["max_retries"] = getattr(cap, "max_retries", None)
        tools = getattr(cap, "tools", None)
        entry["tools"] = dict(tools) if isinstance(tools, dict) else tools
    return entry


def snapshot_capabilities(
    caps: Sequence[AbstractCapability[BTierDeps]],
) -> list[dict[str, Any]]:
    """Serialize a capability list for inventory comparison."""
    return [snapshot_capability(cap) for cap in caps]


def capability_class_names(
    caps: Sequence[AbstractCapability[BTierDeps]],
) -> list[str]:
    """Return ordered capability class names."""
    return [cap.__class__.__name__ for cap in caps]


@pytest.fixture
def tier_b_hooks() -> Hooks:
    """Minimal tier-B hooks bundle for capability assembly tests."""
    return Hooks()


@pytest.fixture
def build_caps(tier_b_hooks: Hooks):
    """Factory mirroring W0.2 baseline scenarios."""

    def _build(
        *,
        codemode_on: bool = False,
        overflow_on: bool = True,
    ) -> list[AbstractCapability[BTierDeps]]:
        return build_tier_b_capabilities(
            hooks=tier_b_hooks,
            codemode_on=codemode_on,
            overflow_on=overflow_on,
        )

    return _build
