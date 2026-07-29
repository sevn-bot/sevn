"""Async Monty backend for tier-B CodeMode (D13 structural freeze fix).

The stock harness ``CodeModeToolset`` drives Monty synchronously on the event loop
(``feed_start`` / ``resume``), so a CPU-bound ``run_code`` snippet blocks tier-B
``asyncio.wait_for`` timeouts. This module swaps the execution backend for a local
``AsyncMonty`` pool (awaitable snapshots) while inheriting tool catalog, dispatch,
and retry semantics from the harness.

Module: sevn.agent.adapters.tier_b_async_codemode
Depends: pydantic_ai_harness, pydantic_monty, sevn.agent.adapters._monty_limits

Exports:
    SevnAsyncCodeMode — drop-in ``CodeMode`` using ``AsyncMonty`` (provider ``monty`` only).
    SevnAsyncCodeModeToolset — harness toolset with async Monty execution backend.
"""

from __future__ import annotations

import asyncio
from collections.abc import Container, Coroutine
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, cast

from pydantic_ai import AbstractToolset, RunContext  # noqa: TC002
from pydantic_ai.exceptions import ApprovalRequired, CallDeferred, ModelRetry, UserError
from pydantic_ai.messages import ToolCallPart, ToolReturn, ToolReturnPart
from pydantic_ai.tool_manager import ToolManager
from pydantic_ai.tools import AgentDepsT, ToolDenied
from pydantic_ai.toolsets.abstract import ToolsetTool  # noqa: TC002
from pydantic_ai_harness import CodeMode
from pydantic_ai_harness._monty_exec import PrintCapture, is_sandbox_panic
from pydantic_ai_harness.code_mode._toolset import (  # pyright: ignore[reportPrivateUsage]
    _TOOL_RETURN_CONTENT_TA,
    CodeModeToolset,
    _contains_multimodal,
    _global_mode_is_sequential,
    _RunCodeTool,
)
from pydantic_monty import (
    AsyncFunctionSnapshot,
    AsyncMonty,
    AsyncMontySession,
    AsyncNameLookupSnapshot,
    AsyncSnapshot,
    ExternalException,
    ExternalReturnValue,
    ExternalSettledResult,
    MontyComplete,
    MontyCrashedError,
    MontyRuntimeError,
    MontySyntaxError,
    MontyTypingError,
)

from sevn.agent.executors.b_types import BTierDeps

PendingCall = asyncio.Task[Any] | Coroutine[Any, Any, Any]


def _make_external_lookup_entry(
    sandbox_name: str,
    dispatch: Any,
) -> Any:
    """Build one ``external_lookup`` entry for async Monty ``feed_start``.

    Args:
        sandbox_name (str): Sanitized sandbox function name.
        dispatch (Any): Async host dispatch callback.

    Returns:
        Any: Awaitable host function bound for Monty lookup.

    Examples:
        >>> True
        True
    """

    async def _external(**kwargs: Any) -> Any:
        return await dispatch(sandbox_name, kwargs)

    return _external


@dataclass
class _AsyncMontyRunState:
    """Monty async pool + session shared across toolset views for one agent run."""

    pool: AsyncMonty | None = None
    session: AsyncMontySession | None = None
    has_executed_feed: bool = False
    _pool_stack: AsyncExitStack = field(default_factory=AsyncExitStack, repr=False)
    _session_stack: AsyncExitStack = field(default_factory=AsyncExitStack, repr=False)

    async def get_session(
        self, *, type_check: bool, type_check_stubs: str | None
    ) -> AsyncMontySession:
        """Return the run's live REPL session, creating its pool on first use.

        Args:
            type_check (bool): Whether to type-check the first snippet.
            type_check_stubs (str | None): Optional stub definitions for type-check.

        Returns:
            AsyncMontySession: Checked-out REPL session.

        Examples:
            >>> True
            True
        """
        if self.pool is None:
            self.pool = await self._pool_stack.enter_async_context(AsyncMonty())
        if self.session is None:
            self.session = await self._session_stack.enter_async_context(
                self.pool.checkout(type_check=type_check, type_check_stubs=type_check_stubs)
            )
        return self.session

    async def reset(self) -> None:
        """Return the current worker and make the next call start a fresh REPL.

        Examples:
            >>> True
            True
        """
        await self._session_stack.aclose()
        self._session_stack = AsyncExitStack()
        self.session = None
        self.has_executed_feed = False

    async def close(self) -> None:
        """Tear down the checked-out worker and close the owning pool.

        Examples:
            >>> True
            True
        """
        await self.reset()
        await self._pool_stack.aclose()
        self._pool_stack = AsyncExitStack()
        self.pool = None


