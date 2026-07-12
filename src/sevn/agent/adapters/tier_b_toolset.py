"""Registry-backed pydantic-ai toolset for tier B (`specs/14-executor-tier-b.md` §2.2).

Every tool call re-enters :meth:`sevn.tools.base.ToolExecutor.dispatch` via the
``Tool`` runners built in :mod:`sevn.agent.adapters.tier_b_tools`.

Module: sevn.agent.adapters.tier_b_toolset
Depends: pydantic_ai, sevn.agent.adapters.tier_b_tools, sevn.tools.base

Exports:
    SevnRegistryToolset — ``AbstractToolset`` over the live registry snapshot.
    bound_tools_only_first_round — first-round tool-exposure filter (all providers).

Examples:
    >>> from sevn.tools.base import ToolExecutor
    >>> from sevn.agent.adapters.pydantic_adapter import PydanticToolRegistration
    >>> ts = SevnRegistryToolset.from_registry(
    ...     ToolExecutor(),
    ...     PydanticToolRegistration((), {}, (), {}),
    ... )
    >>> ts.id
    'sevn_registry'
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai.toolsets import FunctionToolset

from sevn.agent.adapters.tier_b_codemode import compute_codemode_eligible_names
from sevn.agent.adapters.tier_b_tools import build_pydantic_tools_for_registry
from sevn.agent.executors.b_types import BTierDeps

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic_ai import Tool
    from pydantic_ai.tools import RunContext, ToolDefinition

    from sevn.agent.adapters.pydantic_adapter import PydanticToolRegistration
    from sevn.agent.adapters.tier_b_capabilities import WebEgressDomainPolicy
    from sevn.tools.base import ToolExecutor


def bound_tools_only_first_round(
    allowed: frozenset[str],
) -> Callable[[RunContext[BTierDeps], ToolDefinition], bool]:
    """Return a toolset filter that limits the FIRST tier-B round to ``allowed``.

    Applied via :meth:`FunctionToolset.filtered`, this hides every tool whose name
    is not in ``allowed`` (the triager-bound set) from the model on its first
    request (``run_step == 1``); from the second round onward the full toolset is
    exposed again. Because it runs at the toolset layer — before any provider wire
    format — it enforces the bound toolset for **every** model/provider, keeping a
    model from wandering into always-on meta tools (``run_skill_script``,
    ``run_code``, ``list_registry`` …) instead of the tool it was given.

    Args:
        allowed (frozenset[str]): Tool names callable on the first round
            (typically ``bound_tool_names`` — triager picks + ``request_escalation``
            + ``run_code`` when CodeMode is on).

    Returns:
        Callable[[RunContext[BTierDeps], ToolDefinition], bool]: Filter predicate.

    Examples:
        >>> from types import SimpleNamespace
        >>> f = bound_tools_only_first_round(frozenset({"serp"}))
        >>> f(SimpleNamespace(run_step=1), SimpleNamespace(name="serp"))
        True
        >>> f(SimpleNamespace(run_step=1), SimpleNamespace(name="load_tool"))
        False
        >>> f(SimpleNamespace(run_step=2), SimpleNamespace(name="load_tool"))
        True
    """

    def _filter(ctx: RunContext[BTierDeps], tool_def: ToolDefinition) -> bool:
        if ctx.run_step > 1:
            return True
        return tool_def.name in allowed

    return _filter


class SevnRegistryToolset(FunctionToolset[BTierDeps]):
    """Live registry toolset whose runners always call ``ToolExecutor.dispatch``.

    Approval-gated registry tools (``requires_human=True``) are exposed with
    ``requires_approval=True`` so pydantic-ai routes them through
    ``deferred_tool_calls`` hooks.
    """

    @classmethod
    def from_registry(
        cls,
        executor: ToolExecutor,
        registration: PydanticToolRegistration,
        *,
        extra_tools: list[Tool[BTierDeps]] | None = None,
        codemode_enabled: bool = False,
        triager_tools: frozenset[str] | None = None,
        triager_skills: frozenset[str] | None = None,
        exclude_tool_names: frozenset[str] | None = None,
        codemode_web_policy: WebEgressDomainPolicy | None = None,
    ) -> SevnRegistryToolset:
        """Build a registry toolset for one tier-B turn.

        Args:
            executor (ToolExecutor): Active registry whose definitions back the tools.
            registration (PydanticToolRegistration): Triager-chosen names (ordering anchor).
            extra_tools (list[Tool[BTierDeps]] | None): Native tools appended after registry
                rows (e.g. ``request_escalation``).
            codemode_enabled (bool): When ``True``, tag triager-scoped tools for ``CodeMode`` (W8).
            triager_tools (frozenset[str] | None): ``triage.tools[]`` for metadata scoping.
            triager_skills (frozenset[str] | None): ``triage.skills[]`` for skill-runner scoping.
            exclude_tool_names (frozenset[str] | None): Names omitted when a capability owns them.
            codemode_web_policy (object | None): Egress policy for CodeMode-local web registry tools.

        Returns:
            SevnRegistryToolset: Toolset bound to ``ToolExecutor.dispatch``.

        Examples:
            >>> from sevn.tools.base import ToolExecutor
            >>> from sevn.agent.adapters.pydantic_adapter import PydanticToolRegistration
            >>> SevnRegistryToolset.from_registry(
            ...     ToolExecutor(),
            ...     PydanticToolRegistration((), {}, (), {}),
            ... ).id
            'sevn_registry'
        """
        codemode_eligible: frozenset[str] | None = None
        if codemode_enabled:
            codemode_eligible = compute_codemode_eligible_names(
                triager_tools=triager_tools or frozenset(),
                triager_skills=triager_skills or frozenset(),
            )
        tools = build_pydantic_tools_for_registry(
            executor,
            registration,
            extra_tools=extra_tools,
            codemode_eligible=codemode_eligible,
            exclude_tool_names=exclude_tool_names,
            codemode_web_policy=codemode_web_policy,
        )
        return cls(tools, id="sevn_registry")


__all__ = ["SevnRegistryToolset", "bound_tools_only_first_round"]
