"""Plugin hook types (`PluginHook` protocol and optional base class).

Module: sevn.plugins.hook
Depends: (none)

Exports:
    HookContext — read-only hook invocation context.
    Continue — allow unchanged.
    Block — reject with a reason.
    Replace — substitute validated tool arguments.
    PluginHook — interception protocol surface.
    PluginHookBase — default no-op implementations.

Examples:
    >>> HookContext(workspace_id="w", session_id="s", turn_id="t", tier="B", correlation_id="c")
    HookContext(...)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class HookContext:
    """Read-only context for a hook invocation."""

    workspace_id: str
    session_id: str
    turn_id: str
    tier: str
    correlation_id: str


@dataclass(frozen=True)
class Continue:
    """Allow the in-flight call unchanged."""


@dataclass(frozen=True)
class Block:
    """Reject the call; surface `reason` to the model."""

    reason: str


@dataclass(frozen=True)
class Replace:
    """Proceed with substituted args (must pass tool input validation)."""

    new_args: dict[str, object]


@runtime_checkable
class PluginHook(Protocol):
    """Optional interception points — plugins may inherit ``PluginHookBase``."""

    name: str

    async def pre_tool_call(
        self,
        tool_name: str,
        args: dict[str, object],
        ctx: HookContext,
    ) -> Continue | Block | Replace:
        """Inspect or rewrite a tool call before execution.

                Args:
        tool_name (str): Tool symbol under consideration.
        args (dict): Tool arguments from the model.
        ctx (HookContext): Call context for routing and audit.

                Returns:
                    Continue | Block | Replace: Gate outcome for the tool call.

                Examples:
                    >>> isinstance(True, bool)
                    True
        """
        ...

    async def transform_tool_result(
        self,
        tool_name: str,
        result: object,
        ctx: HookContext,
    ) -> object:
        """Rewrite a tool result before it returns to the model.

                Args:
        tool_name (str): Tool that produced the result.
        result (object): Raw tool return value.
        ctx (HookContext): Call context.

                Returns:
                    object: Possibly rewritten result.

                Examples:
                    >>> isinstance(True, bool)
                    True
        """
        ...

    async def transform_terminal_output(self, chunk: str, ctx: HookContext) -> str:
        """Rewrite each decoded terminal / subprocess text chunk before UI/LLM sees it.

        Args:
            chunk (str): One outbound text chunk.
            ctx (HookContext): Call context.

        Returns:
            str: Possibly rewritten chunk.

        Examples:
            >>> isinstance(True, bool)
            True
        """
        ...

    async def trigger_before_receive(
        self,
        *,
        transport: str,
        correlation_id: str,
        trigger_meta: dict[str, object],
    ) -> None:
        """Optional trigger ingress hook (`specs/30-non-interactive-triggers.md` §2.1).

        Args:
            transport (str): Coarse label (``webhook``, ``api``, ``cron``).
            correlation_id (str): Fire identifier.
            trigger_meta (dict[str, object]): Provider metadata.

        Examples:
            >>> isinstance(True, bool)
            True
        """
        ...

    async def trigger_after_dispatch(
        self,
        *,
        transport: str,
        correlation_id: str,
        trigger_meta: dict[str, object],
        status: str,
    ) -> None:
        """Optional trigger egress hook after notify/dispatch arms complete.

        Args:
            transport (str): Coarse transport label.
            correlation_id (str): Fire identifier.
            trigger_meta (dict[str, object]): Provider metadata.
            status (str): Outcome label (``ok``, ``error``, …).

        Examples:
            >>> isinstance(True, bool)
            True
        """
        ...

    def register_command(self) -> list[object]:
        """Return command specs (shape defined in ``specs/34-plugin-hooks.md``).

        Returns:
            list[object]: Command specifications for gateway registration.

        Examples:
            >>> isinstance(True, bool)
            True
        """
        ...

    async def dispatch_tool(
        self,
        dispatch_key: str,
        argv_tokens: list[str],
        ctx: HookContext,
    ) -> object | None:
        """Handle a plugin-owned slash command outside the LLM loop.

                Args:
        dispatch_key (str): Stable key from :class:`~sevn.plugins.command_spec.PluginCommandSpec`.
        argv_tokens (list[str]): Tokenized argv after the slash verb (shell-like splitting).
        ctx (HookContext): Call context.

                Returns:
                    object | None: User-visible object when handled; ``None`` to defer.

                Examples:
                    >>> isinstance(True, bool)
                    True
        """
        ...


class PluginHookBase:
    """Defaults matching safe hook semantics until the gateway registers real hooks."""

    def __init__(self, name: str) -> None:
        """Create a base hook with a stable ``name`` for logging.

                Args:
        name (str): Hook identifier.

                Examples:
                    >>> isinstance(True, bool)
                    True
        """
        self.name = name

    async def pre_tool_call(
        self,
        tool_name: str,
        args: dict[str, object],
        ctx: HookContext,
    ) -> Continue | Block | Replace:
        """Allow all tool calls by default.

                Args:
        tool_name (str): Tool symbol.
        args (dict): Tool arguments.
        ctx (HookContext): Call context.

                Returns:
                    Continue | Block | Replace: Always ``Continue()``.

                Examples:
                    >>> isinstance(True, bool)
                    True
        """
        _ = (tool_name, args, ctx)
        return Continue()

    async def transform_tool_result(
        self,
        tool_name: str,
        result: object,
        ctx: HookContext,
    ) -> object:
        """Return tool results unchanged by default.

                Args:
        tool_name (str): Tool symbol.
        result (object): Tool output.
        ctx (HookContext): Call context.

                Returns:
                    object: Same as ``result``.

                Examples:
                    >>> isinstance(True, bool)
                    True
        """
        _ = (tool_name, ctx)
        return result

    async def transform_terminal_output(self, chunk: str, ctx: HookContext) -> str:
        """Passthrough text chunks by default.

                Args:
        chunk (str): Outbound text.
        ctx (HookContext): Call context.

                Returns:
                    str: Same as ``chunk``.

                Examples:
                    >>> isinstance(True, bool)
                    True
        """
        _ = ctx
        return chunk

    async def trigger_before_receive(
        self,
        *,
        transport: str,
        correlation_id: str,
        trigger_meta: dict[str, object],
    ) -> None:
        """No-op default; plugins may observe trigger ingress.

        Args:
            transport (str): Transport label.
            correlation_id (str): Correlation id.
            trigger_meta (dict[str, object]): Provider metadata.

        Examples:
            >>> isinstance(True, bool)
            True
        """
        _ = (transport, correlation_id, trigger_meta)

    async def trigger_after_dispatch(
        self,
        *,
        transport: str,
        correlation_id: str,
        trigger_meta: dict[str, object],
        status: str,
    ) -> None:
        """No-op default; plugins may observe trigger completion.

        Args:
            transport (str): Transport label.
            correlation_id (str): Correlation id.
            trigger_meta (dict[str, object]): Provider metadata.
            status (str): Outcome label.

        Examples:
            >>> isinstance(True, bool)
            True
        """
        _ = (transport, correlation_id, trigger_meta, status)

    def register_command(self) -> list[object]:
        """Register no CLI/Telegram commands by default.

        Returns:
            list[object]: Empty list.

        Examples:
            >>> isinstance(True, bool)
            True
        """
        return []

    async def dispatch_tool(
        self,
        dispatch_key: str,
        argv_tokens: list[str],
        ctx: HookContext,
    ) -> object | None:
        """Defer slash dispatch to the core registry by default.

                Args:
        dispatch_key (str): Plugin command key.
        argv_tokens (list[str]): Args after the verb.
        ctx (HookContext): Call context.

                Returns:
                    object | None: Always ``None``.

                Examples:
                    >>> isinstance(True, bool)
                    True
        """
        _ = (dispatch_key, argv_tokens, ctx)
        return None