@dataclass
class _AsyncMontyExecutor:
    """Drive an async Monty REPL, dispatching external calls to a host callback."""

    dispatch: Any
    valid_names: Container[str]
    sequential_names: set[str] = field(default_factory=set)
    global_sequential: bool = False
    _pending: dict[int, PendingCall] = field(default_factory=dict, init=False)
    _pre_resolved: dict[int, ExternalSettledResult] = field(default_factory=dict, init=False)

    async def run(self, state: AsyncSnapshot) -> MontyComplete:
        """Drive the REPL from ``state`` until it completes.

        Args:
            state (AsyncSnapshot): Initial Monty async snapshot from ``feed_start``.

        Returns:
            MontyComplete: Terminal completion snapshot.

        Examples:
            >>> True
            True
        """
        try:
            while not isinstance(state, MontyComplete):
                if isinstance(state, AsyncNameLookupSnapshot):
                    if state.variable_name in self.valid_names:
                        state = await state.resume_auto()
                    else:
                        state = await state.resume()
                elif isinstance(state, AsyncFunctionSnapshot):
                    state = await self._handle_function(state)
                else:
                    state = await self._resolve_futures(state)
        finally:
            cancelled: list[asyncio.Task[Any]] = []
            for call in self._pending.values():
                if isinstance(call, asyncio.Task):
                    call.cancel()
                    cancelled.append(call)
                else:
                    call.close()
            if cancelled:
                await asyncio.gather(*cancelled, return_exceptions=True)
        if not isinstance(state, MontyComplete):
            msg = "Monty executor finished without MontyComplete"
            raise RuntimeError(msg)
        return state

    async def _handle_function(self, snapshot: AsyncFunctionSnapshot) -> AsyncSnapshot:
        """Dispatch (or defer) one external function snapshot.

        Args:
            snapshot (AsyncFunctionSnapshot): Pending sandbox external call.

        Returns:
            AsyncSnapshot: Next async Monty snapshot after resume.

        Examples:
            >>> True
            True
        """
        if snapshot.is_os_function:
            return await snapshot.resume_auto()

        name = snapshot.function_name
        if name not in self.valid_names:
            return await snapshot.resume({"exception": NameError(f"Unknown function: {name}")})

        if snapshot.args:
            return await snapshot.resume(
                {
                    "exception": TypeError(
                        f"{name}() does not accept positional arguments; use keyword arguments"
                    ),
                },
            )

        if name in self.sequential_names:
            for cid in list(self._pending):
                self._pre_resolved[cid] = await _await_external(self._pending.pop(cid))
            return await snapshot.resume(
                await _await_external(self.dispatch(name, snapshot.kwargs))
            )

        call = self.dispatch(name, snapshot.kwargs)
        if self.global_sequential:
            self._pending[snapshot.call_id] = call
        else:
            self._pending[snapshot.call_id] = asyncio.ensure_future(call)
        return await snapshot.resume({"future": ...})

    async def _resolve_futures(self, snapshot: Any) -> AsyncSnapshot:
        """Resolve deferred async tool calls at a future snapshot.

        Args:
            snapshot (Any): ``AsyncFutureSnapshot`` waiting on host tasks.

        Returns:
            AsyncSnapshot: Next async Monty snapshot after resume.

        Examples:
            >>> True
            True
        """
        pending_ids = snapshot.pending_call_ids
        results: dict[int, ExternalSettledResult] = {}
        for cid in pending_ids:
            if cid in self._pre_resolved:
                results[cid] = self._pre_resolved.pop(cid)
            elif self.global_sequential:
                results[cid] = await _await_external(self._pending.pop(cid))

        gather_ids = [cid for cid in pending_ids if cid not in results]
        if gather_ids:
            settled = await asyncio.gather(
                *(self._pending[cid] for cid in gather_ids),
                return_exceptions=True,
            )
            for cid, outcome in zip(gather_ids, settled, strict=True):
                del self._pending[cid]
                results[cid] = _wrap_gathered(outcome)

        return cast("AsyncSnapshot", await snapshot.resume(results))


async def _await_external(call: PendingCall) -> ExternalReturnValue | ExternalException:
    """Await one deferred host-side tool call and wrap the outcome for Monty.

    Args:
        call (PendingCall): Task or coroutine representing one host dispatch.

    Returns:
        ExternalReturnValue | ExternalException: Result envelope for Monty resume.

    Examples:
        >>> True
        True
    """
    try:
        result = await call
    except Exception as exc:
        return ExternalException(exception=exc)
    return ExternalReturnValue(return_value=result)


def _wrap_gathered(outcome: Any) -> ExternalReturnValue | ExternalException:
    """Wrap an ``asyncio.gather`` outcome for Monty resume.

    Args:
        outcome (Any): Settled task result or exception from ``gather``.

    Returns:
        ExternalReturnValue | ExternalException: Result envelope for Monty resume.

    Examples:
        >>> from sevn.agent.adapters.tier_b_async_codemode import _wrap_gathered
        >>> isinstance(_wrap_gathered(1), object)
        True
    """
    if isinstance(outcome, Exception):
        return ExternalException(exception=outcome)
    if isinstance(outcome, BaseException):  # pragma: no cover
        raise outcome
    return ExternalReturnValue(return_value=outcome)


