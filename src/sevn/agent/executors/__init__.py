"""Agent execution backends.

Module: sevn.agent.executors
Exports:
    run_b_turn — tier-B harness entry (`specs/14-executor-tier-b.md`).
    run_cd_turn — tier C/D harness entry (`specs/21-executor-tier-cd.md`).
    CdTurnOutcome, PlanGatePort, Plan, PlanStep, ResolvedCdOuterModels — C/D types (`cd_types`).
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "CdTurnOutcome",
    "Plan",
    "PlanGatePort",
    "PlanStep",
    "ResolvedCdOuterModels",
    "run_b_turn",
    "run_cd_turn",
]


def __getattr__(name: str) -> Any:
    """Lazily resolve heavy executor exports.

    Args:
        name (str): Attribute name being requested on the package.

    Returns:
        Any: The resolved attribute.

    Raises:
        AttributeError: When ``name`` is not a known lazy export.

    Examples:
        >>> from sevn.agent import executors
        >>> hasattr(executors, "__getattr__")
        True
    """

    if name == "run_b_turn":
        from sevn.agent.executors.b_harness import run_b_turn as run_b_turn_impl

        return run_b_turn_impl
    if name == "run_cd_turn":
        from sevn.agent.executors.cd_harness import run_cd_turn as run_cd_turn_impl

        return run_cd_turn_impl
    if name == "CdTurnOutcome":
        from sevn.agent.executors.cd_types import CdTurnOutcome

        return CdTurnOutcome
    if name == "PlanGatePort":
        from sevn.agent.executors.cd_types import PlanGatePort

        return PlanGatePort
    if name == "Plan":
        from sevn.agent.executors.cd_types import Plan

        return Plan
    if name == "PlanStep":
        from sevn.agent.executors.cd_types import PlanStep

        return PlanStep
    if name == "ResolvedCdOuterModels":
        from sevn.agent.executors.cd_types import ResolvedCdOuterModels

        return ResolvedCdOuterModels
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
