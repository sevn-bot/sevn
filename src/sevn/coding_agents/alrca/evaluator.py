"""ALRCA evaluator — optional second-model LLM pass over executor output (CA3.3).

Module: sevn.coding_agents.alrca.evaluator
Depends: sevn.coding_agents.alrca.goal

Exports:
    EvaluatorResult — structured evaluation outcome.
    evaluate_turn — run an optional LLM evaluator pass.
    NullEvaluator — no-op evaluator (evaluator_model not configured).

The evaluator is intentionally separate from the executor model (D6 decision:
``evaluator_model`` is an independent config key per agent). When no
``evaluator_model`` is set, :func:`evaluate_turn` returns a neutral pass so the
loop continues unconditionally until verifiers decide.

Examples:
    >>> import asyncio
    >>> from sevn.coding_agents.alrca.goal import new_goal
    >>> g = new_goal(agent_id="a1", description="fix tests")
    >>> r = asyncio.run(evaluate_turn(g, executor_output="tests pass", evaluator_model=None))
    >>> r.passed
    True
    >>> r.reason
    'no evaluator_model configured — neutral pass'
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sevn.coding_agents.alrca.goal import GoalContract


@dataclass
class EvaluatorResult:
    """Structured evaluation outcome from the optional LLM judge.

    Args:
        passed (bool): Whether the evaluator considers progress satisfactory.
        reason (str): Human-readable evaluation rationale.
        score (float | None): Optional 0-1 quality score.

    Examples:
        >>> EvaluatorResult(passed=True, reason="ok").passed
        True
    """

    passed: bool
    reason: str
    score: float | None = None


class NullEvaluator:
    """No-op evaluator used when ``evaluator_model`` is not configured.

    Examples:
        >>> import asyncio
        >>> from sevn.coding_agents.alrca.goal import new_goal
        >>> g = new_goal(agent_id="a", description="d")
        >>> asyncio.run(NullEvaluator()(g, "output")).passed
        True
    """

    async def __call__(self, goal: GoalContract, executor_output: str) -> EvaluatorResult:
        """Return neutral pass.

        Args:
            goal (GoalContract): Active goal contract.
            executor_output (str): Latest executor stdout/artifact text.

        Returns:
            EvaluatorResult: Neutral pass with explanatory reason.

        Examples:
            >>> import asyncio
            >>> from sevn.coding_agents.alrca.goal import new_goal
            >>> g = new_goal(agent_id="a", description="d")
            >>> asyncio.run(NullEvaluator()(g, "output")).passed
            True
        """
        _ = goal, executor_output
        return EvaluatorResult(
            passed=True,
            reason="no evaluator_model configured — neutral pass",
        )


async def evaluate_turn(
    goal: GoalContract,
    executor_output: str,
    *,
    evaluator_model: str | None,
) -> EvaluatorResult:
    """Run the evaluator pass for one loop iteration.

    When ``evaluator_model`` is ``None`` a :class:`NullEvaluator` is used and
    the result is always a neutral pass. Real LLM evaluation is a stub pending
    integration with the sevn tier-B model client.

    Args:
        goal (GoalContract): Active goal contract.
        executor_output (str): Latest executor stdout/artifact text.
        evaluator_model (str | None): Catalog model id, or ``None``.

    Returns:
        EvaluatorResult: Evaluation outcome.

    Examples:
        >>> import asyncio
        >>> from sevn.coding_agents.alrca.goal import new_goal
        >>> g = new_goal(agent_id="a1", description="fix tests")
        >>> asyncio.run(evaluate_turn(g, "output", evaluator_model=None)).passed
        True
    """
    if evaluator_model is None:
        return await NullEvaluator()(goal, executor_output)
    return EvaluatorResult(
        passed=True,
        reason=f"[stub] evaluator_model={evaluator_model!r} — LLM judge not yet wired",
    )


__all__ = [
    "EvaluatorResult",
    "NullEvaluator",
    "evaluate_turn",
]
