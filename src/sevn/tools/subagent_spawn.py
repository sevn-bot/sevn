"""``spawn_subagent`` — level-1 → level-2 sub-agent spawn tool (D9, `specs/36-sub-agents.md`).

Default fire-and-forget: returns the run id immediately; the supervisor's
``AnnounceBackHook`` (wired at gateway boot — ``sevn.gateway.subagents.subagents_announce``)
delivers the result once the level-2 run finishes. ``wait=True`` blocks the
caller instead, bounded by the parent turn's remaining ``CascadeBudget`` (D11).

Module: sevn.tools.subagent_spawn
Depends: sevn.agent.subagents, sevn.tools.base, sevn.tools.context, sevn.tools.decorator

Exports:
    spawn_subagent_tool — the ``spawn_subagent`` tool body.
    register_subagent_spawn_tools — register on a ``ToolExecutor`` unless disabled.

Examples:
    >>> from sevn.tools.base import ToolExecutor
    >>> from sevn.tools.subagent_spawn import register_subagent_spawn_tools
    >>> exe = ToolExecutor()
    >>> register_subagent_spawn_tools(exe, None)
    >>> "spawn_subagent" in {d.name for d in exe.definitions()}
    True
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from sevn.agent.subagents import (
    SubAgentLimitExceeded,
    SubAgentSpec,
    resolve_specialist,
    specialist_spawn_allowed,
)
from sevn.tools.base import enveloped_failure, enveloped_success
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.decorator import sevn_tool, tool_from_decorated

if TYPE_CHECKING:
    from sevn.config.sections.subagents import Role
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.tools.base import ToolExecutor

_MAX_TASK_SUMMARY_CHARS = 200
_MIN_WAIT_TIMEOUT_S = 0.1


async def _specialist_worker_body(
    ctx: ToolContext,
    *,
    task: str,
    specialist: str | None,
) -> str:
    """Dispatch a level-2 worker body for a named specialist (W8).

    Args:
        ctx (ToolContext): Spawn invocation context (session, router, supervisor).
        task (str): Sub-task description passed to ``spawn_subagent``.
        specialist (str | None): Specialist name when this is a specialist spawn.

    Returns:
        str: Worker result text (JSON for ``media_generator``).

    Raises:
        Exception: Propagates generation failures to the spawn tool wait path.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_specialist_worker_body)
        True
    """
    if specialist == "media_generator":
        from sevn.agent.subagents.media_worker import execute_media_generator_for_context

        return await execute_media_generator_for_context(ctx, task)
    return await _placeholder_worker_body(task=task, specialist=specialist)


async def _placeholder_worker_body(*, task: str, specialist: str | None) -> str:
    """Stand-in level-2 worker body (W3 scope: spawn/track/limit/announce-back plumbing only).

    Real nested-worker execution (generic: reusing the parent turn's resolved
    model; specialist: the MiniMax invocation path) is out of W3's scope —
    see `specs/36-sub-agents.md` Build Checklist (W8 for specialists).

    Args:
        task (str): Sub-task description passed to ``spawn_subagent``.
        specialist (str | None): Specialist name when this is a specialist spawn.

    Returns:
        str: Placeholder result text.

    Examples:
        >>> import asyncio
        >>> asyncio.run(_placeholder_worker_body(task="draft a haiku", specialist=None))[:15]
        '[sub-agent] not'
    """
    who = f"specialist '{specialist}'" if specialist else "sub-agent"
    return (
        f"[{who}] noted task: {task}. Real worker execution ships in a follow-up "
        "wave (this run exercised spawn/track/limit/announce-back plumbing only)."
    )


@sevn_tool(
    name="spawn_subagent",
    category="subagents",
    description=(
        "Spawn a level-2 sub-agent to work on a sub-task in the background. "
        "Fire-and-forget by default — returns immediately with a run id, and the "
        "result is announced back once it finishes. Pass wait=true to block for "
        "the result inline instead (bounded by the remaining turn budget)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Sub-task description for the spawned worker.",
            },
            "specialist": {
                "type": "string",
                "description": (
                    "Optional specialist name (e.g. 'media_generator'). Omit for a "
                    "generic worker using the parent's own model configuration."
                ),
            },
            "wait": {
                "type": "boolean",
                "description": (
                    "Block until the sub-agent finishes (bounded by the remaining "
                    "cascade budget) instead of the default fire-and-forget."
                ),
            },
        },
        "required": ["task"],
    },
    abortable=True,
)
async def spawn_subagent_tool(
    ctx: ToolContext,
    *,
    task: str,
    specialist: str | None = None,
    wait: bool = False,
) -> str:
    """Spawn a level-2 sub-agent against the process-wide supervisor (D9).

    Args:
        ctx (ToolContext): Invocation context — requires ``subagent_supervisor``,
            ``subagent_role``, and ``subagent_parent_id`` to be wired (W3.1).
        task (str): Sub-task description.
        specialist (str | None): Optional specialist name (D8).
        wait (bool): When ``True``, block for the result within the remaining
            cascade budget (D11) instead of the default fire-and-forget (D9).

    Returns:
        str: §3.1 JSON envelope string.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(spawn_subagent_tool)
        True
    """
    task_text = task.strip()
    if not task_text:
        return enveloped_failure("task must be non-empty", code=ToolResultCode.VALIDATION_ERROR)
    supervisor = ctx.subagent_supervisor
    if supervisor is None:
        return enveloped_failure(
            "sub-agent spawning is unavailable (supervisor not wired)",
            code=ToolResultCode.TOOL_NOT_PROVISIONED,
        )
    role = ctx.subagent_role
    parent_id = ctx.subagent_parent_id
    if not role or not parent_id:
        return enveloped_failure(
            "spawn_subagent requires an active level-1 run context",
            code=ToolResultCode.INTERNAL_ERROR,
        )
    specialist_name = (specialist or "").strip() or None
    if specialist_name is not None:
        specialist_cfg = resolve_specialist(supervisor.config, specialist_name)
        if specialist_cfg is None:
            return enveloped_failure(
                f"unknown specialist: {specialist_name}",
                code=ToolResultCode.VALIDATION_ERROR,
            )
        granted = specialist_name in ctx.subagent_specialist_grants
        if not specialist_spawn_allowed(
            specialist_cfg,
            role=cast("Role", role),
            granted_by_triager=granted,
        ):
            return enveloped_failure(
                f"role '{role}' is not permitted to spawn specialist '{specialist_name}'",
                code=ToolResultCode.PERMISSION_DENIED,
            )

    outcome: dict[str, str] = {}

    async def _work() -> str:
        try:
            text = await _specialist_worker_body(
                ctx,
                task=task_text,
                specialist=specialist_name,
            )
        except Exception as exc:  # recorded for the wait=True path below
            outcome["error"] = str(exc)
            raise
        outcome["result"] = text
        return text

    spec = SubAgentSpec(
        level=2,
        role=cast("Role", role),
        body=_work,
        session_id=ctx.session_id,
        channel=ctx.delivery_channel,
        task_summary=task_text[:_MAX_TASK_SUMMARY_CHARS],
        specialist=specialist_name,
        parent_id=parent_id,
    )
    handle = await supervisor.spawn(spec)
    if isinstance(handle, SubAgentLimitExceeded):
        return enveloped_failure(str(handle), code=ToolResultCode.VALIDATION_ERROR)
    if not wait:
        return enveloped_success(
            {
                "run_id": handle.id,
                "level": 2,
                "status": "spawned",
                "mode": "fire_and_forget",
            },
        )
    remaining_fn = ctx.subagent_remaining_budget_s
    remaining = remaining_fn() if remaining_fn is not None else None
    timeout_s = max(_MIN_WAIT_TIMEOUT_S, remaining) if remaining is not None else None
    try:
        if timeout_s is not None:
            await asyncio.wait_for(asyncio.shield(handle.task), timeout=timeout_s)
        else:
            await handle.task
    except TimeoutError:
        await supervisor.kill(handle.id)
        return enveloped_failure(
            f"sub-agent {handle.id} did not complete within the remaining cascade budget",
            code=ToolResultCode.TOOL_TIMEOUT,
        )
    if "error" in outcome:
        return enveloped_failure(
            f"sub-agent {handle.id} failed: {outcome['error']}",
            code=ToolResultCode.INTERNAL_ERROR,
        )
    return enveloped_success(
        {
            "run_id": handle.id,
            "level": 2,
            "status": "done",
            "result": outcome.get("result", ""),
        },
    )


def register_subagent_spawn_tools(
    executor: ToolExecutor,
    workspace_config: WorkspaceConfig | None,
) -> None:
    """Register ``spawn_subagent`` unless ``subagents.enabled`` is explicitly ``False``.

    Args:
        executor (ToolExecutor): Registry under construction.
        workspace_config (WorkspaceConfig | None): Parsed workspace; ``None`` registers
            with defaults (sub-agents default to enabled — D2).

    Examples:
        >>> from sevn.tools.base import ToolExecutor
        >>> exe = ToolExecutor()
        >>> register_subagent_spawn_tools(exe, None)
        >>> "spawn_subagent" in {d.name for d in exe.definitions()}
        True
    """
    subagents_cfg = workspace_config.subagents if workspace_config is not None else None
    if subagents_cfg is not None and not subagents_cfg.enabled:
        return
    executor.register(tool_from_decorated(spawn_subagent_tool))


__all__ = [
    "register_subagent_spawn_tools",
    "spawn_subagent_tool",
]
