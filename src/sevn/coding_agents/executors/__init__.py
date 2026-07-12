"""ALRCA executor backends — ExecutorProtocol + stub factory (CA4).

Module: sevn.coding_agents.executors
Depends: sevn.coding_agents.executors.protocol

Exports:
    StubExecutor — deterministic no-op backend for tests.
    build_executor — construct executor from config executor id string.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sevn.coding_agents.executors.protocol import ExecutorProtocol, ExecutorResult

if TYPE_CHECKING:
    from sevn.coding_agents.alrca.goal import GoalContract

JsonDict = dict[str, Any]


class StubExecutor:
    """Deterministic no-op executor for tests and offline development."""

    def __init__(self, *, output: str = "stub output") -> None:
        """Wire fixed output text.

        Args:
            output (str): Output text returned by each stub turn.

        Examples:
            >>> StubExecutor(output="ok")._output
            'ok'
        """
        self._output = output

    async def __call__(self, goal: GoalContract, context: JsonDict) -> ExecutorResult:
        """Return a fixed stub result.

        Args:
            goal (GoalContract): Active goal (ignored).
            context (JsonDict): Turn context (ignored).

        Returns:
            ExecutorResult: Fixed stub result with configured output.

        Examples:
            >>> import asyncio
            >>> from sevn.coding_agents.alrca.goal import new_goal
            >>> g = new_goal(agent_id="a", description="d")
            >>> asyncio.run(StubExecutor(output="done")(g, {})).output
            'done'
        """
        _ = goal, context
        return ExecutorResult(output=self._output, cost_usd=0.0, artifacts=[])


def build_executor(executor_id: str, **kwargs: Any) -> ExecutorProtocol:
    """Construct an executor from a config executor id string.

    Live ``claude_code`` / ``cursor`` / ``codex`` wiring is deferred; all ids
    return :class:`StubExecutor` until CA4 live-smoke markers land.

    Args:
        executor_id (str): Config executor id.
        kwargs (Any): Reserved for backend-specific options.

    Returns:
        ExecutorProtocol: Stub executor for recognised ids.

    Raises:
        ValueError: When ``executor_id`` is not recognised.

    Examples:
        >>> isinstance(build_executor("cursor"), StubExecutor)
        True
    """
    _ = kwargs
    known = {"claude_code", "cursor", "codex", "stub"}
    if executor_id not in known:
        msg = f"unknown executor_id={executor_id!r}; known: {', '.join(sorted(known))}"
        raise ValueError(msg)
    return StubExecutor(output=f"stub:{executor_id}")


__all__ = [
    "StubExecutor",
    "build_executor",
]
