"""Tier-B permission / budget / approval guardrails (D7/W8).

Extracts the parity-proven subset of ``tier_b_hooks`` — provision+permission gates,
counted-round budget enforcement, and human approval — into capability wrappers.
Steer and grounding remain sevn-owned hooks; harness ``InputGuardrail`` covers
prompt/output filtering only, not tool-access or round budgets.

Module: sevn.agent.adapters.tier_b_guardrails
Depends: pydantic_ai, sevn.agent.adapters.tier_b_hooks, sevn.agent.adapters.tool_approval_bridge

Exports:
    TierBPermissionGuardrail — ``before_tool_execute`` permission/provision gate.
    TierBRoundBudgetGuardrail — ``before_node_run`` counted-round cap.
    TierBApprovalGuardrail — human approval workflow bridge.
    TierBPermissionGuardrailCapability — capability wrapper for permission guard.
    TierBRoundBudgetGuardrailCapability — capability wrapper for budget guard.
    TierBApprovalGuardrailCapability — capability wrapper for approval guard.
    permission_guardrail — factory closed over ``TierBHookConfig``.
    round_budget_guardrail — factory closed over ``TierBHookConfig``.
    approval_guardrail — factory closed over ``TierBHookConfig``.
    build_tier_b_guardrail_capabilities — assemble all three guardrail capabilities.

Examples:
    >>> caps = build_tier_b_guardrail_capabilities()
    >>> [c.__class__.__name__ for c in caps]
    ['TierBPermissionGuardrailCapability', 'TierBRoundBudgetGuardrailCapability', 'TierBApprovalGuardrailCapability']
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic_ai._agent_graph import AgentNode, ModelRequestNode
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.exceptions import SkipToolExecution, UsageLimitExceeded
from pydantic_ai.tools import DeferredToolRequests, DeferredToolResults, ToolDefinition, ToolDenied

if TYPE_CHECKING:
    from pydantic_ai import RunContext
    from pydantic_ai.capabilities import ValidatedToolArgs
    from pydantic_ai.messages import ToolCallPart

    from sevn.agent.adapters.tier_b_hooks import TierBHookConfig
    from sevn.agent.adapters.tool_approval_bridge import ToolApprovalBridge

from sevn.agent.adapters.tier_b_hooks import (
    TierBHookConfig,
    check_permission_before_dispatch,
)
from sevn.agent.adapters.tool_approval_bridge import (
    ack_tool_on_deps,
    get_tool_approval_bridge,
    summarize_tool_args,
)
from sevn.agent.executors.b_types import BTierDeps
from sevn.tools.codes import ToolResultCode


def _approval_bridge(ctx: RunContext[BTierDeps]) -> ToolApprovalBridge | Any | None:
    """Return the per-run or process-wide approval bridge when wired.

    Args:
        ctx (RunContext[BTierDeps]): Pydantic AI run context.

    Returns:
        ToolApprovalBridge | Any | None: Bridge instance, or ``None`` when unwired.

    Examples:
        >>> _approval_bridge.__name__
        '_approval_bridge'
    """
    bridge = getattr(ctx.deps, "approval_bridge", None)
    if bridge is not None:
        return bridge
    return get_tool_approval_bridge()


@dataclass(frozen=True)
class TierBPermissionGuardrail:
    """Provision + permission + human-gate checks before tool execution."""

    config: TierBHookConfig

    async def check_tool_access(
        self,
        ctx: RunContext[BTierDeps],
        *,
        tool_name: str,
        args: dict[str, Any],
    ) -> None:
        """Raise ``SkipToolExecution`` when gates block ``tool_name``.

        Args:
            ctx (RunContext[BTierDeps]): Pydantic AI run context.
            tool_name (str): Candidate tool name.
            args (dict[str, Any]): Validated tool arguments.

        Raises:
            SkipToolExecution: When provision, permission, or human gates block the call.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TierBPermissionGuardrail.check_tool_access)
            True
        """
        _ = self.config
        denial = check_permission_before_dispatch(ctx.deps, tool_name, args=args)
        if denial is not None:
            blob = json.loads(denial)
            if (
                blob.get("code") == ToolResultCode.PLAN_HUMAN_GATE
                and _approval_bridge(ctx) is not None
            ):
                approved, deny_reason = await TierBApprovalGuardrail(self.config).resolve_approval(
                    ctx,
                    tool_name=tool_name,
                    args=args,
                )
                if not approved:
                    if deny_reason:
                        from sevn.tools.deny_rules import enveloped_deny_with_reason

                        raise SkipToolExecution(
                            enveloped_deny_with_reason(
                                tool_name=tool_name,
                                reason=deny_reason,
                            ),
                        )
                    raise SkipToolExecution(denial)
                denial = check_permission_before_dispatch(ctx.deps, tool_name, args=args)
            if denial is not None:
                raise SkipToolExecution(denial)


@dataclass(frozen=True)
class TierBRoundBudgetGuardrail:
    """Counted provider-round budget enforced at ``ModelRequestNode`` entry."""

    config: TierBHookConfig

    async def check_before_node(
        self,
        ctx: RunContext[BTierDeps],
        *,
        node: AgentNode[Any],
    ) -> AgentNode[Any]:
        """Raise ``UsageLimitExceeded`` when counted rounds reach ``max_rounds``.

        Args:
            ctx (RunContext[BTierDeps]): Pydantic AI run context.
            node (AgentNode[Any]): Agent graph node about to run.

        Returns:
            AgentNode[Any]: Unchanged node when under budget.

        Raises:
            UsageLimitExceeded: When ``provider_round_counter`` reached ``max_rounds``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TierBRoundBudgetGuardrail.check_before_node)
            True
        """
        _ = ctx
        if not isinstance(node, ModelRequestNode):
            return node
        if (
            self.config.max_rounds is not None
            and self.config.provider_round_counter[0] >= self.config.max_rounds
        ):
            msg = (
                f"tier-B counted-round budget exhausted (rounds={self.config.provider_round_counter[0]}, "
                f"max={self.config.max_rounds}, count_planning={self.config.count_planning})"
            )
            raise UsageLimitExceeded(msg)
        return node


@dataclass(frozen=True)
class TierBApprovalGuardrail:
    """Human approval workflow bridged to Mission Control."""

    config: TierBHookConfig

    async def resolve_approval(
        self,
        ctx: RunContext[BTierDeps],
        *,
        tool_name: str,
        args: dict[str, Any],
    ) -> tuple[bool, str | None]:
        """Block on operator approval for ``tool_name`` when required.

        Args:
            ctx (RunContext[BTierDeps]): Pydantic AI run context.
            tool_name (str): Registry tool name awaiting acknowledgement.
            args (dict[str, Any]): Validated tool arguments for the approval card.

        Returns:
            tuple[bool, str | None]: Approval flag and optional operator denial reason.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TierBApprovalGuardrail.resolve_approval)
            True
        """
        _ = self.config
        bridge = _approval_bridge(ctx)
        if bridge is None:
            return False, None
        tool_ctx = ctx.deps.effective_tool_context()
        if tool_name in tool_ctx.human_acknowledged_tools:
            return True, None
        await_fn = getattr(bridge, "await_approval", None)
        if await_fn is not None:
            approved = await await_fn(tool_name=tool_name, args=args)
            if approved:
                ack_tool_on_deps(ctx.deps, tool_name)
            return bool(approved), None
        verdict, deny_reason = await bridge.await_operator_verdict(
            session_id=tool_ctx.session_id,
            turn_id=tool_ctx.turn_id,
            tool_name=tool_name,
            args_summary=summarize_tool_args(args),
            trace=tool_ctx.trace,
        )
        if verdict == "deny":
            return False, deny_reason
        if verdict == "session":
            bridge.record_session_ack(tool_ctx.session_id, tool_name)
        ack_tool_on_deps(ctx.deps, tool_name)
        return True, None

    async def resolve(
        self,
        ctx: RunContext[BTierDeps],
        *,
        tool_name: str,
        args: dict[str, Any],
    ) -> ToolDenied | None:
        """Return a denial when operator approval is required but not granted.

        Args:
            ctx (RunContext[BTierDeps]): Pydantic AI run context.
            tool_name (str): Registry tool name awaiting acknowledgement.
            args (dict[str, Any]): Validated tool arguments for the approval card.

        Returns:
            ToolDenied | None: Denial when blocked; ``None`` when approved or already acked.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TierBApprovalGuardrail.resolve)
            True
        """
        approved, deny_reason = await self.resolve_approval(ctx, tool_name=tool_name, args=args)
        if approved:
            return None
        if deny_reason:
            message = deny_reason
        else:
            message = (
                f"Operator denied approval for `{tool_name}`. "
                "Revise the plan or choose a different approach."
            )
        return ToolDenied(message=message)


def permission_guardrail(config: TierBHookConfig) -> TierBPermissionGuardrail:
    """Build the tier-B permission guardrail closed over ``config``.

    Args:
        config (TierBHookConfig): Per-turn hook state.

    Returns:
        TierBPermissionGuardrail: Permission/provision gate guard.

    Examples:
        >>> guard = permission_guardrail(
        ...     TierBHookConfig(
        ...         provider_round_counter=[0],
        ...         max_rounds=3,
        ...         count_planning=False,
        ...         bound_tool_names=frozenset(),
        ...         triager_first_reply="",
        ...     )
        ... )
        >>> guard.__class__.__name__
        'TierBPermissionGuardrail'
    """
    return TierBPermissionGuardrail(config)


def round_budget_guardrail(config: TierBHookConfig) -> TierBRoundBudgetGuardrail:
    """Build the tier-B round-budget guardrail closed over ``config``.

    Args:
        config (TierBHookConfig): Per-turn hook state.

    Returns:
        TierBRoundBudgetGuardrail: Counted-round budget guard.

    Examples:
        >>> guard = round_budget_guardrail(
        ...     TierBHookConfig(
        ...         provider_round_counter=[0],
        ...         max_rounds=3,
        ...         count_planning=False,
        ...         bound_tool_names=frozenset(),
        ...         triager_first_reply="",
        ...     )
        ... )
        >>> guard.__class__.__name__
        'TierBRoundBudgetGuardrail'
    """
    return TierBRoundBudgetGuardrail(config)


def approval_guardrail(config: TierBHookConfig) -> TierBApprovalGuardrail:
    """Build the tier-B approval guardrail closed over ``config``.

    Args:
        config (TierBHookConfig): Per-turn hook state.

    Returns:
        TierBApprovalGuardrail: Human approval workflow guard.

    Examples:
        >>> guard = approval_guardrail(
        ...     TierBHookConfig(
        ...         provider_round_counter=[0],
        ...         max_rounds=3,
        ...         count_planning=False,
        ...         bound_tool_names=frozenset(),
        ...         triager_first_reply="",
        ...     )
        ... )
        >>> guard.__class__.__name__
        'TierBApprovalGuardrail'
    """
    return TierBApprovalGuardrail(config)


@dataclass
class TierBPermissionGuardrailCapability(AbstractCapability[BTierDeps]):
    """Capability wrapper for :class:`TierBPermissionGuardrail`."""

    guardrail: TierBPermissionGuardrail

    async def wrap_tool_execute(
        self,
        ctx: RunContext[BTierDeps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: ValidatedToolArgs,
        handler: Any,
    ) -> Any:
        """Enforce permission/provision gates before delegating to ``handler``.

        Args:
            ctx (RunContext[BTierDeps]): Pydantic AI run context.
            call (ToolCallPart): Model-requested tool invocation.
            tool_def (ToolDefinition): Prepared tool definition.
            args (ValidatedToolArgs): Schema-validated arguments.
            handler (Any): Inner tool execute handler.

        Returns:
            Any: Result from ``handler`` when gates pass.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TierBPermissionGuardrailCapability.wrap_tool_execute)
            True
        """
        _ = tool_def
        await self.guardrail.check_tool_access(ctx, tool_name=call.tool_name, args=dict(args))
        return await handler(args)


@dataclass
class TierBRoundBudgetGuardrailCapability(AbstractCapability[BTierDeps]):
    """Capability wrapper for :class:`TierBRoundBudgetGuardrail`."""

    guardrail: TierBRoundBudgetGuardrail

    async def before_node_run(
        self,
        ctx: RunContext[BTierDeps],
        *,
        node: AgentNode[BTierDeps],
    ) -> AgentNode[BTierDeps]:
        """Enforce counted-round budget before the node runs.

        Args:
            ctx (RunContext[BTierDeps]): Pydantic AI run context.
            node (AgentNode[BTierDeps]): Agent graph node about to run.

        Returns:
            AgentNode[BTierDeps]: Unchanged node when under budget.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TierBRoundBudgetGuardrailCapability.before_node_run)
            True
        """
        return await self.guardrail.check_before_node(ctx, node=node)


@dataclass
class TierBApprovalGuardrailCapability(AbstractCapability[BTierDeps]):
    """Capability wrapper for :class:`TierBApprovalGuardrail`."""

    guardrail: TierBApprovalGuardrail

    async def handle_deferred_tool_calls(
        self,
        ctx: RunContext[BTierDeps],
        *,
        requests: DeferredToolRequests,
    ) -> DeferredToolResults | None:
        """Bridge pydantic-ai deferred approvals to operator acknowledgement.

        Args:
            ctx (RunContext[BTierDeps]): Pydantic AI run context.
            requests (DeferredToolRequests): Approval deferrals from pydantic-ai.

        Returns:
            DeferredToolResults | None: Approval map keyed by ``tool_call_id``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TierBApprovalGuardrailCapability.handle_deferred_tool_calls)
            True
        """
        tool_ctx = ctx.deps.effective_tool_context()
        acked = tool_ctx.human_acknowledged_tools
        results = DeferredToolResults()
        for call in requests.approvals:
            if call.tool_name in acked:
                results.approvals[call.tool_call_id] = True
                continue
            denied = await self.guardrail.resolve(
                ctx,
                tool_name=call.tool_name,
                args=dict(call.args) if isinstance(call.args, dict) else {},
            )
            if denied is None:
                results.approvals[call.tool_call_id] = True
            else:
                results.approvals[call.tool_call_id] = denied
        return results


def build_tier_b_guardrail_capabilities(
    config: TierBHookConfig | None = None,
) -> list[AbstractCapability[BTierDeps]]:
    """Assemble permission, budget, and approval guardrail capabilities for tier-B.

    Args:
        config (TierBHookConfig | None): Per-turn hook state; ``None`` uses inventory defaults.

    Returns:
        list[AbstractCapability[BTierDeps]]: Three guardrail capabilities for ``Agent(...)``.

    Examples:
        >>> caps = build_tier_b_guardrail_capabilities()
        >>> len(caps)
        3
    """
    hook_config = config or TierBHookConfig(
        provider_round_counter=[0],
        max_rounds=None,
        count_planning=False,
        bound_tool_names=frozenset(),
        triager_first_reply="",
    )
    return [
        TierBPermissionGuardrailCapability(guardrail=permission_guardrail(hook_config)),
        TierBRoundBudgetGuardrailCapability(guardrail=round_budget_guardrail(hook_config)),
        TierBApprovalGuardrailCapability(guardrail=approval_guardrail(hook_config)),
    ]


__all__ = [
    "TierBApprovalGuardrail",
    "TierBApprovalGuardrailCapability",
    "TierBPermissionGuardrail",
    "TierBPermissionGuardrailCapability",
    "TierBRoundBudgetGuardrail",
    "TierBRoundBudgetGuardrailCapability",
    "approval_guardrail",
    "build_tier_b_guardrail_capabilities",
    "permission_guardrail",
    "round_budget_guardrail",
]
