"""Gateway boot hook: construct the process-wide sub-agent supervisor (D3/D4/D10).

Module: sevn.gateway.subagents.subagents_boot
Depends: sevn.agent.subagents, sevn.agent.tracing.subagent_trace, sevn.gateway.boot_registry,
    sevn.gateway.subagents.subagents_announce

Exports:
    register_subagents_boot_hook — register the CW-2 boot hook (module import
        side-effect, mirrors ``telemetry_boot.py``; registration itself is
        one-shot — see ``boot_registry.register_boot_hook`` — so unlike this
        module's own import-time call, re-invoking it a second time raises).
    build_persist_result_hook — write completion text at finish (#76).

One :class:`~sevn.agent.subagents.SubAgentRegistry` /
:class:`~sevn.agent.subagents.SubAgentSupervisor` pair is constructed per
gateway process at boot — wired with the D9 announce-back hook
(:func:`sevn.gateway.subagents.subagents_announce.build_announce_back_hook`) — and
exposed as ``app.state.subagent_registry`` / ``app.state.subagent_supervisor``.

W3 activates this module from ``boot_registry.py``'s bottom import chain (it
was constructed but dormant in W2). Since ``run_boot_hooks`` executes *after*
both ``build_agent_run_turn`` call sites in ``http_server.py``, the gateway
turn spine (``agent_turn.py``) reads ``router._subagent_supervisor`` lazily
per-dispatch rather than as a constructor parameter — ``http_server.py``
copies ``app.state.subagent_supervisor`` onto the router right after
``run_boot_hooks`` completes.

Examples:
    >>> from sevn.gateway import boot_registry as br
    >>> any(name == "subagents_supervisor" for _, name, _ in br._BOOT_HOOKS)
    True
"""

from __future__ import annotations

import asyncio
import sqlite3

from loguru import logger

from sevn.agent.subagents import SubAgentRegistry, SubAgentSupervisor
from sevn.agent.subagents.models import SubAgentRun
from sevn.agent.subagents.storage import (
    persist_subagent_run,
    restore_pending_subagent_deliveries,
    sqlite_persist_hook,
    sweep_orphaned_subagent_runs,
)
from sevn.agent.subagents.supervisor import PersistResultHook
from sevn.agent.tracing.subagent_trace import (
    SubAgentPrometheusCounts,
    build_subagent_trace_hook,
)
from sevn.gateway.boot_registry import BootContext, register_boot_hook
from sevn.gateway.subagents.subagents_announce import build_announce_back_hook


def _result_body_from_completion(
    result: object | None,
    error: BaseException | None,
) -> str | None:
    """Normalize a completion value into storable ``result_body`` text.

    Args:
        result (object | None): Body return value on success.
        error (BaseException | None): Body exception, or timeout/cancel marker.

    Returns:
        str | None: Text to persist, or ``None`` when there is nothing to store.

    Examples:
        >>> _result_body_from_completion("done", None)
        'done'
    """
    if error is not None:
        return f"failed: {error}"
    if isinstance(result, str) and result.strip():
        return result.strip()
    if result is not None:
        return str(result)
    return None


def build_persist_result_hook(conn: sqlite3.Connection) -> PersistResultHook:
    """Write completion text to ``subagent_runs.result_body`` (#76).

    Args:
        conn (sqlite3.Connection): Open, migrated ``sevn.db`` connection.

    Returns:
        PersistResultHook: Async callback for :class:`~sevn.agent.subagents.supervisor.SubAgentSupervisor`.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> hook = build_persist_result_hook(conn)
        >>> hook.__name__
        '_persist'
    """

    async def _persist(
        run: SubAgentRun,
        result: object | None,
        error: BaseException | None,
    ) -> None:
        body = _result_body_from_completion(result, error)
        if body is None:
            return
        await asyncio.to_thread(persist_subagent_run, conn, run, result_body=body)

    return _persist


async def _construct_subagent_supervisor(ctx: BootContext) -> None:
    """Boot hook: build the registry/supervisor pair and run the orphan sweep.

    Args:
        ctx (BootContext): Lifespan startup context.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_construct_subagent_supervisor)
        True
    """
    orphaned = sweep_orphaned_subagent_runs(ctx.conn)
    if orphaned:
        logger.bind(orphaned=orphaned).info("subagents boot sweep marked stale runs orphaned")
    restored = await restore_pending_subagent_deliveries(
        conn=ctx.conn,
        router=ctx.gateway_router,
    )
    if restored:
        logger.bind(restored=restored).info("subagents boot restored completed run deliveries")
    prometheus = SubAgentPrometheusCounts()
    registry = SubAgentRegistry(persist=sqlite_persist_hook(ctx.conn))
    registry.wire_trace(build_subagent_trace_hook(registry, prometheus=prometheus))
    ctx.app.state.subagent_prometheus = prometheus
    supervisor = SubAgentSupervisor(
        registry,
        config=ctx.workspace.subagents,
        announce_back=build_announce_back_hook(ctx.gateway_router, ctx.conn),
        persist_result=build_persist_result_hook(ctx.conn),
    )
    ctx.app.state.subagent_registry = registry
    ctx.app.state.subagent_supervisor = supervisor


def register_subagents_boot_hook() -> None:
    """Register the sub-agent supervisor construction hook.

    Called once at module import (bottom of this file). Not idempotent by
    itself — ``boot_registry.register_boot_hook`` raises on a duplicate name —
    so this is a one-shot process-boot side effect, not a callable meant to be
    invoked again later (mirrors ``register_telemetry_boot_hooks``).

    Examples:
        >>> from sevn.gateway import boot_registry as br
        >>> any(name == "subagents_supervisor" for _, name, _ in br._BOOT_HOOKS)
        True
    """
    register_boot_hook("subagents_supervisor", _construct_subagent_supervisor, priority=40)


register_subagents_boot_hook()

__all__ = ["build_persist_result_hook", "register_subagents_boot_hook"]