@dataclass
class SevnAsyncCodeModeToolset(CodeModeToolset[AgentDepsT]):
    """``CodeModeToolset`` executing ``run_code`` on a local ``AsyncMonty`` pool."""

    _async_run_state: _AsyncMontyRunState | None = field(
        default=None, init=False, repr=False, compare=False
    )

    async def for_run_step(self, ctx: RunContext[AgentDepsT]) -> AbstractToolset[AgentDepsT]:
        """Preserve async REPL state when the wrapped toolset advances one step.

        Args:
            ctx (RunContext[AgentDepsT]): Current pydantic-ai run context.

        Returns:
            AbstractToolset[AgentDepsT]: Toolset view for the next step.

        Examples:
            >>> True
            True
        """
        new_self = await super().for_run_step(ctx)
        if new_self is not self:
            if not isinstance(new_self, SevnAsyncCodeModeToolset):
                msg = "for_run_step must preserve SevnAsyncCodeModeToolset type"
                raise TypeError(msg)
            new_self._async_run_state = self._async_run_state
        return new_self

    async def __aenter__(self) -> SevnAsyncCodeModeToolset[AgentDepsT]:
        """Enter the wrapped toolset and prepare lazy async Monty resources.

        Returns:
            SevnAsyncCodeModeToolset[AgentDepsT]: Entered toolset instance.

        Examples:
            >>> True
            True
        """
        await self.wrapped.__aenter__()
        self._async_run_state = _AsyncMontyRunState()
        return self

    async def __aexit__(self, *args: Any) -> bool | None:
        """Exit the wrapped toolset and tear down the async Monty pool.

        Args:
            args (Any): Exception info forwarded from the async context manager.

        Returns:
            bool | None: Whether an exception was suppressed.

        Examples:
            >>> True
            True
        """
        run_state = self._async_run_state
        if run_state is None:
            msg = "SevnAsyncCodeModeToolset exited without entering"
            raise RuntimeError(msg)
        self._async_run_state = None
        try:
            return await self.wrapped.__aexit__(*args)
        finally:
            await run_state.close()

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[AgentDepsT],
        tool: ToolsetTool[AgentDepsT],
    ) -> Any:
        """Execute Python in the async Monty sandbox, or pass through native tools.

        Args:
            name (str): Tool name being invoked.
            tool_args (dict[str, Any]): Validated tool arguments.
            ctx (RunContext[AgentDepsT]): Current pydantic-ai run context.
            tool (ToolsetTool[AgentDepsT]): Resolved toolset tool metadata.

        Returns:
            Any: Tool return value or ``ToolReturn`` wrapper for ``run_code``.

        Examples:
            >>> True
            True
        """
        if not isinstance(tool, _RunCodeTool):
            return await self.wrapped.call_tool(name, tool_args, ctx, tool)

        code = tool_args["code"]
        restart = tool_args.get("restart", False)

        run_state = self._async_run_state
        if run_state is None:
            msg = "SevnAsyncCodeModeToolset must be entered before run_code"
            raise RuntimeError(msg)

        if restart:
            await run_state.reset()

        fresh_repl = not run_state.has_executed_feed
        callable_defs = tool.callable_defs
        sanitized_to_original = tool.sanitized_to_original

        parent_tm = ctx.tool_manager
        if parent_tm is None:
            msg = "SevnAsyncCodeModeToolset requires ctx.tool_manager"
            raise RuntimeError(msg)
        tool_manager = ToolManager(
            toolset=self.wrapped,
            root_capability=parent_tm.root_capability,
            ctx=ctx,
            tools=tool.wrapped_tools,
        )

        global_sequential = _global_mode_is_sequential(tool_manager.get_parallel_execution_mode)
        sequential_tools = {n for n, td in callable_defs.items() if td.sequential}

        nested_calls: dict[str, ToolCallPart] = {}
        nested_returns: dict[str, ToolReturnPart] = {}
        call_counter = 0

        async def dispatch_tool_call(sandbox_name: str, kwargs: dict[str, Any]) -> Any:
            nonlocal call_counter
            original_name = sanitized_to_original.get(sandbox_name, sandbox_name)
            call_counter += 1
            parent_id = ctx.tool_call_id or "pyd_ai_code_mode"
            tool_call_id = f"{parent_id}__{call_counter}"
            call_part = ToolCallPart(
                tool_name=original_name, args=kwargs, tool_call_id=tool_call_id
            )
            nested_calls[tool_call_id] = call_part

            try:
                result = await tool_manager.handle_call(call_part, wrap_validation_errors=False)
            except (CallDeferred, ApprovalRequired) as exc:
                raise UserError(
                    f"Tool {original_name!r} raised {type(exc).__name__} inside code mode, "
                    "but no `HandleDeferredToolCalls` capability resolved it.",
                ) from exc

            if isinstance(result, ToolDenied):
                nested_returns[tool_call_id] = ToolReturnPart(
                    tool_name=original_name,
                    content=result.message,
                    tool_call_id=tool_call_id,
                    outcome="denied",
                )
                raise RuntimeError(f"Tool {original_name!r} call denied: {result.message}")

            return_metadata: Any = None
            if isinstance(result, ToolReturn):
                return_metadata = result.metadata
                result = result.return_value

            nested_returns[tool_call_id] = ToolReturnPart(
                tool_name=original_name,
                content=result,
                tool_call_id=tool_call_id,
                metadata=return_metadata,
            )
            return _TOOL_RETURN_CONTENT_TA.dump_python(result)

        type_check = fresh_repl and bool(callable_defs)
        type_check_stubs = self._build_type_check_stubs(callable_defs) if type_check else None
        capture = PrintCapture()

        external_lookup = {
            sandbox_name: _make_external_lookup_entry(sandbox_name, dispatch_tool_call)
            for sandbox_name in callable_defs
        }

        try:
            session = await run_state.get_session(
                type_check=type_check, type_check_stubs=type_check_stubs
            )
            try:
                monty_state = await session.feed_start(
                    code,
                    external_lookup=external_lookup,
                    print_callback=capture.callback,
                    os=self.os_access,
                    mount=self.mount,
                    skip_type_check=not type_check,
                )
                completed = await _AsyncMontyExecutor(
                    dispatch=dispatch_tool_call,
                    valid_names=callable_defs,
                    sequential_names=sequential_tools,
                    global_sequential=global_sequential,
                ).run(monty_state)
            except MontyRuntimeError:
                run_state.has_executed_feed = True
                raise
            run_state.has_executed_feed = True
        except MontySyntaxError as exc:
            if fresh_repl:
                await run_state.reset()
            raise ModelRetry(f"Syntax error in code:\n{capture.prepend_to(exc.display())}") from exc
        except MontyTypingError as exc:
            await run_state.reset()
            raise ModelRetry(f"Type error in code:\n{capture.prepend_to(exc.display())}") from exc
        except MontyRuntimeError as exc:
            raise ModelRetry(f"Runtime error:\n{capture.prepend_to(exc.display())}") from exc
        except MontyCrashedError as exc:
            await run_state.reset()
            raise ModelRetry(
                "The code crashed the sandbox worker and the session was reset. "
                "Revise the code and try again.",
            ) from exc
        except BaseException as exc:
            if not is_sandbox_panic(exc):
                await run_state.reset()
                raise
            await run_state.reset()
            raise ModelRetry(
                "The code aborted inside the sandbox and the session was reset. "
                "Revise the code and try again.",
            ) from exc

        result = completed.output
        printed = capture.joined

        if result is not None:
            result = _TOOL_RETURN_CONTENT_TA.validate_python(result)

        if not printed:
            return_value: Any = result if result is not None else {}
        elif result is None:
            return_value = {"output": printed}
        elif _contains_multimodal(result):
            return_value = [printed, *result] if isinstance(result, list) else [printed, result]
        else:
            return_value = {"output": printed, "result": result}

        return ToolReturn(
            return_value=return_value,
            metadata={
                "code_mode": True,
                "tool_calls": nested_calls,
                "tool_returns": nested_returns,
            },
        )


@dataclass
class SevnAsyncCodeMode(CodeMode[BTierDeps]):
    """Tier-B ``CodeMode`` with an ``AsyncMonty`` execution backend (D13)."""

    def get_wrapper_toolset(
        self, toolset: AbstractToolset[BTierDeps]
    ) -> AbstractToolset[BTierDeps] | None:
        """Wrap the agent toolset with the async Monty ``run_code`` backend.

        Args:
            toolset (AbstractToolset[BTierDeps]): Assembled agent toolset.

        Returns:
            AbstractToolset[BTierDeps] | None: Async CodeMode wrapper toolset.

        Examples:
            >>> from sevn.agent.adapters.tier_b_async_codemode import SevnAsyncCodeMode
            >>> cap = SevnAsyncCodeMode()
            >>> cap.__class__.__name__
            'SevnAsyncCodeMode'
        """
        return SevnAsyncCodeModeToolset(
            wrapped=toolset,
            tool_selector=self.tools,
            max_retries=self.max_retries,
            dynamic_catalog=self.dynamic_catalog,
            os_access=self.os_access,
            mount=self.mount,
        )


__all__ = ["SevnAsyncCodeMode", "SevnAsyncCodeModeToolset"]
