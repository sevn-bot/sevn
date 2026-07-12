"""Ordered plugin hook invocation (`specs/34-plugin-hooks.md` §4.2-§4.4).

Module: sevn.plugins.runner
Depends: sevn.agent.tracing, sevn.plugins.hook

Exports:
    RegisteredHook — one loaded hook with trust + ordering metadata.
    PluginHookChain — pre/transform/terminal chains with trace attrs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from time import time_ns
from typing import TYPE_CHECKING

from sevn.agent.tracing.sink import TraceEvent
from sevn.plugins.hook import Block, Continue, HookContext, PluginHook, Replace

if TYPE_CHECKING:
    from sevn.agent.tracing.sink import TraceSink


@dataclass(frozen=True)
class RegisteredHook:
    """Loaded hook plus workspace policy row."""

    hook: PluginHook
    plugin_id: str
    distribution_name: str
    entry_point_name: str
    trust_owner: bool


@dataclass
class PluginHookChain:
    """Sorted hooks for gateway + executor wiring."""

    hooks: tuple[RegisteredHook, ...]

    async def run_pre_tool_call(
        self,
        tool_name: str,
        args: dict[str, object],
        ctx: HookContext,
        trace: TraceSink | None,
    ) -> Continue | Block | Replace:
        """Run ``pre_tool_call`` for owner-trust hooks; compose ``Replace``.

        Args:
            tool_name (str): Tool symbol.
            args (dict[str, object]): Mutable args dict; may be replaced in-place when
                a hook returns ``Replace``.
            ctx (HookContext): Hook context.
            trace (TraceSink | None): Optional trace sink.

        Returns:
            Continue | Block | Replace: First ``Block`` wins; otherwise last outcome.

        Examples:
            >>> isinstance(True, bool)
            True
        """
        decision: Continue | Block | Replace = Continue()
        for rh in self.hooks:
            if not rh.trust_owner:
                continue
            try:
                out = await rh.hook.pre_tool_call(tool_name, args, ctx)
            except Exception as exc:
                if trace is not None:
                    await trace.emit(
                        TraceEvent(
                            kind="plugin.hook.error",
                            span_id=str(uuid.uuid4()),
                            parent_span_id=None,
                            session_id=ctx.session_id,
                            turn_id=ctx.turn_id,
                            tier=ctx.tier,
                            ts_start_ns=time_ns(),
                            ts_end_ns=time_ns(),
                            status="error",
                            attrs={
                                "plugin.name": rh.hook.name,
                                "exc_type": type(exc).__name__,
                            },
                        ),
                    )
                raise
            if trace is not None:
                if isinstance(out, Block):
                    decision_s = "block"
                elif isinstance(out, Replace):
                    decision_s = "replace"
                else:
                    decision_s = "continue"
                attrs: dict[str, object] = {
                    "plugin.name": rh.hook.name,
                    "tool.name": tool_name,
                    "decision": decision_s,
                }
                if isinstance(out, Block):
                    attrs["block.reason"] = out.reason
                if isinstance(out, Replace):
                    attrs["replace.diff_keys"] = tuple(out.new_args.keys())
                await trace.emit(
                    TraceEvent(
                        kind="plugin.hook.pre_tool_call",
                        span_id=str(uuid.uuid4()),
                        parent_span_id=None,
                        session_id=ctx.session_id,
                        turn_id=ctx.turn_id,
                        tier=ctx.tier,
                        ts_start_ns=time_ns(),
                        ts_end_ns=time_ns(),
                        status="ok",
                        attrs=attrs,
                    ),
                )
            if isinstance(out, Block):
                return out
            if isinstance(out, Replace):
                args.clear()
                args.update(out.new_args)
                decision = out
            else:
                decision = out
        return decision

    async def run_transform_tool_result(
        self,
        tool_name: str,
        result: object,
        ctx: HookContext,
        trace: TraceSink | None,
    ) -> object:
        """Run ``transform_tool_result`` in registration order.

        Args:
            tool_name (str): Tool that produced ``result``.
            result (object): Current result object.
            ctx (HookContext): Hook context.
            trace (TraceSink | None): Optional trace sink.

        Returns:
            object: Transformed result (or failure envelope string stub on error).

        Examples:
            >>> isinstance(True, bool)
            True
        """
        out: object = result
        for rh in self.hooks:
            size_in = len(repr(out)) if out is not None else 0
            try:
                out = await rh.hook.transform_tool_result(tool_name, out, ctx)
            except Exception as exc:
                if trace is not None:
                    await trace.emit(
                        TraceEvent(
                            kind="plugin.hook.error",
                            span_id=str(uuid.uuid4()),
                            parent_span_id=None,
                            session_id=ctx.session_id,
                            turn_id=ctx.turn_id,
                            tier=ctx.tier,
                            ts_start_ns=time_ns(),
                            ts_end_ns=time_ns(),
                            status="error",
                            attrs={
                                "plugin.name": rh.hook.name,
                                "exc_type": type(exc).__name__,
                            },
                        ),
                    )
                from sevn.tools.base import enveloped_failure
                from sevn.tools.codes import ToolResultCode

                return enveloped_failure(
                    "transform_tool_result raised",
                    code=ToolResultCode.INTERNAL_ERROR,
                    data={"plugin": rh.hook.name, "exc_type": type(exc).__name__},
                )
            size_out = len(repr(out)) if out is not None else 0
            if trace is not None:
                await trace.emit(
                    TraceEvent(
                        kind="plugin.hook.transform_tool_result",
                        span_id=str(uuid.uuid4()),
                        parent_span_id=None,
                        session_id=ctx.session_id,
                        turn_id=ctx.turn_id,
                        tier=ctx.tier,
                        ts_start_ns=time_ns(),
                        ts_end_ns=time_ns(),
                        status="ok",
                        attrs={
                            "plugin.name": rh.hook.name,
                            "tool.name": tool_name,
                            "result_size_in": size_in,
                            "result_size_out": size_out,
                        },
                    ),
                )
        return out

    async def transform_terminal_chunk(
        self,
        chunk: str,
        ctx: HookContext,
        trace: TraceSink | None,
    ) -> str:
        """Apply ``transform_terminal_output`` per hook; exceptions drop the chunk.

        Args:
            chunk (str): One decoded text chunk.
            ctx (HookContext): Hook context.
            trace (TraceSink | None): Optional trace sink.

        Returns:
            str: Transformed chunk, or empty when a hook raises.

        Examples:
            >>> isinstance(True, bool)
            True
        """
        out = chunk
        for rh in self.hooks:
            size_in = len(out)
            try:
                out = await rh.hook.transform_terminal_output(out, ctx)
            except Exception as exc:
                if trace is not None:
                    await trace.emit(
                        TraceEvent(
                            kind="plugin.hook.error",
                            span_id=str(uuid.uuid4()),
                            parent_span_id=None,
                            session_id=ctx.session_id,
                            turn_id=ctx.turn_id,
                            tier=ctx.tier,
                            ts_start_ns=time_ns(),
                            ts_end_ns=time_ns(),
                            status="warn",
                            attrs={
                                "plugin.name": rh.hook.name,
                                "exc_type": type(exc).__name__,
                            },
                        ),
                    )
                return ""
            size_out = len(out)
            if trace is not None:
                await trace.emit(
                    TraceEvent(
                        kind="plugin.hook.transform_terminal_output",
                        span_id=str(uuid.uuid4()),
                        parent_span_id=None,
                        session_id=ctx.session_id,
                        turn_id=ctx.turn_id,
                        tier=ctx.tier,
                        ts_start_ns=time_ns(),
                        ts_end_ns=time_ns(),
                        status="ok",
                        attrs={
                            "plugin.name": rh.hook.name,
                            "chunk_size_in": size_in,
                            "chunk_size_out": size_out,
                        },
                    ),
                )
        return out


__all__ = ["PluginHookChain", "RegisteredHook"]
