"""Backend wrappers for ``/logs`` and ``/traces`` operator diagnostics.

Module: sevn.gateway.diagnostics.diagnostics
Depends: sevn.agent.tracing.redacting_sink, sevn.agent.tracing.sink,
    sevn.agent.tracing.sink_factory, sevn.channels.telegram, sevn.cli.log_redact,
    sevn.tools.log_query, sevn.ui.dashboard.query.traces, sevn.workspace.layout

Exports:
    tail_service_log — return redacted tail lines for ``gateway`` or ``proxy``.
    recent_traces — return the most-recent trace rows ordered newest first.
    get_span — fetch one span (with its descendant tree) by ``span_id``.
    format_for_telegram — wrap text payloads in ``<pre>`` chunks safe for Telegram.
    format_traces_for_telegram — render trace rows as compact JSON inside ``<pre>``.

Examples:
    >>> from sevn.gateway.diagnostics.diagnostics import tail_service_log
    >>> tail_service_log.__name__
    'tail_service_log'
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from sevn.agent.tracing.redacting_sink import TraceRedactionPolicy
from sevn.channels.telegram import chunk_text
from sevn.cli.log_redact import redact_log_line
from sevn.tools.log_query import tail_log_lines
from sevn.ui.dashboard.query.traces import (
    ensure_trace_connection,
    get_span_with_children,
    list_trace_events,
)

if TYPE_CHECKING:
    from sevn.workspace.layout import WorkspaceLayout

_KNOWN_SERVICES: frozenset[str] = frozenset({"gateway", "proxy"})


def _resolve_service_log_path(layout: WorkspaceLayout, service: str) -> Any:
    """Return ``<content_root>/logs/<service>.log`` for ``gateway`` / ``proxy``.

    Mirrors :func:`sevn.cli.log_follow.resolve_service_log_path` (line 105) but
    accepts a pre-resolved :class:`~sevn.workspace.layout.WorkspaceLayout` so
    the gateway can resolve paths without touching ``SEVN_HOME``.

    Args:
        layout (WorkspaceLayout): Resolved workspace layout.
        service (str): ``gateway`` or ``proxy``.

    Returns:
        Path: ``<content_root>/logs/<service>.log``.

    Raises:
        ValueError: When ``service`` is not one of the supported values.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> lay = WorkspaceLayout(Path("/r/sevn.json"), Path("/r"))
        >>> _resolve_service_log_path(lay, "gateway").as_posix()
        '/r/logs/gateway.log'
    """
    normalised = service.strip().lower()
    if normalised not in _KNOWN_SERVICES:
        msg = f"unknown service {service!r}; expected gateway or proxy"
        raise ValueError(msg)
    return layout.logs_dir / f"{normalised}.log"


def tail_service_log(service: str, lines: int, layout: WorkspaceLayout) -> list[str]:
    """Return the last ``lines`` redacted entries from a service log.

    Wraps :func:`sevn.tools.log_query.tail_log_lines` after resolving the path
    via :func:`_resolve_service_log_path`. Returns an empty list when the file
    does not exist; the operator surface decides how to present that.

    Args:
        service (str): ``gateway`` or ``proxy``.
        lines (int): Tail length (clamped by ``tail_log_lines`` to 1-500).
        layout (WorkspaceLayout): Resolved workspace layout.

    Returns:
        list[str]: Redacted tail lines (newest at end).

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> td = Path(tempfile.mkdtemp())
        >>> (td / "logs").mkdir()
        >>> _ = (td / "logs" / "gateway.log").write_text("a\\nb\\n", encoding="utf-8")
        >>> lay = WorkspaceLayout(td / "sevn.json", td)
        >>> tail_service_log("gateway", 5, lay)
        ['a', 'b']
    """
    path = _resolve_service_log_path(layout, service)
    matched, _existed = tail_log_lines(path, lines=lines, pattern=None)
    return matched


def recent_traces(
    layout: WorkspaceLayout,
    *,
    limit: int,
    policy: TraceRedactionPolicy | None = None,
) -> list[dict[str, object]]:
    """Return the most-recent trace rows (newest first) from ``traces.db``.

    Wraps :func:`sevn.ui.dashboard.query.traces.list_trace_events`. Returns an
    empty list when the trace database does not exist yet.

    Args:
        layout (WorkspaceLayout): Resolved workspace layout.
        limit (int): Maximum rows to return (caller clamps).
        policy (TraceRedactionPolicy | None): Redaction policy applied on read;
            defaults to :meth:`TraceRedactionPolicy.from_defaults`.

    Returns:
        list[dict[str, object]]: List of span dicts as returned by
        ``list_trace_events`` (``items`` key only — pagination metadata is
        dropped because Telegram has no cursor surface).

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> td = Path(tempfile.mkdtemp())
        >>> lay = WorkspaceLayout(td / "sevn.json", td)
        >>> recent_traces(lay, limit=5)
        []
    """
    from sevn.storage.paths import traces_sqlite_path

    db_path = traces_sqlite_path(layout.dot_sevn)
    effective_policy = policy or TraceRedactionPolicy.from_defaults()
    conn = ensure_trace_connection(db_path)
    try:
        page = list_trace_events(conn, limit=max(1, limit), policy=effective_policy)
    finally:
        conn.close()
    items = page.get("items", [])
    return list(items) if isinstance(items, list) else []


def get_span(
    layout: WorkspaceLayout,
    span_id: str,
    *,
    policy: TraceRedactionPolicy | None = None,
) -> dict[str, object] | None:
    """Return one span (with its descendant tree) or ``None`` when missing.

    Wraps :func:`sevn.ui.dashboard.query.traces.get_span_with_children`.

    Args:
        layout (WorkspaceLayout): Resolved workspace layout.
        span_id (str): Span primary key.
        policy (TraceRedactionPolicy | None): Redaction policy applied on read;
            defaults to :meth:`TraceRedactionPolicy.from_defaults`.

    Returns:
        dict[str, object] | None: Span tree dict or ``None`` when the row is
        absent (also returned when the trace database has not been created).

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> td = Path(tempfile.mkdtemp())
        >>> lay = WorkspaceLayout(td / "sevn.json", td)
        >>> get_span(lay, "missing") is None
        True
    """
    from sevn.storage.paths import traces_sqlite_path

    db_path = traces_sqlite_path(layout.dot_sevn)
    effective_policy = policy or TraceRedactionPolicy.from_defaults()
    conn = ensure_trace_connection(db_path)
    try:
        return get_span_with_children(conn, span_id, policy=effective_policy)
    finally:
        conn.close()


def _stringify_payload(payload: str | list[str]) -> str:
    """Join a list payload with newlines or return ``payload`` unchanged.

    Args:
        payload (str | list[str]): Source text from log/trace helpers.

    Returns:
        str: Single string ready for chunking.

    Examples:
        >>> _stringify_payload(["a", "b"])
        'a\\nb'
        >>> _stringify_payload("a\\nb")
        'a\\nb'
    """
    if isinstance(payload, list):
        return "\n".join(str(item) for item in payload)
    return str(payload)


def format_for_telegram(
    payload: str | list[str],
    *,
    redaction: TraceRedactionPolicy | None = None,
) -> list[str]:
    """Apply log-line redaction (when enabled) and wrap the payload in chunked ``<pre>`` blocks.

    Log payloads receive :func:`sevn.cli.log_redact.redact_log_line` per line
    when ``redaction`` is enabled (the trace-attribute policy is consumed at
    SQL read time by :func:`list_trace_events`). The resulting text is sliced
    via :func:`sevn.channels.telegram.chunk_text` (UTF-16 aware) so each chunk
    fits within Telegram's per-message limit when wrapped in ``<pre>...</pre>``
    HTML.

    Args:
        payload (str | list[str]): Source text. List entries are joined with
            ``\\n`` after per-line redaction.
        redaction (TraceRedactionPolicy | None): Workspace redaction rules;
            ``None`` or ``enabled=False`` disables line-level redaction.

    Returns:
        list[str]: ``<pre>``-wrapped chunks ready to send to Telegram. Returns
        a single placeholder chunk when ``payload`` is empty so callers can
        always send something.

    Examples:
        >>> chunks = format_for_telegram("token=abc123", redaction=None)
        >>> len(chunks) == 1 and chunks[0].startswith("<pre>")
        True
        >>> from sevn.agent.tracing.redacting_sink import TraceRedactionPolicy
        >>> policy = TraceRedactionPolicy.from_defaults()
        >>> out = format_for_telegram(["token=abc123"], redaction=policy)
        >>> "abc123" not in out[0]
        True
    """
    body = _stringify_payload(payload)
    enabled = bool(redaction and redaction.enabled)
    if enabled and body:
        body = "\n".join(redact_log_line(line) for line in body.splitlines())
    if not body:
        return ["<pre>(empty)</pre>"]
    open_tag = "<pre>"
    close_tag = "</pre>"
    wrapper_overhead = len(open_tag) + len(close_tag)
    from sevn.config.defaults import TELEGRAM_MAX_TEXT_LENGTH

    inner_budget = max(1, TELEGRAM_MAX_TEXT_LENGTH - wrapper_overhead)
    pieces = chunk_text(body, max_utf16=inner_budget)
    return [f"{open_tag}{piece}{close_tag}" for piece in pieces]


def format_traces_for_telegram(
    spans: list[dict[str, object]],
    *,
    redaction: TraceRedactionPolicy | None = None,
) -> list[str]:
    """Render trace rows as compact JSON lines, then delegate to :func:`format_for_telegram`.

    Trace ``attrs`` are already redacted at read time by ``list_trace_events``
    when ``redaction.enabled`` is true; this helper only handles serialisation.

    Args:
        spans (list[dict[str, object]]): Rows from :func:`recent_traces`.
        redaction (TraceRedactionPolicy | None): Forwarded for log-line scrubbing
            of the serialised payload (defence in depth).

    Returns:
        list[str]: ``<pre>``-wrapped chunks ready to send to Telegram.

    Examples:
        >>> format_traces_for_telegram([], redaction=None)
        ['<pre>(empty)</pre>']
    """
    lines: list[str] = []
    for span in spans:
        try:
            lines.append(json.dumps(span, default=str, ensure_ascii=False, separators=(",", ":")))
        except (TypeError, ValueError):
            lines.append(repr(span))
    return format_for_telegram(lines, redaction=redaction)


__all__ = [
    "format_for_telegram",
    "format_traces_for_telegram",
    "get_span",
    "recent_traces",
    "tail_service_log",
]
