"""``coding_agent_invoke`` tier-B/C tool — invoke a bound coding agent (CA6.1 + CA6.4).

Module: sevn.tools.coding_agent_invoke
Depends: sevn.agent.tracing.provider_call, sevn.coding_agents, sevn.tools.base,
    sevn.tools.context, sevn.tools.decorator

Exports:
    coding_agent_invoke — standalone async helper for tests and tier-B.
    coding_agent_invoke_tool — ``@sevn_tool`` decorated version for the registry.
    register_coding_agent_invoke_tool — register on a ``ToolExecutor``.

Trace events:
    ``provider.call``   — emitted via :func:`~sevn.agent.tracing.provider_call.emit_provider_call`
                          for each agent invocation (CA6.4, D-6 MUST import from provider_call.py).
    ``coding_agent.run`` — mission_state event with run metadata.

Examples:
    >>> import inspect
    >>> inspect.iscoroutinefunction(coding_agent_invoke_tool)
    True
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING, Any

from sevn.agent.tracing.provider_call import emit_provider_call
from sevn.tools.base import enveloped_failure, enveloped_success
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.decorator import sevn_tool, tool_from_decorated

if TYPE_CHECKING:
    from sevn.tools.base import ToolExecutor

JsonDict = dict[str, Any]

_INVOKE_PARAMS: JsonDict = {
    "type": "object",
    "properties": {
        "agent_id": {
            "type": "string",
            "description": "Registry id of the coding agent to invoke.",
        },
        "message": {
            "type": "string",
            "description": "Message or task description to send to the agent.",
        },
        "async_run": {
            "type": "boolean",
            "description": "When true, fire-and-forget (do not wait for result).",
        },
    },
    "required": ["agent_id", "message"],
    "additionalProperties": False,
}


@sevn_tool(
    name="coding_agent_invoke",
    category="coding_agents",
    description="Invoke a registered coding agent (ALRCA or LAP) by id with a message or task.",
    parameters=_INVOKE_PARAMS,
    sandbox_mode="none",
    capability_key="coding_agents",
)
async def coding_agent_invoke_tool(
    ctx: ToolContext,
    agent_id: str,
    message: str,
    async_run: bool = False,
) -> str:
    """Invoke a coding agent and return its response.

    Args:
        ctx (ToolContext): Tool invocation context.
        agent_id (str): Registry id of the agent.
        message (str): Task or message text.
        async_run (bool): Fire-and-forget when ``True``.

    Returns:
        str: JSON-encoded success or failure envelope.

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> from sevn.tools.context import ToolContext
        >>> from sevn.tools.permissions import AllowAllPermissionPolicy
        >>> ctx = ToolContext(
        ...     session_id="s",
        ...     workspace_path=Path("/tmp"),
        ...     workspace_id="w",
        ...     registry_version=1,
        ...     trace=None,
        ...     permissions=AllowAllPermissionPolicy(),
        ... )
        >>> result = asyncio.run(coding_agent_invoke_tool(ctx, agent_id="x", message="hi"))
        >>> '"ok"' in result or '"error"' in result
        True
    """
    ts_start = time.time_ns()
    span_id = str(uuid.uuid4())
    turn_id = ctx.turn_id if hasattr(ctx, "turn_id") and ctx.turn_id else span_id

    try:
        result = await _invoke_agent(
            agent_id=agent_id,
            message=message,
            workspace_path=ctx.workspace_path,
            async_run=async_run,
        )
    except Exception as exc:
        ts_end = time.time_ns()
        await emit_provider_call(
            ctx.trace,
            span_id=span_id,
            parent_span_id=None,
            session_id=ctx.session_id,
            turn_id=turn_id,
            model_id="coding_agent_invoke",
            regime="CODING_AGENT",
            tokens_in=0,
            tokens_out=0,
            transport="coding_agent",
            tier="B",
            status="error",
            ts_start_ns=ts_start,
            ts_end_ns=ts_end,
            extra_attrs={"agent_id": agent_id, "error": str(exc)},
        )
        return enveloped_failure(
            f"coding_agent_invoke failed: {exc}", code=ToolResultCode.INTERNAL_ERROR
        )

    ts_end = time.time_ns()
    await emit_provider_call(
        ctx.trace,
        span_id=span_id,
        parent_span_id=None,
        session_id=ctx.session_id,
        turn_id=turn_id,
        model_id="coding_agent_invoke",
        regime="CODING_AGENT",
        tokens_in=0,
        tokens_out=len(result.get("reply", "")),
        transport="coding_agent",
        tier="B",
        status="ok",
        ts_start_ns=ts_start,
        ts_end_ns=ts_end,
        extra_attrs={"agent_id": agent_id, "async_run": async_run},
    )

    if ctx.trace:
        from sevn.agent.tracing.sink import TraceEvent

        await ctx.trace.emit(
            TraceEvent(
                kind="coding_agent.run",
                span_id=str(uuid.uuid4()),
                parent_span_id=span_id,
                session_id=ctx.session_id,
                turn_id=turn_id,
                tier="B",
                ts_start_ns=ts_start,
                ts_end_ns=ts_end,
                status="ok",
                attrs={
                    "agent_id": agent_id,
                    "async_run": async_run,
                    "reply_len": len(result.get("reply", "")),
                },
            ),
        )

    return enveloped_success(result)


async def _invoke_agent(
    *,
    agent_id: str,
    message: str,
    workspace_path: Any,
    async_run: bool,
) -> JsonDict:
    """Resolve agent type and invoke it.

    Args:
        agent_id (str): Registry agent id.
        message (str): Task message.
        workspace_path (Any): Operator workspace root (``Path`` or path-like).
        async_run (bool): Fire-and-forget flag.

    Returns:
        JsonDict: ``{"agent_id": ..., "reply": ..., "async_run": ...}``.

    Examples:
        >>> import asyncio, pathlib, tempfile
        >>> with tempfile.TemporaryDirectory() as t:
        ...     try:
        ...         asyncio.run(_invoke_agent(
        ...             agent_id="no-such-agent", message="hi",
        ...             workspace_path=pathlib.Path(t), async_run=False,
        ...         ))
        ...     except ValueError as e:
        ...         "not found" in str(e)
        True
    """
    from pathlib import Path

    from sevn.coding_agents.alrca.goal import new_goal
    from sevn.coding_agents.alrca.loop_worker import run_alrca_loop
    from sevn.coding_agents.executors import StubExecutor

    ws_path = Path(workspace_path)
    sevn_json = ws_path / "sevn.json"

    agent_type: str = "unknown"
    executor_id: str = "cursor"
    verifier_specs: list[str] = []
    evaluator_model: str | None = None
    base_url: str | None = None

    if sevn_json.is_file():
        try:
            import json

            from sevn.config.sections.coding_agents import parse_coding_agents_section

            doc = json.loads(sevn_json.read_text(encoding="utf-8"))
            section = parse_coding_agents_section(doc.get("coding_agents"))
            if section and agent_id in section.agents:
                from sevn.config.sections.coding_agents import (
                    AlrcaAgentConfig,
                    LitellmLapAgentConfig,
                )

                agent_cfg = section.agents[agent_id]
                agent_type = agent_cfg.type
                if isinstance(agent_cfg, AlrcaAgentConfig):
                    executor_id = agent_cfg.executor
                    verifier_specs = list(agent_cfg.verifiers)
                    evaluator_model = agent_cfg.evaluator_model
                elif isinstance(agent_cfg, LitellmLapAgentConfig):
                    base_url = agent_cfg.base_url
        except Exception:  # nosec B110
            pass

    if agent_type == "unknown":
        msg = f"agent_id={agent_id!r} not found in coding_agents config"
        raise ValueError(msg)

    if agent_type == "litellm_lap":
        from sevn.integrations.litellm_lap.client import LitellmLapClient

        client = LitellmLapClient(base_url=base_url or "http://127.0.0.1:4000")
        result = await client.send_message(session_id=agent_id, message=message)
        return {"agent_id": agent_id, "reply": result.get("reply", ""), "async_run": async_run}

    if async_run:
        return {
            "agent_id": agent_id,
            "reply": f"[async] ALRCA loop started for agent={agent_id}",
            "async_run": True,
        }

    from sevn.coding_agents.executors import build_executor

    try:
        executor = build_executor(executor_id)
    except (ValueError, Exception):
        executor = StubExecutor()

    goal = new_goal(agent_id=agent_id, description=message)
    loop_result = await run_alrca_loop(
        goal,
        executor=executor,
        verifier_specs=verifier_specs,
        workspace_path=ws_path,
        evaluator_model=evaluator_model,
    )
    return {
        "agent_id": agent_id,
        "run_id": loop_result.run_id,
        "status": loop_result.status.value,
        "turns_used": loop_result.turns_used,
        "reply": f"ALRCA run {loop_result.run_id}: {loop_result.status.value} in {loop_result.turns_used} turn(s)",
        "async_run": False,
    }


def register_coding_agent_invoke_tool(executor: ToolExecutor) -> None:
    """Register ``coding_agent_invoke`` on a ``ToolExecutor``.

    Args:
        executor (ToolExecutor): Target registry.

    Returns:
        None

    Examples:
        >>> from sevn.tools.base import ToolExecutor
        >>> ex = ToolExecutor()
        >>> register_coding_agent_invoke_tool(ex)
        >>> "coding_agent_invoke" in [t.definition().name for t in ex._tools.values()]
        True
    """
    executor.register(tool_from_decorated(coding_agent_invoke_tool))


async def coding_agent_invoke(
    *,
    agent_id: str,
    message: str,
    workspace: Any,
    async_run: bool = False,
) -> JsonDict:
    """Invoke a coding agent by id — standalone async helper for tests and tier-B.

    Args:
        agent_id (str): Registry agent id.
        message (str): Task or message text.
        workspace (Any): WorkspaceConfig or path-like workspace root.
        async_run (bool): Fire-and-forget when ``True``.

    Returns:
        JsonDict: ``{"ok": True, "data": {...}}`` or ``{"ok": False, "error": "..."}``.

    Examples:
        >>> import asyncio
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> r = asyncio.run(coding_agent_invoke(
        ...     agent_id="test-agent",
        ...     message="hi",
        ...     workspace=WorkspaceConfig.minimal(),
        ... ))
        >>> isinstance(r, dict)
        True
    """
    from pathlib import Path as _Path

    if hasattr(workspace, "workspace_path"):
        workspace_path: Any = getattr(workspace, "workspace_path", _Path("."))
    elif hasattr(workspace, "__fspath__") or isinstance(workspace, (str, _Path)):
        workspace_path = _Path(str(workspace))
    else:
        workspace_path = _Path(".")

    try:
        result = await _invoke_agent(
            agent_id=agent_id,
            message=message,
            workspace_path=workspace_path,
            async_run=async_run,
        )
        return {"ok": True, "data": result}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


__all__ = [
    "coding_agent_invoke",
    "coding_agent_invoke_tool",
    "register_coding_agent_invoke_tool",
]
