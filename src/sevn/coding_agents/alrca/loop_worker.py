"""ALRCA loop worker — wake/check/re-invoke executor until goal satisfied (CA3.2).

Module: sevn.coding_agents.alrca.loop_worker
Depends: sevn.agent.tracing.sink, sevn.coding_agents.alrca.evaluator,
    sevn.coding_agents.alrca.goal, sevn.coding_agents.alrca.verifiers

Exports:
    ALRCALoopWorker — orchestrates goal+verifiers+executor into a control loop.
    LoopResult — final outcome of one ALRCA loop run.
    run_alrca_loop — convenience wrapper to construct and run ALRCALoopWorker.

Trace events emitted:
    ``coding_agent.goal.start``       — goal run begins.
    ``coding_agent.loop.iteration``   — each turn (turn_number, executor_result summary).
    ``coding_agent.verifier.pass``    — verifier passed.
    ``coding_agent.verifier.fail``    — verifier failed.
    ``coding_agent.goal.complete``    — all verifiers passed.
    ``coding_agent.goal.exhausted``   — max_turns reached without success.

Examples:
    >>> import asyncio, pathlib, tempfile
    >>> from sevn.agent.tracing.sink import NullTraceSink
    >>> from sevn.coding_agents.alrca.goal import new_goal
    >>> from sevn.coding_agents.executors.protocol import ExecutorResult
    >>> async def fake_executor(goal, ctx):
    ...     return ExecutorResult(output="done", cost_usd=0.0, artifacts=[])
    >>> g = new_goal(agent_id="a1", description="fix tests",
    ...     success_criteria=[], max_turns=3)
    >>> with tempfile.TemporaryDirectory() as t:
    ...     worker = ALRCALoopWorker(
    ...         goal=g,
    ...         executor=fake_executor,
    ...         verifier_specs=[],
    ...         trace=NullTraceSink(),
    ...         workspace_path=pathlib.Path(t),
    ...     )
    ...     result = asyncio.run(worker.run())
    ...     result.status.value
    'complete'
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path  # noqa: TC003
from typing import Any

from sevn.agent.tracing.sink import SYSTEM_TURN_ID, TraceEvent, TraceSink
from sevn.coding_agents.alrca.evaluator import EvaluatorResult, evaluate_turn
from sevn.coding_agents.alrca.goal import GoalContract, GoalStatus, save_goal
from sevn.coding_agents.alrca.verifiers import VerifierResult, run_verifier_spec

JsonDict = dict[str, Any]

ExecutorCallable = Callable[[GoalContract, JsonDict], Awaitable[Any]]


@dataclass
class LoopResult:
    """Final outcome of one ALRCA goal run.

    Args:
        run_id (str): Goal run identifier.
        status (GoalStatus): Terminal state.
        turns_used (int): Number of executor invocations.
        verifier_results (list[VerifierResult]): Last verifier sweep results.
        evaluator_result (EvaluatorResult | None): Last evaluator output.

    Examples:
        >>> from sevn.coding_agents.alrca.goal import GoalStatus
        >>> r = LoopResult(run_id="r", status=GoalStatus.complete, turns_used=2)
        >>> r.status.value
        'complete'
    """

    run_id: str
    status: GoalStatus
    turns_used: int
    verifier_results: list[VerifierResult] = field(default_factory=list)
    evaluator_result: EvaluatorResult | None = None


class ALRCALoopWorker:
    """Orchestrate the ALRCA control loop for one goal run.

    Each call to :meth:`run` advances the goal until all verifiers pass,
    the evaluator vetoes continuation, or ``max_turns`` is exhausted.

    Args:
        goal (GoalContract): Goal contract driving this run.
        executor (ExecutorCallable): Async callable ``(goal, ctx) → ExecutorResult``.
        verifier_specs (list[str]): Spec strings for the verifier registry.
        trace (TraceSink): Destination for loop trace events.
        workspace_path (Path): Operator workspace root for verifiers + artifact vault.
        evaluator_model (str | None): Optional second-model evaluator config.
        context (JsonDict | None): Extra context passed to executor per turn.

    Examples:
        >>> import asyncio, pathlib, tempfile
        >>> from sevn.agent.tracing.sink import NullTraceSink
        >>> from sevn.coding_agents.alrca.goal import new_goal
        >>> from sevn.coding_agents.executors.protocol import ExecutorResult
        >>> async def fake_exec(g, ctx):
        ...     return ExecutorResult(output="ok", cost_usd=0.0, artifacts=[])
        >>> g = new_goal(agent_id="a1", description="d")
        >>> with tempfile.TemporaryDirectory() as t:
        ...     w = ALRCALoopWorker(
        ...         goal=g, executor=fake_exec, verifier_specs=[],
        ...         trace=NullTraceSink(), workspace_path=pathlib.Path(t),
        ...     )
        ...     asyncio.run(w.run()).status.value
        'complete'
    """

    def __init__(
        self,
        *,
        goal: GoalContract,
        executor: ExecutorCallable,
        verifier_specs: list[str],
        trace: TraceSink,
        workspace_path: Path,
        evaluator_model: str | None = None,
        context: JsonDict | None = None,
    ) -> None:
        """Wire goal, executor, verifiers, and trace for a loop run.

        Args:
            goal (GoalContract): Goal contract driving this run.
            executor (ExecutorCallable): Async ``(goal, ctx) → ExecutorResult`` callable.
            verifier_specs (list[str]): Spec strings for the verifier registry.
            trace (TraceSink): Destination for loop trace events.
            workspace_path (Path): Operator workspace root.
            evaluator_model (str | None): Optional second-model evaluator.
            context (JsonDict | None): Extra context passed per turn.

        Examples:
            >>> from sevn.agent.tracing.sink import NullTraceSink
            >>> from sevn.coding_agents.alrca.goal import new_goal
            >>> import pathlib
            >>> g = new_goal(agent_id="a", description="d")
            >>> w = ALRCALoopWorker(
            ...     goal=g, executor=lambda g, c: None, verifier_specs=[],
            ...     trace=NullTraceSink(), workspace_path=pathlib.Path("."),
            ... )
            >>> w._goal.agent_id
            'a'
        """
        self._goal = goal
        self._executor = executor
        self._verifier_specs = list(verifier_specs)
        self._trace = trace
        self._workspace = workspace_path
        self._evaluator_model = evaluator_model
        self._context: JsonDict = context or {}

    # ------------------------------------------------------------------
    # Trace helpers
    # ------------------------------------------------------------------

    def _span_id(self) -> str:
        """Generate a new UUID4 span id.

        Returns:
            str: Fresh span id string.

        Examples:
            >>> from sevn.agent.tracing.sink import NullTraceSink
            >>> from sevn.coding_agents.alrca.goal import new_goal
            >>> from sevn.coding_agents.executors.protocol import ExecutorResult
            >>> import pathlib
            >>> g = new_goal(agent_id="a", description="d")
            >>> w = ALRCALoopWorker(
            ...     goal=g, executor=lambda g, c: None, verifier_specs=[],
            ...     trace=NullTraceSink(), workspace_path=pathlib.Path("."),
            ... )
            >>> len(w._span_id()) > 8
            True
        """
        return str(uuid.uuid4())

    async def _emit(self, kind: str, attrs: JsonDict) -> None:
        """Emit one trace event with the given kind and attrs.

        Args:
            kind (str): Event kind string.
            attrs (JsonDict): Event attributes dict.

        Returns:
            None: Always.

        Examples:
            >>> import asyncio, pathlib
            >>> from sevn.agent.tracing.sink import NullTraceSink
            >>> from sevn.coding_agents.alrca.goal import new_goal
            >>> g = new_goal(agent_id="a", description="d")
            >>> w = ALRCALoopWorker(
            ...     goal=g, executor=lambda g, c: None, verifier_specs=[],
            ...     trace=NullTraceSink(), workspace_path=pathlib.Path("."),
            ... )
            >>> asyncio.run(w._emit("test.event", {"x": 1})) is None
            True
        """
        ts = time.time_ns()
        await self._trace.emit(
            TraceEvent(
                kind=kind,
                span_id=self._span_id(),
                parent_span_id=None,
                session_id=self._goal.agent_id,
                turn_id=self._goal.run_id or SYSTEM_TURN_ID,
                tier=None,
                ts_start_ns=ts,
                ts_end_ns=ts,
                status="ok",
                attrs=attrs,
            ),
        )

    # ------------------------------------------------------------------
    # Loop
    # ------------------------------------------------------------------

    async def run(self) -> LoopResult:
        """Execute the ALRCA control loop until termination.

        Returns:
            LoopResult: Terminal result with status, turns used, and verifier outcomes.

        Examples:
            >>> import asyncio, pathlib, tempfile
            >>> from sevn.agent.tracing.sink import NullTraceSink
            >>> from sevn.coding_agents.alrca.goal import new_goal
            >>> from sevn.coding_agents.executors.protocol import ExecutorResult
            >>> async def fake_exec(g, ctx):
            ...     return ExecutorResult(output="ok", cost_usd=0.0, artifacts=[])
            >>> g = new_goal(agent_id="a", description="d", max_turns=2)
            >>> with tempfile.TemporaryDirectory() as t:
            ...     w = ALRCALoopWorker(
            ...         goal=g, executor=fake_exec, verifier_specs=["script:true"],
            ...         trace=NullTraceSink(), workspace_path=pathlib.Path(t),
            ...     )
            ...     asyncio.run(w.run()).turns_used
            1
        """
        goal = self._goal
        goal.status = GoalStatus.running
        save_goal(goal, self._workspace)

        await self._emit(
            "coding_agent.goal.start",
            {
                "run_id": goal.run_id,
                "agent_id": goal.agent_id,
                "description": goal.description,
                "max_turns": goal.max_turns,
                "verifier_count": len(self._verifier_specs),
            },
        )

        last_verifier_results: list[VerifierResult] = []
        last_evaluator: EvaluatorResult | None = None
        turns_used = 0

        for turn_number in range(1, goal.max_turns + 1):
            turns_used = turn_number

            executor_result = await self._executor(goal, self._context)
            output_text: str = getattr(executor_result, "output", str(executor_result))

            await self._emit(
                "coding_agent.loop.iteration",
                {
                    "run_id": goal.run_id,
                    "turn_number": turn_number,
                    "executor_output_len": len(output_text),
                    "cost_usd": getattr(executor_result, "cost_usd", None),
                },
            )

            last_evaluator = await evaluate_turn(
                goal,
                output_text,
                evaluator_model=self._evaluator_model,
            )

            last_verifier_results = await self._run_verifiers()

            all_passed = all(r.passed for r in last_verifier_results)
            if all_passed and last_evaluator.passed:
                goal.status = GoalStatus.complete
                save_goal(goal, self._workspace)
                await self._emit(
                    "coding_agent.goal.complete",
                    {"run_id": goal.run_id, "turns_used": turns_used},
                )
                return LoopResult(
                    run_id=goal.run_id,
                    status=GoalStatus.complete,
                    turns_used=turns_used,
                    verifier_results=last_verifier_results,
                    evaluator_result=last_evaluator,
                )

        goal.status = GoalStatus.exhausted
        save_goal(goal, self._workspace)
        await self._emit(
            "coding_agent.goal.exhausted",
            {"run_id": goal.run_id, "turns_used": turns_used, "max_turns": goal.max_turns},
        )
        return LoopResult(
            run_id=goal.run_id,
            status=GoalStatus.exhausted,
            turns_used=turns_used,
            verifier_results=last_verifier_results,
            evaluator_result=last_evaluator,
        )

    async def _run_verifiers(self) -> list[VerifierResult]:
        """Run all configured verifier specs sequentially.

        Returns:
            list[VerifierResult]: One result per configured verifier spec.

        Examples:
            >>> import asyncio, pathlib, tempfile
            >>> from sevn.agent.tracing.sink import NullTraceSink
            >>> from sevn.coding_agents.alrca.goal import new_goal
            >>> g = new_goal(agent_id="a", description="d")
            >>> with tempfile.TemporaryDirectory() as t:
            ...     w = ALRCALoopWorker(
            ...         goal=g, executor=lambda g, c: None, verifier_specs=["script:true"],
            ...         trace=NullTraceSink(), workspace_path=pathlib.Path(t),
            ...     )
            ...     results = asyncio.run(w._run_verifiers())
            ...     results[0].passed
            True
        """
        if not self._verifier_specs:
            return []
        results: list[VerifierResult] = []
        for spec in self._verifier_specs:
            result = await run_verifier_spec(spec, self._workspace)
            event_kind = (
                "coding_agent.verifier.pass" if result.passed else "coding_agent.verifier.fail"
            )
            await self._emit(
                event_kind,
                {
                    "run_id": self._goal.run_id,
                    "spec": spec,
                    "exit_code": result.exit_code,
                    "output_len": len(result.output),
                },
            )
            results.append(result)
        return results


async def run_alrca_loop(
    goal: GoalContract,
    *,
    executor: ExecutorCallable,
    verifier_specs: list[str],
    workspace_path: Path,
    trace: TraceSink | None = None,
    evaluator_model: str | None = None,
    context: JsonDict | None = None,
) -> LoopResult:
    """Convenience wrapper: construct and run an :class:`ALRCALoopWorker`.

    Args:
        goal (GoalContract): Goal contract for this run.
        executor (ExecutorCallable): Async ``(goal, ctx) → ExecutorResult`` callable.
        verifier_specs (list[str]): Verifier spec strings.
        workspace_path (Path): Operator workspace root.
        trace (TraceSink | None): Trace sink; a :class:`~sevn.agent.tracing.sink.NullTraceSink`
            is used when ``None``.
        evaluator_model (str | None): Optional second-model evaluator.
        context (JsonDict | None): Extra context for executor turns.

    Returns:
        LoopResult: Terminal loop outcome.

    Examples:
        >>> import asyncio, pathlib, tempfile
        >>> from sevn.agent.tracing.sink import NullTraceSink
        >>> from sevn.coding_agents.alrca.goal import new_goal
        >>> from sevn.coding_agents.executors.protocol import ExecutorResult
        >>> async def fake_exec(g, ctx):
        ...     return ExecutorResult(output="ok", cost_usd=0.0, artifacts=[])
        >>> g = new_goal(agent_id="a", description="d", max_turns=2)
        >>> with tempfile.TemporaryDirectory() as t:
        ...     asyncio.run(run_alrca_loop(
        ...         g, executor=fake_exec, verifier_specs=[],
        ...         workspace_path=pathlib.Path(t),
        ...     )).status.value
        'complete'
    """
    from sevn.agent.tracing.sink import NullTraceSink

    effective_trace: TraceSink = trace if trace is not None else NullTraceSink()
    worker = ALRCALoopWorker(
        goal=goal,
        executor=executor,
        verifier_specs=verifier_specs,
        trace=effective_trace,
        workspace_path=workspace_path,
        evaluator_model=evaluator_model,
        context=context,
    )
    return await worker.run()


__all__ = [
    "ALRCALoopWorker",
    "LoopResult",
    "run_alrca_loop",
]
