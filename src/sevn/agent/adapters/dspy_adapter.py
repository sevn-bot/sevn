"""DSPy + λ-RLM adapter scaffolding (`specs/11-tools-registry.md` §2.6).

Produces full executor-width async callables for ``dspy.RLM`` integrations while allowing
narrow combinator subsets via deterministic allowlists. Does **not** import ``dspy``.

Module: sevn.agent.adapters.dspy_adapter
Depends: sevn.tools.base, sevn.tools.context

Exports:
    to_dspy_tools — bind ``executor.dispatch`` to each registered tool definition.
    lambda_rlm_filter — restrict DSPy-visible callables via operator allowlists.

Examples:
    >>> from sevn.agent.adapters.dspy_adapter import lambda_rlm_filter
    >>> lambda_rlm_filter({"a": 1, "b": 2}, allowlist={"a"})
    {'a': 1}
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, Mapping
from typing import TYPE_CHECKING, Any

from sevn.tools.base import ToolCall, ToolExecutor

if TYPE_CHECKING:
    from sevn.tools.context import ToolContext


def _wrap_tool(
    *,
    executor: ToolExecutor,
    runtime_ctx: ToolContext,
    name: str,
) -> Callable[..., Any]:
    """Return async callable forwarding kwargs to ``executor.dispatch``.

    Args:
        executor (ToolExecutor): Active registry owning ``Tool`` instances.
        runtime_ctx (ToolContext): Frozen per-turn context reused for every dispatch.
        name (str): Registered tool name bound by the wrapper.

    Returns:
        Callable[..., Any]: Async forwarder accepting tool kwargs.

    Examples:
        >>> import inspect
        >>> inspect.signature(_wrap_tool).parameters["name"].kind.name
        'KEYWORD_ONLY'
    """

    async def _forwarder(**payload: Any) -> str:
        call = ToolCall(name=name, arguments=dict(payload))
        return await executor.dispatch(runtime_ctx, call)

    _forwarder.__name__ = f"dspy_tool_{name}"
    return _forwarder


def to_dspy_tools(
    executor: ToolExecutor,
    runtime_ctx: ToolContext,
    *,
    include_disabled: bool = False,
) -> dict[str, Callable[..., Any]]:
    """Materialize DSPy-visible async callables for every registered definition.

            Args:
    executor (ToolExecutor): Active registry owning ``Tool`` instances.
    runtime_ctx (ToolContext): Frozen session snapshot adapters reuse per-turn.
    include_disabled (bool): When ``True``, keep disabled stubs (normally skipped).

            Returns:
                dict[str, Callable[..., Any]]: Name → shim callable mapping.

            Examples:
                >>> import asyncio
                >>> import json
                >>> from pathlib import Path
                >>> from sevn.tools.permissions import AllowAllPermissionPolicy
                >>> from sevn.tools.context import ToolContext
                >>> from sevn.tools.base import (
                ...     enveloped_success,
                ...     ToolDefinition,
                ...     FunctionTool,
                ...     ToolExecutor,
                ... )
                >>> exe = ToolExecutor(default_timeout_seconds=2.0)
                >>> definition = ToolDefinition(
                ...     name="echo",
                ...     category="meta",
                ...     description="echo",
                ...     parameters={
                ...         "type": "object",
                ...         "properties": {"phrase": {"type": "string"}},
                ...         "required": ["phrase"],
                ...     },
                ... )
                >>> async def echo(ctx: ToolContext, *, phrase: str) -> str:  # type: ignore[misc,no-untyped-def]
                ...     return enveloped_success({"phrase": phrase})
                ...
                >>> exe.register(FunctionTool(definition, echo))
                >>> ctx = ToolContext(
                ...     session_id="sess",
                ...     workspace_path=Path("/tmp"),
                ...     workspace_id="w",
                ...     registry_version=1,
                ...     trace=None,
                ...     permissions=AllowAllPermissionPolicy(),
                ... )
                >>> shim = to_dspy_tools(exe, ctx)["echo"]
                >>> payload = asyncio.run(shim(phrase="hi"))
                >>> json.loads(payload)["data"]["phrase"]
                'hi'
    """

    mapping: dict[str, Callable[..., Any]] = {}
    for bundle in executor.definitions():
        if not bundle.enabled and not include_disabled:
            continue
        mapping[bundle.name] = _wrap_tool(
            executor=executor, runtime_ctx=runtime_ctx, name=bundle.name
        )
    return mapping


def lambda_rlm_filter[T](
    tool_map: Mapping[str, T],
    *,
    allowlist: Iterable[Hashable] | Mapping[Hashable, Any],
) -> dict[str, T]:
    """Retain only tool names enumerated for λ-RLM combinator scopes.

            Args:
    tool_map (Mapping[str, T]): Source mapping (typically DSPy shim dict).
    allowlist (Iterable[Hashable] | Mapping[str, Any]): Operator-selected names.

            Returns:
                dict[str, T]: Subset keyed by allowable names preserving Tool objects.

            Examples:
                >>> lambda_rlm_filter({"a": None, "b": None}, allowlist=["b"])
                {'b': None}
    """

    allowed_names = (
        frozenset(allowlist.keys()) if isinstance(allowlist, Mapping) else frozenset(allowlist)
    )
    return {name: bundle for name, bundle in tool_map.items() if name in allowed_names}


__all__ = ["lambda_rlm_filter", "to_dspy_tools"]
