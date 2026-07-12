"""Declarative `@sevn_tool` metadata binding (`specs/11-tools-registry.md` §2.3).

Stores a finalized ``ToolDefinition`` on callable objects so gateways can iterate
registration tables without duplicated dictionaries.

Module: sevn.tools.decorator
Depends: sevn.tools.base

Exports:
    sevn_tool — decorator binding catalog metadata onto async callables.
    tool_from_decorated — build ``FunctionTool`` instances from annotated callables.

Examples:
    >>> @sevn_tool(
    ...     name="demo",
    ...     category="meta",
    ...     description="demo",
    ...     parameters={"type": "object", "properties": {}},
    ... )
    ... async def demo(ctx):  # type: ignore[misc,no-untyped-def]
    ...     from sevn.tools.base import enveloped_success
    ...     return enveloped_success({"v": True})
    ...
    >>> tool_from_decorated(demo).definition().name == "demo"
    True
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Final, Literal, TypeVar

from sevn.tools.base import FunctionTool, SandboxMode, ToolDefinition

_SEVN_DEF: Final[str] = "__sevn_tool_definition__"


F = TypeVar("F", bound=Callable[..., Any])


def sevn_tool(
    *,
    name: str,
    category: str,
    description: str,
    parameters: dict[str, Any],
    requires_human: bool = False,
    abortable: bool = True,
    sandbox_mode: SandboxMode = "none",
    large_result: bool = False,
    see_also: Sequence[str] = (),
    enabled: bool = True,
    capability_key: str | None = None,
    long_description_file: str | None = None,
    dispatch_timeout_seconds: float | None | Literal["inherit"] = "inherit",
) -> Callable[[F], F]:
    """Declare normative Layer-3 metadata alongside the callable Python body.

            Args:
    name (str): Canonical tool identifier.
    category (str): Tracing/documentation bucket (`file_ops`, …).
    description (str): One-line Triager-visible summary (always loaded).
    parameters (dict[str, Any]): JSON Schema object for adapters.
    requires_human (bool): Human gate enforced by ``ToolExecutor``.
    abortable (bool): Whether cancellation may interrupt the callable.
    sandbox_mode (SandboxMode): Execution locality hint.
    large_result (bool): Hint for spill heuristics.
    see_also (Sequence[str]): Optional cross-links to skills/other tools.
    enabled (bool): Feature flag without unregistering callable code.
    capability_key (str | None): Stable permission/policy label when wired.
    long_description_file (str | None): Workspace-relative path (e.g.
        ``tools/log_query.md``) for the on-demand long description. Resolved by
        ``load_tool`` at dispatch time — workspace overlay first, packaged template
        fallback (`specs/11-tools-registry.md` §2.3, §2.4).
    dispatch_timeout_seconds (float | None | Literal["inherit"]): Per-tool override for
        ``ToolExecutor.dispatch``'s outer deadline (see
        :attr:`sevn.tools.base.ToolDefinition.dispatch_timeout_seconds`). Defaults to
        ``"inherit"`` (the executor's generic default); pass ``None`` for tools that
        enforce their own wall-clock budget internally, or a float margin (e.g. a cold
        local-model start) that exceeds the generic default.

            Returns:
                Callable[[F], F]: Decorator preserving callable type.

            Examples:
                >>> @sevn_tool(
                ...     name="z",
                ...     category="c",
                ...     description="d",
                ...     parameters={"type": "object", "properties": {}},
                ... )
                ... async def zz(ctx):  # type: ignore[misc,no-untyped-def]
                ...     from sevn.tools.base import enveloped_success
                ...     return enveloped_success({})
                ...
                >>> hasattr(zz, _SEVN_DEF)
                True
    """

    def deco(fn: F) -> F:
        setattr(
            fn,
            _SEVN_DEF,
            ToolDefinition(
                name=name,
                category=category,
                description=description,
                parameters=dict(parameters),
                requires_human=requires_human,
                abortable=abortable,
                sandbox_mode=sandbox_mode,
                large_result=large_result,
                see_also=tuple(see_also),
                enabled=enabled,
                capability_key=capability_key,
                long_description_file=long_description_file,
                dispatch_timeout_seconds=dispatch_timeout_seconds,
            ),
        )
        return fn

    return deco


def tool_from_decorated(fn: Callable[..., Any]) -> FunctionTool:
    """Hydrate metadata stored via ``sevn_tool`` into a registry-ready ``Tool``.

            Args:
    fn (Callable[..., Any]): Decorated callable carrying ``ToolDefinition``.

            Returns:
                FunctionTool: Executable bridge for ``ToolExecutor``.

            Raises:
                ValueError: Missing decorator metadata attribute.

            Examples:
                >>> @sevn_tool(
                ...     name="t",
                ...     category="c",
                ...     description="d",
                ...     parameters={"type": "object", "properties": {}},
                ... )
                ... async def local_fn(ctx):  # type: ignore[misc,no-untyped-def]
                ...     return '{"ok": true, "data": {}, "message": null}'
                ...
                >>> tool_from_decorated(local_fn).definition().name
                't'
    """

    definition_obj = getattr(fn, _SEVN_DEF, None)
    if definition_obj is None:
        msg = "callable missing @sevn_tool metadata — apply sevn.tools.decorator.sevn_tool"
        raise ValueError(msg)
    if not isinstance(definition_obj, ToolDefinition):
        msg = "__sevn_tool_definition__ corrupted; expected ToolDefinition"
        raise TypeError(msg)
    return FunctionTool(definition_obj, fn)


__all__ = ["sevn_tool", "tool_from_decorated"]
