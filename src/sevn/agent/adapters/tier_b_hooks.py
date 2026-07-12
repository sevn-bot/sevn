"""Tier-B pydantic-ai lifecycle hooks (`specs/14-executor-tier-b.md`; W5).

Maps sevn steer / grounding / permission / budget / approval concerns onto native
``Hooks`` so downstream waves extend :func:`build_tier_b_capabilities` instead of
the raw ``Agent(...)`` call.

Module: sevn.agent.adapters.tier_b_hooks
Depends: pydantic_ai, sevn.agent.grounding, sevn.tools.base

Exports:
    TierBHookConfig — per-turn hook state closed over by hook handlers.
    build_tier_b_hooks — construct the tier-B ``Hooks`` bundle.
    inject_owner_steer — ``before_model_request`` steer injection handler.
    enforce_round_budget — ``before_node_run`` round-cap handler.
    fetch_round_cap_after_model — ``after_model_request`` post-round-4 fetch steer (W5 / D9).
    grounding_guard_after_model — ``after_model_request`` grounding retry handler.
    permission_before_tool_execute — ``before_tool_execute`` permission gate.
    resolve_deferred_approvals — ``deferred_tool_calls`` approval bridge.
    await_human_tool_approval — MC W7 out-of-band ``requires_human`` wait.
    provision_denial_envelope — lazy-load / allowlist denial for ``SkipToolExecution``.
    apply_load_tool_grant — explicit allowlist grant + CodeMode steer after ``load_tool``.
    check_permission_before_dispatch — permission gate shared with hooks.

Examples:
    >>> cfg = TierBHookConfig(
    ...     provider_round_counter=[0],
    ...     max_rounds=3,
    ...     count_planning=False,
    ...     bound_tool_names=frozenset({"read"}),
    ...     triager_first_reply="",
    ... )
    >>> hooks = build_tier_b_hooks(cfg)
    >>> hooks.__class__.__name__
    'Hooks'
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from pydantic_ai._agent_graph import AgentNode, ModelRequestNode
from pydantic_ai.capabilities.hooks import Hooks
from pydantic_ai.exceptions import ModelRetry, SkipToolExecution, UsageLimitExceeded
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.tools import DeferredToolRequests, DeferredToolResults, ToolDefinition, ToolDenied

if TYPE_CHECKING:
    from pydantic_ai import RunContext
    from pydantic_ai.capabilities import ValidatedToolArgs
    from pydantic_ai.models import ModelRequestContext

    from sevn.agent.executors.b_types import BTierDeps

from sevn.agent.adapters.tier_b_capabilities import CODEMODE_LOCAL_WEB_TOOL_NAMES
from sevn.agent.adapters.tier_b_tools import (
    _ALWAYS_INVOKABLE_FILE_OPS,
    _ALWAYS_INVOKABLE_SKILL_RUNNERS,
    _ALWAYS_INVOKABLE_TIER_B,
)
from sevn.agent.adapters.tool_approval_bridge import (
    ack_tool_on_deps,
    get_tool_approval_bridge,
    summarize_tool_args,
)
from sevn.agent.grounding import (
    apply_audit_evidence_guard,
    apply_zero_tool_grounding_guard,
    claims_bound_tool_unavailable,
    claims_unattempted_tool_failure,
    steer_for_audit_evidence,
    steer_for_codemode_loaded_tool,
    steer_for_direct_tool_call,
    steer_for_false_tool_failure_claim,
    steer_for_summarize_after_fetch,
    tools_attempted_from_call_counts,
)
from sevn.agent.tracing.sink import checkpoint_snapshot
from sevn.logging.structured import debug_event, preview
from sevn.prompts.fallbacks import ASSISTANT_NO_OUTPUT_PLACEHOLDER
from sevn.tools.base import enveloped_failure
from sevn.tools.codes import ToolResultCode

_FETCH_ROUND_STEER_MIN_ROUND = 4
_GET_PAGE_CONTENT_TOOL = "get_page_content"


def _tool_call_debug_fields(call: ToolCallPart) -> dict[str, Any]:
    """Build optional debug fields for gateway logs on tool dispatch.

    Args:
        call (ToolCallPart): Model-requested tool invocation.

    Returns:
        dict[str, Any]: Extra ``debug_event`` kwargs (e.g. ``run_code`` code preview).

    Examples:
        >>> from pydantic_ai.messages import ToolCallPart
        >>> fields = _tool_call_debug_fields(
        ...     ToolCallPart(tool_name="run_code", args={"code": "await read()"}, tool_call_id="x"),
        ... )
        >>> fields["code_chars"]
        12
    """
    if call.tool_name != "run_code":
        return {}
    args = call.args
    code = ""
    if isinstance(args, dict):
        code = str(args.get("code") or "")
    elif isinstance(args, str):
        code = args
    return {"code_chars": len(code), "code_preview": preview(code, limit=160)}


def _tool_result_debug_fields(tool_name: str, result: object) -> dict[str, Any]:
    """Build optional debug fields for gateway logs after tool execution.

    Args:
        tool_name (str): Registry or capability tool name (logged by caller).
        result (object): Raw tool return payload.

    Returns:
        dict[str, Any]: Outcome label and short preview for ``debug_event``.

    Examples:
        >>> _tool_result_debug_fields("read", '{"ok":true}')["outcome"]
        'ok'
    """
    _ = tool_name
    # Unwrap CodeMode ``ToolReturn`` so the logged outcome reflects the real envelope (ok/error)
    # rather than ``parse_error``/``text`` on the wrapper repr (transcript-review-2026-06-22).
    from sevn.agent.adapters.tier_b_overflow import _unwrap_tool_return

    unwrapped, _was_tool_return = _unwrap_tool_return(result)
    outcome = "text"
    if isinstance(unwrapped, str):
        try:
            blob = json.loads(unwrapped)
            outcome = "ok" if blob.get("ok") else "error"
        except json.JSONDecodeError:
            outcome = "parse_error"
        return {
            "outcome": outcome,
            "result_preview": preview(unwrapped, limit=200),
        }
    return {"outcome": outcome, "result_preview": preview(str(unwrapped), limit=200)}


def _tool_checkpoint_state(call: ToolCallPart, args: object) -> dict[str, object]:
    """Build full checkpoint ``state`` for ``tool.before`` trace rows.

    Args:
        call (ToolCallPart): Model-requested tool invocation.
        args (object): Validated tool arguments from pydantic-ai.

    Returns:
        dict[str, object]: Tool name and argument mapping for traces.

    Examples:
        >>> from pydantic_ai.messages import ToolCallPart
        >>> st = _tool_checkpoint_state(
        ...     ToolCallPart(tool_name="read", args={"path": "x"}, tool_call_id="1"),
        ...     {"path": "x"},
        ... )
        >>> st["name"]
        'read'
    """
    from sevn.agent.tracing.attrs import json_safe_trace_attrs

    arguments: object
    if isinstance(args, dict):
        arguments = json_safe_trace_attrs(args)
    elif callable(getattr(args, "model_dump", None)):
        arguments = cast("Any", args).model_dump(mode="json")
    elif isinstance(call.args, dict):
        arguments = json_safe_trace_attrs(call.args)
    else:
        arguments = call.args
    return {"name": call.tool_name, "arguments": arguments}


def _tool_result_checkpoint_state(
    tool_name: str,
    result: object,
    fields: dict[str, Any],
) -> dict[str, object]:
    """Build full checkpoint ``state`` for ``tool.after`` trace rows.

    Args:
        tool_name (str): Registry tool name.
        result (object): Raw tool return payload.
        fields (dict[str, Any]): Debug fields from :func:`_tool_result_debug_fields`.

    Returns:
        dict[str, object]: Tool name, outcome, and parsed result for traces.

    Examples:
        >>> st = _tool_result_checkpoint_state("read", '{"ok":true}', {"outcome": "ok"})
        >>> st["name"]
        'read'
    """
    from sevn.agent.tracing.attrs import json_safe_trace_value, trace_tool_result_value

    state: dict[str, object] = {
        "name": tool_name,
        "outcome": fields.get("outcome", "unknown"),
    }
    if isinstance(result, str):
        state["result"] = trace_tool_result_value(result)
    else:
        state["result"] = json_safe_trace_value(result)
    return state


@dataclass(frozen=True)
class TierBHookConfig:
    """Per-turn values shared by tier-B hook handlers."""

    provider_round_counter: list[int]
    max_rounds: int | None
    count_planning: bool
    bound_tool_names: frozenset[str]
    triager_first_reply: str


def provision_denial_envelope(deps: BTierDeps, tool_name: str) -> str | None:
    """Return a denial envelope when ``tool_name`` is not provisioned this turn.

    Args:
        deps (BTierDeps): Per-run dependency bag.
        tool_name (str): Candidate tool name.

    Returns:
        str | None: Raw failure envelope when not provisioned; ``None`` when allowed.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.agent.executors.b_types import BTierDeps
        >>> from sevn.tools.base import ToolExecutor
        >>> from sevn.tools.context import ToolContext
        >>> from sevn.tools.permissions import AllowAllPermissionPolicy
        >>> deps = BTierDeps(
        ...     tool_executor=ToolExecutor(),
        ...     tool_context_template=ToolContext(
        ...         session_id="s",
        ...         workspace_path=Path("/tmp"),
        ...         workspace_id="w",
        ...         registry_version=1,
        ...         trace=None,
        ...         permissions=AllowAllPermissionPolicy(),
        ...     ),
        ...     workspace_path=Path("/tmp"),
        ...     registry_version=1,
        ... )
        >>> provision_denial_envelope(deps, "serp") is not None
        True
        >>> _ = deps.loaded_tools.add("serp")
        >>> provision_denial_envelope(deps, "serp") is None
        True
    """
    if (
        tool_name in deps.meta_tool_names
        or tool_name in _ALWAYS_INVOKABLE_SKILL_RUNNERS
        or tool_name in _ALWAYS_INVOKABLE_FILE_OPS
        or tool_name in _ALWAYS_INVOKABLE_TIER_B
        or tool_name in deps.loaded_tools
    ):
        return None
    allow = deps.tool_allowlist.effective if deps.tool_allowlist is not None else frozenset()
    if tool_name in allow:
        return None
    return enveloped_failure(
        f"Tool {tool_name!r} is not provisioned this turn "
        f"(TOOL_NOT_PROVISIONED). Call load_tool or use an available tool.",
        code=ToolResultCode.TOOL_NOT_PROVISIONED,
    )


def apply_load_tool_grant(deps: BTierDeps, loaded_name: str) -> None:
    """Grant an allowlisted tool after successful ``load_tool`` dispatch (W7 / D11).

    Adds ``loaded_name`` to :class:`MutableToolAllowlist` ``extra`` (bypassing CodeMode
    web auto-grant blocks) and steers web tools toward ``run_code`` when CodeMode is on.

    Args:
        deps (BTierDeps): Per-run dependency bag.
        loaded_name (str): Registry tool name passed to ``load_tool(name=…)``.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.agent.adapters.tool_part_filter import MutableToolAllowlist
        >>> from sevn.agent.executors.b_types import BTierDeps
        >>> from sevn.tools.base import ToolExecutor
        >>> from sevn.tools.context import ToolContext
        >>> from sevn.tools.permissions import AllowAllPermissionPolicy
        >>> allow = MutableToolAllowlist(
        ...     base=frozenset({"load_tool"}),
        ...     registry_names=frozenset({"load_tool", "glob"}),
        ... )
        >>> deps = BTierDeps(
        ...     tool_executor=ToolExecutor(),
        ...     tool_context_template=ToolContext(
        ...         session_id="s",
        ...         workspace_path=Path("/tmp"),
        ...         workspace_id="w",
        ...         registry_version=1,
        ...         trace=None,
        ...         permissions=AllowAllPermissionPolicy(),
        ...     ),
        ...     workspace_path=Path("/tmp"),
        ...     registry_version=1,
        ...     tool_allowlist=allow,
        ... )
        >>> apply_load_tool_grant(deps, "glob")
        >>> "glob" in allow.effective
        True
    """
    allowlist = deps.tool_allowlist
    if allowlist is None:
        return
    if not allowlist.grant_load_tool(loaded_name):
        return
    debug_event("tier_b.load_tool_granted", name=loaded_name)
    if allowlist.codemode_blocks_web_autogrants and loaded_name in CODEMODE_LOCAL_WEB_TOOL_NAMES:
        steer = deps.steer_buffer
        if steer is not None:
            steer.inject_pending(steer_for_codemode_loaded_tool(loaded_name))


def check_permission_before_dispatch(deps: BTierDeps, tool_name: str) -> str | None:
    """Return a denial envelope when permission or human gates block ``tool_name``.

    Args:
        deps (BTierDeps): Per-run dependency bag.
        tool_name (str): Candidate tool name.

    Returns:
        str | None: Raw failure envelope when blocked; ``None`` when allowed.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.agent.executors.b_types import BTierDeps
        >>> from sevn.tools.base import ToolDefinition, FunctionTool, ToolExecutor
        >>> from sevn.tools.context import ToolContext
        >>> from sevn.tools.permissions import AllowAllPermissionPolicy
        >>> exe = ToolExecutor()
        >>> exe.register(
        ...     FunctionTool(
        ...         ToolDefinition(
        ...             name="delete",
        ...             category="file",
        ...             description="delete",
        ...             parameters={"type": "object", "properties": {}},
        ...             requires_human=True,
        ...         ),
        ...         lambda _ctx: "{}",
        ...     )
        ... )
        >>> deps = BTierDeps(
        ...     tool_executor=exe,
        ...     tool_context_template=ToolContext(
        ...         session_id="s",
        ...         workspace_path=Path("/tmp"),
        ...         workspace_id="w",
        ...         registry_version=1,
        ...         trace=None,
        ...         permissions=AllowAllPermissionPolicy(),
        ...     ),
        ...     workspace_path=Path("/tmp"),
        ...     registry_version=1,
        ... )
        >>> check_permission_before_dispatch(deps, "delete") is not None
        True
    """
    denial = provision_denial_envelope(deps, tool_name)
    if denial is not None:
        return denial
    tool_ctx = deps.effective_tool_context()
    permission_gate = tool_ctx.permissions
    if permission_gate is not None and not permission_gate.may_invoke(tool_name):
        return enveloped_failure(
            "Permission denied for tool invocation",
            code=ToolResultCode.PERMISSION_DENIED,
        )
    definition = deps.tool_executor.snapshot_definition(tool_name)
    if definition is None:
        return None
    if definition.requires_human and tool_name not in tool_ctx.human_acknowledged_tools:
        return enveloped_failure(
            "requires_human gate not acknowledged for this turn",
            code=ToolResultCode.PLAN_HUMAN_GATE,
        )
    return None


def _text_from_model_response(response: ModelResponse) -> str:
    """Join ``TextPart`` bodies from one ``ModelResponse``.

    Args:
        response (ModelResponse): Single assistant model response.

    Returns:
        str: Concatenated text parts, or ``""`` when none.

    Examples:
        >>> from pydantic_ai.messages import ModelResponse, TextPart
        >>> _text_from_model_response(ModelResponse(parts=[TextPart(content="hi")]))
        'hi'
    """
    parts: list[str] = []
    for part in response.parts:
        if isinstance(part, TextPart):
            parts.append(part.content)
    return "\n".join(parts)


async def inject_owner_steer(
    ctx: RunContext[BTierDeps],
    request_context: ModelRequestContext,
) -> ModelRequestContext:
    """Append buffered ``/steer`` text before the next model request (W5.3).

    Args:
        ctx (RunContext[BTierDeps]): Pydantic AI run context.
        request_context (ModelRequestContext): Outbound model request context.

    Returns:
        ModelRequestContext: Possibly-mutated request context with steer appended.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(inject_owner_steer)
        True
    """
    steer = ctx.deps.steer_buffer
    if steer is None:
        return request_context
    pending = steer.pop_pending()
    if not pending:
        return request_context
    from sevn.agent.adapters.tier_b_model import append_owner_steer_model_request

    request_context.messages = append_owner_steer_model_request(
        list(request_context.messages),
        pending,
    )
    return request_context


async def enforce_round_budget(
    config: TierBHookConfig,
    ctx: RunContext[BTierDeps],
    *,
    node: AgentNode[Any],
) -> AgentNode[Any]:
    """Raise ``UsageLimitExceeded`` when counted rounds reach ``max_rounds`` (W5.3).

    Args:
        config (TierBHookConfig): Per-turn hook state including the round counter.
        ctx (RunContext[BTierDeps]): Pydantic AI run context.
        node (AgentNode[Any]): Agent graph node about to run.

    Returns:
        AgentNode[Any]: Unchanged node when under budget.

    Raises:
        UsageLimitExceeded: When ``provider_round_counter`` reached ``max_rounds``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(enforce_round_budget)
        True
    """
    _ = ctx
    if not isinstance(node, ModelRequestNode):
        return node
    if config.max_rounds is not None and config.provider_round_counter[0] >= config.max_rounds:
        msg = (
            f"tier-B counted-round budget exhausted (rounds={config.provider_round_counter[0]}, "
            f"max={config.max_rounds}, count_planning={config.count_planning})"
        )
        raise UsageLimitExceeded(msg)
    return node


def _turn_has_deliverable_user_text(deps: BTierDeps, response_text: str) -> bool:
    """Return whether this turn already produced user-visible text worth keeping.

    Args:
        deps (BTierDeps): Per-run dependency bag (tool ``channel_payloads``).
        response_text (str): Latest assistant text from the model response.

    Returns:
        bool: ``True`` when channel payloads exist or response text is deliverable.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.agent.executors.b_types import BTierDeps
        >>> from sevn.tools.base import ToolExecutor
        >>> from sevn.tools.context import ToolContext
        >>> from sevn.tools.permissions import AllowAllPermissionPolicy
        >>> deps = BTierDeps(
        ...     tool_executor=ToolExecutor(),
        ...     tool_context_template=ToolContext(
        ...         session_id="s",
        ...         workspace_path=Path("/tmp"),
        ...         workspace_id="w",
        ...         registry_version=1,
        ...         trace=None,
        ...         permissions=AllowAllPermissionPolicy(),
        ...     ),
        ...     workspace_path=Path("/tmp"),
        ...     registry_version=1,
        ... )
        >>> _turn_has_deliverable_user_text(deps, "Here are five headlines.")
        True
        >>> _turn_has_deliverable_user_text(deps, "")
        False
    """
    if deps.channel_payloads:
        return True
    stripped = response_text.strip()
    return bool(stripped) and stripped != ASSISTANT_NO_OUTPUT_PLACEHOLDER


def fetch_round_cap_after_model(
    config: TierBHookConfig,
    ctx: RunContext[BTierDeps],
    response: ModelResponse,
) -> None:
    """Inject summarize steer once when fetch rounds accumulate without an answer (W5 / D9).

    Args:
        config (TierBHookConfig): Per-turn hook state including the round counter.
        ctx (RunContext[BTierDeps]): Pydantic AI run context.
        response (ModelResponse): Latest assistant response from the provider.

    Examples:
        >>> from pathlib import Path
        >>> from unittest.mock import MagicMock
        >>> from pydantic_ai import RunContext
        >>> from pydantic_ai.messages import ModelResponse, TextPart
        >>> from pydantic_ai.usage import RunUsage
        >>> from sevn.agent.executors.b_types import BTierDeps, SteerInject
        >>> from sevn.tools.base import ToolExecutor
        >>> from sevn.tools.context import ToolContext
        >>> from sevn.tools.permissions import AllowAllPermissionPolicy
        >>> steer = SteerInject()
        >>> deps = BTierDeps(
        ...     tool_executor=ToolExecutor(),
        ...     tool_context_template=ToolContext(
        ...         session_id="s",
        ...         workspace_path=Path("/tmp"),
        ...         workspace_id="w",
        ...         registry_version=1,
        ...         trace=None,
        ...         permissions=AllowAllPermissionPolicy(),
        ...     ),
        ...     workspace_path=Path("/tmp"),
        ...     registry_version=1,
        ...     steer_buffer=steer,
        ... )
        >>> deps.successful_tools_called.add("get_page_content")
        >>> cfg = TierBHookConfig(
        ...     provider_round_counter=[4],
        ...     max_rounds=10,
        ...     count_planning=False,
        ...     bound_tool_names=frozenset(),
        ...     triager_first_reply="",
        ... )
        >>> ctx = RunContext(deps=deps, model=MagicMock(), usage=RunUsage())
        >>> fetch_round_cap_after_model(
        ...     cfg,
        ...     ctx,
        ...     ModelResponse(parts=[TextPart(content="")]),
        ... )
        >>> deps.fetch_round_steer_injected
        True
    """
    deps = ctx.deps
    if deps.fetch_round_steer_injected:
        return
    if config.provider_round_counter[0] < _FETCH_ROUND_STEER_MIN_ROUND:
        return
    if _GET_PAGE_CONTENT_TOOL not in deps.successful_tools_called:
        return
    text = _text_from_model_response(response)
    if _turn_has_deliverable_user_text(deps, text):
        return
    steer = deps.steer_buffer
    if steer is None:
        return
    deps.fetch_round_steer_injected = True
    steer.inject_pending(
        steer_for_summarize_after_fetch(frozenset(deps.successful_tools_called)),
    )
    debug_event(
        "tier_b.fetch_round_steer",
        round=config.provider_round_counter[0],
        tools=sorted(deps.successful_tools_called),
    )


async def grounding_guard_after_model(
    config: TierBHookConfig,
    ctx: RunContext[BTierDeps],
    response: ModelResponse,
) -> ModelResponse:
    """Retry when outbound text claims unavailable tools or ungrounded paths (W5.3).

    Args:
        config (TierBHookConfig): Per-turn hook state including bound tool names.
        ctx (RunContext[BTierDeps]): Pydantic AI run context.
        response (ModelResponse): Latest assistant response from the provider.

    Returns:
        ModelResponse: Unchanged response when no guard applies.

    Raises:
        ModelRetry: When the model must ground or stop claiming tools unavailable.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(grounding_guard_after_model)
        True
    """
    fetch_round_cap_after_model(config, ctx, response)
    text = _text_from_model_response(response)
    if not text.strip():
        return response
    unavailable = claims_bound_tool_unavailable(text, config.bound_tool_names)
    if unavailable and unavailable not in ctx.deps.grounding_tools_called:
        steer = ctx.deps.steer_buffer
        if steer is not None:
            steer.inject_pending(steer_for_direct_tool_call(unavailable))
        budget = config.max_rounds
        rounds_used = config.provider_round_counter[0]
        if budget is None or rounds_used + 1 < budget:
            raise ModelRetry(
                f"Do not claim `{unavailable}` is unavailable — it is bound this turn. "
                "Call it directly or explain a concrete blocker.",
            )
        return response
    guarded, applied = apply_zero_tool_grounding_guard(
        text,
        grounding_tools_called=frozenset(ctx.deps.grounding_tools_called),
    )
    if applied and guarded != text:
        raise ModelRetry(
            "Ground your answer in tool output (read/glob/search/web) before asserting "
            "code paths or tool provenance.",
        )
    successful_tools = frozenset(ctx.deps.successful_tools_called)
    attempted = tools_attempted_from_call_counts(ctx.deps.tool_call_counts)
    _audit_guarded, audit_applied = apply_audit_evidence_guard(
        text,
        successful_tools=successful_tools,
        codemode_bound_tools_called=frozenset(ctx.deps.codemode_bound_tools_called),
        tools_attempted=attempted,
    )
    if audit_applied:
        steer = ctx.deps.steer_buffer
        if steer is not None:
            if claims_unattempted_tool_failure(text, tools_attempted=attempted):
                steer.inject_pending(steer_for_false_tool_failure_claim())
            else:
                steer.inject_pending(steer_for_audit_evidence())
        budget = config.max_rounds
        rounds_used = config.provider_round_counter[0]
        if budget is None or rounds_used + 1 < budget:
            raise ModelRetry(
                "Tool evidence succeeded this turn — summarize findings instead of "
                "claiming fabrication or replay-stub failure."
                if not claims_unattempted_tool_failure(text, tools_attempted=attempted)
                else (
                    "Do not claim load_tool or registry tool failure without dispatch "
                    "evidence — use read_transcript and log_query first."
                ),
            )
    return response


async def await_human_tool_approval(
    ctx: RunContext[BTierDeps],
    *,
    tool_name: str,
    args: dict[str, Any],
) -> bool:
    """Block on Mission Control until the operator approves or denies ``tool_name``.

    Args:
        ctx (RunContext[BTierDeps]): Pydantic AI run context.
        tool_name (str): Registry tool name awaiting acknowledgement.
        args (dict[str, Any]): Validated tool arguments for the approval card.

    Returns:
        bool: ``True`` when the operator approved (once/session/always); ``False`` on deny/timeout.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(await_human_tool_approval)
        True
    """
    bridge = get_tool_approval_bridge()
    if bridge is None:
        return False
    tool_ctx = ctx.deps.effective_tool_context()
    if tool_name in tool_ctx.human_acknowledged_tools:
        return True
    verdict = await bridge.await_operator_verdict(
        session_id=tool_ctx.session_id,
        turn_id=tool_ctx.turn_id,
        tool_name=tool_name,
        args_summary=summarize_tool_args(args),
        trace=tool_ctx.trace,
    )
    if verdict == "deny":
        return False
    if verdict == "session":
        bridge.record_session_ack(tool_ctx.session_id, tool_name)
    ack_tool_on_deps(ctx.deps, tool_name)
    return True


async def permission_before_tool_execute(
    ctx: RunContext[BTierDeps],
    *,
    call: ToolCallPart,
    tool_def: ToolDefinition,
    args: ValidatedToolArgs,
) -> ValidatedToolArgs:
    """Deny tool execution via ``SkipToolExecution`` when gates fail (W5.3).

    Args:
        ctx (RunContext[BTierDeps]): Pydantic AI run context.
        call (ToolCallPart): Tool invocation the model requested.
        tool_def (ToolDefinition): Prepared tool definition.
        args (ValidatedToolArgs): Schema-validated arguments.

    Returns:
        ValidatedToolArgs: Unmodified args when execution may proceed.

    Raises:
        SkipToolExecution: When provision, permission, or human gates block the call.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(permission_before_tool_execute)
        True
    """
    _ = tool_def
    denial = check_permission_before_dispatch(ctx.deps, call.tool_name)
    if denial is not None:
        blob = json.loads(denial)
        if (
            blob.get("code") == ToolResultCode.PLAN_HUMAN_GATE
            and get_tool_approval_bridge() is not None
        ):
            approved = await await_human_tool_approval(
                ctx,
                tool_name=call.tool_name,
                args=dict(args),
            )
            if not approved:
                raise SkipToolExecution(denial)
            denial = check_permission_before_dispatch(ctx.deps, call.tool_name)
        if denial is not None:
            raise SkipToolExecution(denial)
    return args


async def resolve_deferred_approvals(
    ctx: RunContext[BTierDeps],
    *,
    requests: DeferredToolRequests,
) -> DeferredToolResults:
    """Bridge pydantic-ai deferred approvals to ``human_acknowledged_tools`` (W5.4).

    Args:
        ctx (RunContext[BTierDeps]): Pydantic AI run context.
        requests (DeferredToolRequests): Approval and external-call deferrals.

    Returns:
        DeferredToolResults: Approval map keyed by ``tool_call_id``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(resolve_deferred_approvals)
        True
    """
    tool_ctx = ctx.deps.effective_tool_context()
    acked = tool_ctx.human_acknowledged_tools
    results = DeferredToolResults()
    bridge = get_tool_approval_bridge()
    for call in requests.approvals:
        if call.tool_name in acked:
            results.approvals[call.tool_call_id] = True
            continue
        if bridge is not None:
            approved = await await_human_tool_approval(
                ctx,
                tool_name=call.tool_name,
                args=dict(call.args) if isinstance(call.args, dict) else {},
            )
            if approved:
                results.approvals[call.tool_call_id] = True
                continue
        results.approvals[call.tool_call_id] = ToolDenied(
            message=(
                f"Human approval required before `{call.tool_name}` can run. "
                "Acknowledge the destructive action, then retry."
            ),
        )
    return results


def build_tier_b_hooks(config: TierBHookConfig) -> Hooks:
    """Construct tier-B lifecycle hooks closed over ``config``.

    Args:
        config (TierBHookConfig): Per-turn hook state (budget counter, allowlists, …).

    Returns:
        Hooks: Capability bundle for ``Agent(capabilities=[...])``.

    Examples:
        >>> cfg = TierBHookConfig(
        ...     provider_round_counter=[0],
        ...     max_rounds=2,
        ...     count_planning=False,
        ...     bound_tool_names=frozenset(),
        ...     triager_first_reply="",
        ... )
        >>> build_tier_b_hooks(cfg).__class__.__name__
        'Hooks'
    """
    hooks = Hooks()

    @hooks.on.before_model_request
    async def _inject_owner_steer(
        ctx: RunContext[BTierDeps],
        request_context: ModelRequestContext,
    ) -> ModelRequestContext:
        return await inject_owner_steer(ctx, request_context)

    @hooks.on.before_node_run
    async def _enforce_round_budget(
        ctx: RunContext[BTierDeps],
        *,
        node: AgentNode[Any],
    ) -> AgentNode[Any]:
        return await enforce_round_budget(config, ctx, node=node)

    @hooks.on.after_model_request
    async def _grounding_guard_retry(
        ctx: RunContext[BTierDeps],
        *,
        request_context: ModelRequestContext,
        response: ModelResponse,
    ) -> ModelResponse:
        _ = request_context
        return await grounding_guard_after_model(config, ctx, response)

    @hooks.on.before_tool_execute
    async def _permission_and_provision_gate(
        ctx: RunContext[BTierDeps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: ValidatedToolArgs,
    ) -> ValidatedToolArgs:
        return await permission_before_tool_execute(ctx, call=call, tool_def=tool_def, args=args)

    @hooks.on.before_tool_execute
    async def trace_tool_before(
        ctx: RunContext[BTierDeps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: ValidatedToolArgs,
    ) -> ValidatedToolArgs:
        _ = tool_def
        _ = args
        tool_ctx = ctx.deps.effective_tool_context()
        await checkpoint_snapshot(
            tool_ctx.trace,
            session_id=tool_ctx.session_id,
            turn_id=tool_ctx.turn_id,
            tier="B",
            kind="tool.before",
            excerpt=f"name={call.tool_name}",
            state=_tool_checkpoint_state(call, args),
        )
        debug_event(
            "tier_b.tool_dispatch",
            session_id=tool_ctx.session_id,
            turn_id=tool_ctx.turn_id,
            tool_name=call.tool_name,
            **_tool_call_debug_fields(call),
        )
        return args

    @hooks.on.after_tool_execute
    async def trace_tool_after(
        ctx: RunContext[BTierDeps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: ValidatedToolArgs,
        result: object,
    ) -> object:
        _ = tool_def
        _ = args
        tool_ctx = ctx.deps.effective_tool_context()
        fields = _tool_result_debug_fields(call.tool_name, result)
        await checkpoint_snapshot(
            tool_ctx.trace,
            session_id=tool_ctx.session_id,
            turn_id=tool_ctx.turn_id,
            tier="B",
            kind="tool.after",
            excerpt=f"name={call.tool_name} outcome={fields.get('outcome', 'unknown')}",
            state=_tool_result_checkpoint_state(call.tool_name, result, fields),
        )
        debug_event(
            "tier_b.tool_result",
            session_id=tool_ctx.session_id,
            turn_id=tool_ctx.turn_id,
            tool_name=call.tool_name,
            **fields,
        )
        return result

    @hooks.on.deferred_tool_calls
    async def _bridge_human_approval(
        ctx: RunContext[BTierDeps],
        *,
        requests: DeferredToolRequests,
    ) -> DeferredToolResults:
        return await resolve_deferred_approvals(ctx, requests=requests)

    return hooks


__all__ = [
    "TierBHookConfig",
    "apply_load_tool_grant",
    "await_human_tool_approval",
    "build_tier_b_hooks",
    "check_permission_before_dispatch",
    "enforce_round_budget",
    "fetch_round_cap_after_model",
    "grounding_guard_after_model",
    "inject_owner_steer",
    "permission_before_tool_execute",
    "provision_denial_envelope",
    "resolve_deferred_approvals",
]
