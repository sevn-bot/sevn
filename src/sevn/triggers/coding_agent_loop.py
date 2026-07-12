"""Coding agent loop trigger — ALRCA background loop + session-mining hook (CA6.3).

Module: sevn.triggers.coding_agent_loop
Depends: sevn.coding_agents.alrca, sevn.coding_agents.artifacts

Exports:
    coding_agent_loop_trigger — run an ALRCA goal loop and mine trajectories on completion.
    mine_session_trajectories — post-loop session mining hook.

Session mining hook (CA6.3):
    On loop complete, scans ``#3 trajectories`` table for completed runs and proposes
    ``AGENTS.md`` / vault rule updates. Currently a stub that logs the intent; full
    trajectory integration lands with the #3 trajectories plan.

Examples:
    >>> import inspect
    >>> inspect.iscoroutinefunction(coding_agent_loop_trigger)
    True
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

JsonDict = dict[str, Any]


async def mine_session_trajectories(
    run_id: str,
    agent_id: str,
    workspace_path: Path,
) -> None:
    """Post-loop session-mining hook — stub pending #3 trajectories integration.

    Scans completed ALRCA runs and proposes AGENTS.md / vault rule updates. Until
    the #3 trajectories plan is wired, this emits a debug log and returns.

    Args:
        run_id (str): Completed ALRCA run identifier.
        agent_id (str): Registry agent id.
        workspace_path (Path): Operator workspace root.

    Returns:
        None: Always.

    Examples:
        >>> import asyncio, pathlib
        >>> asyncio.run(mine_session_trajectories("r1", "a1", pathlib.Path("."))) is None
        True
    """
    logger.debug(
        "session_mining: run={} agent={} workspace={} — stub, pending #3 trajectories",
        run_id,
        agent_id,
        workspace_path,
    )


async def coding_agent_loop_trigger(
    *,
    agent_id: str,
    message: str,
    workspace_path: Path,
    executor_id: str = "cursor",
    verifier_specs: list[str] | None = None,
    evaluator_model: str | None = None,
    max_turns: int = 10,
    trace: Any = None,
) -> JsonDict:
    """Run an ALRCA goal loop as a background trigger and mine on completion.

    Args:
        agent_id (str): Registry agent id.
        message (str): Goal description / task message.
        workspace_path (Path): Operator workspace root.
        executor_id (str): Executor backend id (``claude_code``, ``cursor``, ``codex``).
        verifier_specs (list[str] | None): Verifier spec strings.
        evaluator_model (str | None): Optional second-model evaluator.
        max_turns (int): Goal loop turn cap.
        trace (Any): Optional trace sink (``TraceSink | None``).

    Returns:
        JsonDict: Loop result summary.

    Examples:
        >>> import asyncio, pathlib, tempfile
        >>> with tempfile.TemporaryDirectory() as t:
        ...     r = asyncio.run(coding_agent_loop_trigger(
        ...         agent_id="a1", message="fix lint",
        ...         workspace_path=pathlib.Path(t),
        ...         executor_id="cursor",
        ...     ))
        ...     r["status"] in ("complete", "exhausted")
        True
    """
    from sevn.coding_agents.alrca.goal import new_goal
    from sevn.coding_agents.alrca.loop_worker import run_alrca_loop
    from sevn.coding_agents.executors import StubExecutor, build_executor

    try:
        executor = build_executor(executor_id)
    except ValueError:
        executor = StubExecutor()

    goal = new_goal(
        agent_id=agent_id,
        description=message,
        max_turns=max_turns,
    )

    result = await run_alrca_loop(
        goal,
        executor=executor,
        verifier_specs=verifier_specs or [],
        workspace_path=workspace_path,
        trace=trace,
        evaluator_model=evaluator_model,
    )

    await mine_session_trajectories(result.run_id, agent_id, workspace_path)

    return {
        "run_id": result.run_id,
        "agent_id": agent_id,
        "status": result.status.value,
        "turns_used": result.turns_used,
    }


__all__ = [
    "coding_agent_loop_trigger",
    "mine_session_trajectories",
]
