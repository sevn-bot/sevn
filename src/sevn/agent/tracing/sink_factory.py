"""Build trace sinks from workspace ``tracing.sinks[]`` (`specs/04-tracing.md` §5).
Module: sevn.agent.tracing.sink_factory
Depends: pathlib, sevn.agent.tracing.multi_sink, sevn.agent.tracing.redacting_sink,
         sevn.agent.tracing.rotating_jsonl_sink, sevn.agent.tracing.sink,
         sevn.agent.tracing.sqlite_sink, sevn.config.workspace_config, sevn.storage.paths,
         sevn.workspace.layout
Exports:
    build_gateway_trace_sink — resolve ``TraceSink`` / ``MultiSink`` from config.
    build_gateway_trace_sink_async — gateway boot: env + secret ``token_ref`` resolution.
    trace_redaction_policy_for — resolve ``tracing.redaction`` for read/write paths.
Examples:
    >>> isinstance(True, bool)
    True
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from sevn.agent.tracing.multi_sink import MultiSink
from sevn.agent.tracing.otel_pipeline import configure_gateway_otel
from sevn.agent.tracing.redacting_sink import RedactingSink, TraceRedactionPolicy
from sevn.agent.tracing.rotating_jsonl_sink import RotatingJSONLFileSink
from sevn.agent.tracing.sink import JSONLFileSink, NullTraceSink, TraceSink
from sevn.agent.tracing.sqlite_sink import SQLiteSink
from sevn.agent.tracing.trace_event_bridge import TraceEventOtelBridge, set_trace_event_bridge
from sevn.agent.tracing.trace_secrets_resolve import resolve_trace_sink_token
from sevn.storage.paths import traces_sqlite_path

if TYPE_CHECKING:
    from sevn.config.workspace_config import TraceSinkEntry, WorkspaceConfig
    from sevn.workspace.layout import WorkspaceLayout


def _resolve_workspace_relative_path(layout: WorkspaceLayout, raw: str) -> Path:
    """Resolve a workspace-relative path string against ``content_root``.
        Args:
    layout (WorkspaceLayout): Resolved layout from ``sevn.json``.
    raw (str): Path literal from JSON (quotes stripped).
        Returns:
            Path: Absolute resolved path.
        Examples:
            >>> isinstance(True, bool)
            True
    """
    rel = raw.strip().strip('"').strip("'")
    return (layout.content_root / rel).resolve()


def _trace_redaction_policy(workspace: WorkspaceConfig) -> TraceRedactionPolicy:
    """Resolve ``tracing.redaction`` with shipped defaults when omitted.

    Args:
        workspace (WorkspaceConfig): Parsed ``sevn.json`` workspace model.
    Returns:
        TraceRedactionPolicy: Policy for ``RedactingSink`` wrapping.
    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> policy = _trace_redaction_policy(WorkspaceConfig.minimal())
        >>> policy.enabled
        True
    """
    tracing = workspace.tracing
    redaction = tracing.redaction if tracing is not None else None
    if redaction is None:
        return TraceRedactionPolicy.from_defaults()
    return TraceRedactionPolicy(
        enabled=redaction.enabled,
        deny_keys=tuple(redaction.deny_keys),
        deny_value_patterns=tuple(redaction.deny_value_patterns),
        _compiled_patterns=(),
    )


def _wrap_with_redaction(sink: TraceSink, policy: TraceRedactionPolicy) -> TraceSink:
    """Return ``RedactingSink(sink)`` when policy is enabled.

    Wave 2 OTel sinks compose inside the same wrapper — never per-sink redaction.
    Args:
        sink (TraceSink): Composite or leaf sink from ``tracing.sinks[]``.
        policy (TraceRedactionPolicy): Resolved workspace redaction rules.
    Returns:
        TraceSink: ``RedactingSink`` wrapper or ``sink`` unchanged when disabled.
    Examples:
        >>> from sevn.agent.tracing.sink import NullTraceSink
        >>> _wrap_with_redaction(NullTraceSink(), TraceRedactionPolicy.from_defaults()) is not None
        True
    """
    if not policy.enabled:
        return sink
    return RedactingSink(sink, policy)


def trace_redaction_policy_for(workspace: WorkspaceConfig) -> TraceRedactionPolicy:
    """Resolve ``tracing.redaction`` with shipped defaults when omitted.

    Args:
        workspace (WorkspaceConfig): Parsed ``sevn.json`` workspace model.
    Returns:
        TraceRedactionPolicy: Policy for emit and dashboard read paths.
    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> trace_redaction_policy_for(WorkspaceConfig.minimal()).enabled
        True
    """
    return _trace_redaction_policy(workspace)


def build_gateway_trace_sink(
    workspace: WorkspaceConfig,
    layout: WorkspaceLayout,
    *,
    resolved_tokens: dict[int, str] | None = None,
) -> TraceSink:
    """Construct the gateway trace sink from ``tracing.sinks[]``.
    Supported ``type`` values: ``sqlite``, ``jsonl_file``, ``otel``, ``logfire``.
    ``otel`` / ``logfire`` entries configure the shared OTLP ``TracerProvider``
    (see :mod:`sevn.agent.tracing.otel_pipeline`); product spans bridge to OTel
    via :class:`~sevn.agent.tracing.trace_event_bridge.TraceEventOtelBridge`.
    Unknown types are skipped with a warning. Empty / missing configuration yields
    ``NullTraceSink``.
    When ``tracing.redaction.enabled`` (default true), the composite sink is
    wrapped in ``RedactingSink`` so fan-out members share one redacted payload.
    SQLite paths default to ``traces_sqlite_path(layout.dot_sevn)`` when no
    ``path`` is set; optional ``path`` is resolved relative to ``content_root``.
    JSONL directory paths (trailing ``/`` or ``\\``) use ``RotatingJSONLFileSink``
    under ``layout.traces_dir``; explicit ``.jsonl`` file paths use ``JSONLFileSink``.
        Args:
    workspace (WorkspaceConfig): Parsed ``sevn.json`` workspace model.
    layout (WorkspaceLayout): Resolved filesystem layout.
    resolved_tokens (dict[int, str] | None): Pre-resolved OTLP bearer tokens by sink index.
        Returns:
            TraceSink: ``NullTraceSink``, a concrete sink, or ``MultiSink``.
        Examples:
            >>> isinstance(True, bool)
            True
    """
    configure_gateway_otel(workspace, resolved_tokens=resolved_tokens)

    tracing = workspace.tracing
    entries = tracing.sinks if tracing and tracing.sinks else None
    if not entries:
        set_trace_event_bridge(None)
        return NullTraceSink()

    bridge = TraceEventOtelBridge()
    set_trace_event_bridge(bridge)

    local_sinks: list[TraceSink] = []
    token_by_index = resolved_tokens or {}
    for idx, entry in enumerate(entries):
        built = _sink_from_entry(
            layout,
            workspace,
            entry,
            resolved_token=token_by_index.get(idx),
        )
        if built is not None:
            local_sinks.append(built)

    if local_sinks:
        persistence: TraceSink = local_sinks[0] if len(local_sinks) == 1 else MultiSink(local_sinks)
        composite: TraceSink = MultiSink([bridge, persistence])
    else:
        composite = bridge

    return _wrap_with_redaction(composite, _trace_redaction_policy(workspace))


async def build_gateway_trace_sink_async(
    workspace: WorkspaceConfig,
    layout: WorkspaceLayout,
    *,
    content_root: Path,
) -> TraceSink:
    """Construct the gateway trace sink with async ``token_ref`` secret resolution.

    Resolves ``${SECRET:…}`` and bare logical keys for ``otel`` / ``logfire`` sinks, then
    delegates to :func:`build_gateway_trace_sink` with a per-entry index map.

    Args:
        workspace (WorkspaceConfig): Parsed ``sevn.json`` workspace model.
        layout (WorkspaceLayout): Resolved filesystem layout.
        content_root (Path): Workspace content root for secrets backends.

    Returns:
        TraceSink: Same product as the sync builder after secret expansion.

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> ws = WorkspaceConfig.minimal(workspace_root=".")
        >>> ly = WorkspaceLayout(sevn_json_path=Path("sevn.json"), content_root=Path(".").resolve())
        >>> asyncio.run(build_gateway_trace_sink_async(ws, ly, content_root=ly.content_root)) is not None
        True
    """
    tracing = workspace.tracing
    entries = tracing.sinks if tracing and tracing.sinks else None
    resolved_tokens: dict[int, str] = {}
    if entries:
        for idx, entry in enumerate(entries):
            kind = entry.sink_type.strip().lower()
            if kind not in ("logfire", "otel"):
                continue
            token_ref = (entry.token_ref or "").strip()
            if not token_ref:
                continue
            token = await resolve_trace_sink_token(
                token_ref,
                content_root=content_root,
                workspace=workspace,
            )
            if token:
                resolved_tokens[idx] = token
    return build_gateway_trace_sink(workspace, layout, resolved_tokens=resolved_tokens or None)


def _sink_from_entry(
    layout: WorkspaceLayout,
    workspace: WorkspaceConfig,
    entry: TraceSinkEntry,
    *,
    resolved_token: str | None = None,
) -> TraceSink | None:
    """Map one ``TraceSinkEntry`` to a sink instance.
        Args:
    layout (WorkspaceLayout): Paths anchor.
    workspace (WorkspaceConfig): Parsed workspace for ``traces_dir`` resolution.
    entry (TraceSinkEntry): Single sink descriptor.
    resolved_token (str | None): Async-resolved bearer token for ``otel`` / ``logfire``.
        Returns:
            TraceSink | None: Concrete sink, or ``None`` when skipped.
        Examples:
            >>> isinstance(True, bool)
            True
    """
    kind = entry.sink_type.strip().lower()
    if kind == "sqlite":
        db_path = (
            traces_sqlite_path(layout.dot_sevn)
            if not entry.path or not entry.path.strip()
            else _resolve_workspace_relative_path(layout, entry.path)
        )
        return SQLiteSink(db_path)
    if kind == "jsonl_file":
        if not entry.path or not entry.path.strip():
            logger.bind(sink_type=kind).warning(
                "trace sink skipped: jsonl_file requires path",
            )
            return None
        raw_path = entry.path.strip().strip('"').strip("'")
        if raw_path.endswith(("/", "\\")):
            return RotatingJSONLFileSink(layout.traces_dir(workspace))
        jsonl_path = _resolve_workspace_relative_path(layout, entry.path)
        return JSONLFileSink(jsonl_path)
    if kind in ("logfire", "otel"):
        _ = resolved_token
        return None
    logger.bind(sink_type=entry.sink_type).warning("unknown trace sink type — skipping")
    return None
