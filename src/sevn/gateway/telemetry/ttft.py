"""First-token (TTFT) instrumentation and turn-startup deferral seams (#78, W30).

Module: sevn.gateway.telemetry.ttft
Depends: sevn.agent.tracing.sink, sevn.config.sections.accessors

Exports:
    DeferredTurnResult — turn output from deferred-discovery test seam.
    TurnStartupTimings — wall-clock samples for turn-startup contributors.
    record_ttft_sample — emit a ``gateway.turn.ttft`` trace row.
    extract_ttft_ms_from_events — read TTFT ms from collected trace events.
    run_turn_with_deferred_mcp_discovery — boot-path parity test seam.
    log_turn_startup_timings — structured log for before/after measurements.
    resolve_mcp_tool_definitions_lazy — lazy MCP discovery when deferral enabled.
    SessionRegistryTurnCache — opt-in per-turn registry snapshot cache (W15 seam).
    session_registry_cache_key — fingerprint for registry cache hits.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from time import time_ns
from typing import TYPE_CHECKING, Any

from loguru import logger

from sevn.config.sections.accessors import defer_mcp_discovery_enabled
from sevn.config.sections.root import WorkspaceConfig

if TYPE_CHECKING:
    from sevn.agent.tracing.sink import TraceEvent, TraceSink
    from sevn.tools.base import ToolDefinition
    from sevn.tools.registry import ToolSet

TTFT_SPAN_KIND: str = "gateway.turn.ttft"
"""Stable span kind for first-token latency (Mission Control + trace export)."""


@dataclass(frozen=True, slots=True)
class DeferredTurnResult:
    """Turn output from :func:`run_turn_with_deferred_mcp_discovery`."""

    text: str


@dataclass(slots=True)
class TurnStartupTimings:
    """Wall-clock samples for turn-startup contributors (W30.2)."""

    build_session_registry_ms: float | None = None
    sync_tools_md_ms: float | None = None
    triage_ms: float | None = None
    mcp_discovery_ms: float | None = None


async def record_ttft_sample(
    trace: TraceSink | None,
    *,
    session_id: str,
    turn_id: str,
    ttft_ms: float,
    span_id: str | None = None,
) -> None:
    """Emit a ``gateway.turn.ttft`` trace event with latency in milliseconds.

    Args:
        trace (TraceSink | None): Gateway trace sink (no-op when ``None``).
        session_id (str): Owning session id.
        turn_id (str): Turn correlation id.
        ttft_ms (float): First outbound assistant token latency in ms.
        span_id (str | None): Optional fixed span id.

    Examples:
        >>> import asyncio
        >>> asyncio.run(record_ttft_sample(None, session_id="s", turn_id="t", ttft_ms=1.0))
    """
    if trace is None or ttft_ms <= 0:
        return
    from sevn.agent.tracing.sink import TraceEvent

    now = time_ns()
    await trace.emit(
        TraceEvent(
            kind=TTFT_SPAN_KIND,
            span_id=span_id or uuid.uuid4().hex,
            parent_span_id=None,
            session_id=session_id,
            turn_id=turn_id,
            tier=None,
            ts_start_ns=now,
            ts_end_ns=now,
            status="completed",
            attrs={"ttft_ms": float(ttft_ms)},
        )
    )


def extract_ttft_ms_from_events(events: Sequence[TraceEvent]) -> float | None:
    """Return the most recent TTFT sample from trace events.

    Args:
        events (Sequence[TraceEvent]): Collected gateway trace rows.

    Returns:
        float | None: TTFT milliseconds when a span is present.

    Examples:
        >>> extract_ttft_ms_from_events(())
        >>> extract_ttft_ms_from_events([]) is None
        True
    """
    for event in reversed(events):
        if event.kind != TTFT_SPAN_KIND:
            continue
        raw = event.attrs.get("ttft_ms")
        if isinstance(raw, (int, float)) and float(raw) > 0:
            return float(raw)
    return None


async def run_turn_with_deferred_mcp_discovery(
    *,
    workspace: WorkspaceConfig,
    defer_mcp_discovery: bool,
    executor: Callable[..., Awaitable[str]],
) -> DeferredTurnResult:
    """Run *executor* after optional eager MCP discovery (boot-path parity seam).

    When ``defer_mcp_discovery`` is ``True``, MCP subprocess discovery is skipped
    before the executor — matching the deferred boot path. Turn text must match.

    Args:
        workspace (WorkspaceConfig): Parsed workspace config.
        defer_mcp_discovery (bool): When ``False``, run discovery before executor.
        executor (Callable[..., Awaitable[str]]): Async callable returning turn text.

    Returns:
        DeferredTurnResult: Executor output wrapper.

    Examples:
        >>> import asyncio
        >>> async def _exec() -> str:
        ...     return "ok"
        >>> asyncio.run(
        ...     run_turn_with_deferred_mcp_discovery(
        ...         workspace=WorkspaceConfig.minimal(),
        ...         defer_mcp_discovery=True,
        ...         executor=_exec,
        ...     )
        ... ).text
        'ok'
    """
    from sevn.code_understanding.graphify_mcp import build_effective_mcp_servers
    from sevn.tools.mcp_stdio_client import discover_mcp_tool_definitions

    content_root = Path(workspace.workspace_root or ".")
    servers = build_effective_mcp_servers(workspace, content_root)
    if not defer_mcp_discovery and servers:
        await discover_mcp_tool_definitions(servers, workspace_path=content_root)
    text = await executor()
    return DeferredTurnResult(text=text)


def session_registry_cache_key(
    *,
    workspace_fingerprint: str,
    mcp_tool_names: tuple[str, ...],
    include_bootstrap_tools: bool,
) -> str:
    """Build a stable cache key for per-turn session registry snapshots (W30.4 / W15 seam).

    Args:
        workspace_fingerprint (str): Workspace/tool-config digest.
        mcp_tool_names (tuple[str, ...]): Sorted MCP tool qualified names.
        include_bootstrap_tools (bool): Bootstrap tool inclusion flag.

    Returns:
        str: Hex digest suitable for :class:`SessionRegistryTurnCache`.

    Examples:
        >>> session_registry_cache_key(
        ...     workspace_fingerprint="abc",
        ...     mcp_tool_names=("mcp__demo__ping",),
        ...     include_bootstrap_tools=False,
        ... )[:8]
        'd4f2f843'
    """
    payload = "|".join(
        (
            workspace_fingerprint,
            ",".join(sorted(mcp_tool_names)),
            "1" if include_bootstrap_tools else "0",
        )
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class SessionRegistryTurnCache:
    """Opt-in in-process cache for ``build_session_registry`` snapshots (W30.4).

    Shares the fingerprint seam planned for W15 ``skills.discovery_cache`` — callers
    pass the same digest inputs rather than maintaining a competing cache tree.
    """

    def __init__(self) -> None:
        """Create an empty in-process registry snapshot cache.

        Examples:
            >>> SessionRegistryTurnCache()._entries
            {}
        """
        self._entries: dict[str, tuple[Any, ToolSet]] = {}

    def get(self, key: str) -> tuple[Any, ToolSet] | None:
        """Return a cached ``(executor, tool_set)`` pair on hit.

        Args:
            key (str): Cache fingerprint from :func:`session_registry_cache_key`.

        Returns:
            tuple[Any, ToolSet] | None: Cached pair, or ``None`` on miss.

        Examples:
            >>> c = SessionRegistryTurnCache()
            >>> c.get("missing") is None
            True
        """
        return self._entries.get(key)

    def put(self, key: str, value: tuple[Any, ToolSet]) -> None:
        """Store a registry snapshot under *key*.

        Args:
            key (str): Cache fingerprint.
            value (tuple[Any, ToolSet]): ``build_session_registry`` result.

        Examples:
            >>> c = SessionRegistryTurnCache()
            >>> c.put("k", (object(), object()))  # doctest: +ELLIPSIS
        """
        self._entries[key] = value

    def clear(self) -> None:
        """Drop all cached snapshots (e.g. after config reload).

        Examples:
            >>> SessionRegistryTurnCache().clear()
        """
        self._entries.clear()


def log_turn_startup_timings(
    *,
    session_id: str,
    timings: TurnStartupTimings,
    defer_mcp: bool,
    cache_hit: bool,
) -> None:
    """Log measured turn-startup contributors for before/after comparisons (W30.2/5).

    Args:
        session_id (str): Gateway session id.
        timings (TurnStartupTimings): Stage samples in milliseconds.
        defer_mcp (bool): Whether deferred MCP discovery is enabled.
        cache_hit (bool): Whether session registry cache was used.

    Examples:
        >>> log_turn_startup_timings(
        ...     session_id="s1",
        ...     timings=TurnStartupTimings(build_session_registry_ms=12.0),
        ...     defer_mcp=False,
        ...     cache_hit=False,
        ... )
    """
    logger.info(
        "gateway_turn_startup_timings session_id={} defer_mcp={} registry_cache_hit={} "
        "build_session_registry_ms={} sync_tools_md_ms={} triage_ms={} mcp_discovery_ms={}",
        session_id,
        defer_mcp,
        cache_hit,
        timings.build_session_registry_ms,
        timings.sync_tools_md_ms,
        timings.triage_ms,
        timings.mcp_discovery_ms,
    )


_MCP_DISCOVERY_LOCK = asyncio.Lock()


async def resolve_mcp_tool_definitions_lazy(
    *,
    workspace: WorkspaceConfig,
    content_root: Path,
    mcp_defs_box: list[tuple[ToolDefinition, ...]],
    mcp_servers_map: dict[str, dict[str, Any]] | None = None,
) -> tuple[ToolDefinition, ...]:
    """Return MCP tool defs, discovering lazily when deferral is enabled (W30.3).

    Args:
        workspace (WorkspaceConfig): Parsed workspace config.
        content_root (Path): Workspace content root.
        mcp_defs_box (list[tuple[ToolDefinition, ...]]): Mutable holder updated in-place.
        mcp_servers_map (dict[str, dict[str, Any]] | None): Pre-built server map.

    Returns:
        tuple[ToolDefinition, ...]: Current MCP tool definitions.

    Examples:
        >>> import asyncio
        >>> asyncio.run(
        ...     resolve_mcp_tool_definitions_lazy(
        ...         workspace=WorkspaceConfig.minimal(),
        ...         content_root=Path("."),
        ...         mcp_defs_box=[()],
        ...     )
        ... )
        ()
    """
    if mcp_defs_box and mcp_defs_box[0]:
        return mcp_defs_box[0]
    if not defer_mcp_discovery_enabled(workspace):
        return mcp_defs_box[0] if mcp_defs_box else ()
    from sevn.code_understanding.graphify_mcp import build_effective_mcp_servers
    from sevn.tools.mcp_stdio_client import discover_mcp_tool_definitions

    async with _MCP_DISCOVERY_LOCK:
        if mcp_defs_box and mcp_defs_box[0]:
            return mcp_defs_box[0]
        servers = (
            mcp_servers_map
            if mcp_servers_map is not None
            else build_effective_mcp_servers(workspace, content_root)
        )
        if not servers:
            return ()
        started = time_ns()
        defs = await discover_mcp_tool_definitions(servers, workspace_path=content_root)
        elapsed_ms = max(0.1, (time_ns() - started) / 1_000_000)
        logger.debug(
            "gateway_mcp_discovery_lazy content_root={} servers={} tools={} ms={:.1f}",
            content_root,
            len(servers),
            len(defs),
            elapsed_ms,
        )
        if mcp_defs_box:
            mcp_defs_box[:] = [defs]
        return defs


__all__ = [
    "TTFT_SPAN_KIND",
    "DeferredTurnResult",
    "SessionRegistryTurnCache",
    "TurnStartupTimings",
    "extract_ttft_ms_from_events",
    "log_turn_startup_timings",
    "record_ttft_sample",
    "resolve_mcp_tool_definitions_lazy",
    "run_turn_with_deferred_mcp_discovery",
    "session_registry_cache_key",
]
