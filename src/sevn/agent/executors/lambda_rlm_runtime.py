"""Opt-in λ-RLM execute stub (`specs/21-executor-tier-cd.md` §2.5, §4.2).

No ``dspy.RLM`` Python REPL and no ``build_rlm_interpreter`` — this module only
summarises allowlisted tool **names** intersecting the live registry. Full combinator
execution lands with the upstream λ runtime.

Module: sevn.agent.executors.lambda_rlm_runtime
Depends: sevn.agent.executors.cd_types, sevn.tools.base

Exports:
    run_lambda_rlm_turn — one outer λ macro unit (+1 C/D outer round).

Examples:
    >>> import asyncio
    >>> from sevn.agent.executors.lambda_rlm_runtime import run_lambda_rlm_turn
    >>> from sevn.agent.executors.cd_types import Plan, PlanStep
    >>> from sevn.tools.base import ToolExecutor
    >>> from sevn.tools.context import ToolContext
    >>> from sevn.tools.permissions import AllowAllPermissionPolicy
    >>> from pathlib import Path
    >>> p = Plan(
    ...     steps=[PlanStep(id="1", title="t")],
    ...     summary="s",
    ...     meta=Plan.Meta(complexity="C", registry_version=1),
    ... )
    >>> async def _t():
    ...     exe = ToolExecutor(default_timeout_seconds=1.0)
    ...     ctx = ToolContext(
    ...         session_id="s",
    ...         workspace_path=Path("/tmp"),
    ...         workspace_id="w",
    ...         registry_version=1,
    ...         trace=None,
    ...         permissions=AllowAllPermissionPolicy(),
    ...     )
    ...     return await run_lambda_rlm_turn(
    ...         plan=p,
    ...         task="hi",
    ...         tool_executor=exe,
    ...         tool_ctx=ctx,
    ...         allowlist=frozenset(),
    ...     )
    >>> out, exhausted = asyncio.run(_t())
    >>> exhausted
    False
"""

from __future__ import annotations

from sevn.agent.executors.cd_types import Plan
from sevn.tools.base import ToolExecutor
from sevn.tools.context import ToolContext


async def run_lambda_rlm_turn(
    *,
    plan: Plan,
    task: str,
    tool_executor: ToolExecutor,
    tool_ctx: ToolContext,
    allowlist: frozenset[str],
) -> tuple[str, bool]:
    """Run one λ outer macro: allowlisted tool surface only (§2.5, §4.2).

    Does **not** call ``to_dspy_tools`` — combinator leaves are tracked as **names**
    intersecting the session registry (no inner REPL).

    Args:
        plan (Plan): Structured plan (may embed execution hints for future runtimes).
        task (str): User-visible task text for this turn.
        tool_executor (ToolExecutor): Registry aligned with the session ``ToolSet``.
        tool_ctx (ToolContext): Frozen dispatch envelope (trace, permissions, …).
        allowlist (frozenset[str]): ``rlm.lambda_tool_allowlist`` names ∩ session tools.

    Returns:
        tuple[str, bool]: Execution summary blob and **inner** budget exhaustion flag
            (stub always ``False`` until leaf LM budgeting lands).

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(run_lambda_rlm_turn)
        True
    """

    _ = task, tool_ctx
    names = frozenset(
        d.name for d in tool_executor.definitions() if d.enabled and d.name in allowlist
    )
    summary = (
        f"lambda_rlm macro: {len(plan.steps)} plan step(s); "
        f"allowlisted tool leaves: [{', '.join(sorted(names)) or 'none'}]"
    )
    return summary, False


lambda_macro_execute = run_lambda_rlm_turn

__all__ = ["lambda_macro_execute", "run_lambda_rlm_turn"]
