"""W1.1 — capability inventory snapshot vs W0.2 baseline (always green)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.agent.monty_013.conftest import (
    capability_class_names,
    load_capability_baseline,
    snapshot_capabilities,
)

if TYPE_CHECKING:
    from pydantic_ai.capabilities.abstract import AbstractCapability

    from sevn.agent.executors.b_types import BTierDeps


def test_capability_baseline_file_exists() -> None:
    baseline = load_capability_baseline()
    assert baseline["git_head"]
    assert "scenarios" in baseline


@pytest.mark.parametrize(
    ("scenario", "codemode_on", "overflow_on"),
    [
        ("codemode_off", False, True),
        ("codemode_on", True, True),
        ("codemode_on_no_overflow", True, False),
    ],
)
def test_build_tier_b_capabilities_matches_w0_baseline(
    build_caps,
    scenario: str,
    codemode_on: bool,
    overflow_on: bool,
) -> None:
    """Convention §6: capability set must match W0.2 unless a wave explicitly changes it."""
    baseline = load_capability_baseline()
    expected = baseline["scenarios"][scenario]

    caps: list[AbstractCapability[BTierDeps]] = build_caps(
        codemode_on=codemode_on,
        overflow_on=overflow_on,
    )

    assert capability_class_names(caps) == expected["class_names"]
    assert snapshot_capabilities(caps) == expected["capabilities"]
    assert len(caps) == expected["count"]
