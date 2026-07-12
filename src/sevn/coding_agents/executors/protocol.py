"""Executor protocol + result type for ALRCA backends (CA4.1).

Module: sevn.coding_agents.executors.protocol
Depends: dataclasses

Exports:
    ExecutorResult — structured result from one executor turn.
    ExecutorProtocol — awaitable callable protocol for executor backends.

All executor backends implement ``ExecutorProtocol``:
    ``async (goal: GoalContract, context: dict) -> ExecutorResult``

Examples:
    >>> from sevn.coding_agents.executors.protocol import ExecutorResult
    >>> r = ExecutorResult(output="ok", cost_usd=0.001, artifacts=[])
    >>> r.output
    'ok'
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from sevn.coding_agents.alrca.goal import GoalContract

JsonDict = dict[str, Any]


@dataclass
class ExecutorResult:
    """One executor turn result.

    Args:
        output (str): Captured stdout or response text from the executor.
        cost_usd (float): Estimated USD cost (0.0 when not applicable).
        artifacts (list[str]): Paths to any files written by the executor.
        exit_code (int | None): Process exit code when subprocess-based.
        extra (JsonDict): Extension attributes.

    Examples:
        >>> ExecutorResult(output="ok", cost_usd=0.0, artifacts=[]).cost_usd
        0.0
    """

    output: str
    cost_usd: float
    artifacts: list[str] = field(default_factory=list)
    exit_code: int | None = None
    extra: JsonDict = field(default_factory=dict)


@runtime_checkable
class ExecutorProtocol(Protocol):
    """Awaitable callable that runs one executor turn.

    Implementations accept the active :class:`~sevn.coding_agents.alrca.goal.GoalContract`
    and a context dict, and return an :class:`ExecutorResult`.
    """

    async def __call__(
        self,
        goal: GoalContract,
        context: JsonDict,
    ) -> ExecutorResult:
        """Run one executor turn and return a structured result.

        Args:
            goal (GoalContract): Active goal contract for this run.
            context (JsonDict): Per-turn context (``workspace_path``, env, etc.).

        Returns:
            ExecutorResult: Captured output, cost, and artifact paths.

        Examples:
            >>> from sevn.coding_agents.executors.protocol import ExecutorResult
            >>> r = ExecutorResult(output="done", cost_usd=0.0, artifacts=[])
            >>> r.output
            'done'
        """
        ...


ExecutorCallable = Callable[["GoalContract", JsonDict], Awaitable[ExecutorResult]]

__all__ = [
    "ExecutorCallable",
    "ExecutorProtocol",
    "ExecutorResult",
]
