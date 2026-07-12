"""CLI reader for ``traces.db`` wrapping dashboard query helpers (W6, D2).

Module: sevn.cli.traces_read
Depends: dataclasses, datetime, pathlib, sqlite3, typing, sevn.agent.tracing.redacting_sink,
    sevn.cli.log_follow, sevn.storage.paths, sevn.ui.dashboard.query.traces

Exports:
    SpanNode — one span node in a turn tree.
    load_trace_turns — span-grouped turns/sessions from ``traces.db``.
    turn_to_span_tree_node — map one turn payload to :class:`SpanTreeNode`.
    traces_drilldown_hint — suggested ``sevn traces`` command for a session id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from sevn.agent.tracing.redacting_sink import TraceRedactionPolicy
from sevn.cli.log_follow import _parse_since_window
from sevn.cli.render.tree import SpanTreeNode
from sevn.storage.paths import traces_sqlite_path
from sevn.ui.dashboard.query.traces import ensure_trace_connection, list_trace_events


@dataclass
class SpanNode:
    """One span node in a turn tree."""

    span_id: str
    kind: str
    tier: str | None
    status: str
    duration_ms: float | None
    attrs: dict[str, object]
    children: list[SpanNode] = field(default_factory=list)


def _span_duration_ms(span: dict[str, object]) -> float | None:
    """Return span duration in milliseconds when both timestamps exist.

    Args:
        span (dict[str, object]): Span dict from dashboard readers.

    Returns:
        float | None: Duration in ms or ``None`` when incomplete.

    Examples:
        >>> _span_duration_ms({"ts_start_ns": 0, "ts_end_ns": 2_000_000})
        2.0
    """
    start = span.get("ts_start_ns")
    end = span.get("ts_end_ns")
    if start is None or end is None:
        return None
    try:
        return round((int(str(end)) - int(str(start))) / 1_000_000, 1)
    except (TypeError, ValueError):
        return None


def _span_label(span: dict[str, object]) -> str:
    """Build a human label for one span (kind + optional tool name).

    Args:
        span (dict[str, object]): Span dict with ``kind`` and optional ``attrs``.

    Returns:
        str: Display label for tree rendering.

    Examples:
        >>> _span_label({"kind": "tool.invoke", "attrs": {"tool_name": "read_file"}})
        'tool.invoke read_file'
    """
    kind = str(span.get("kind") or "span")
    attrs = span.get("attrs")
    if isinstance(attrs, dict):
        for key in ("tool_name", "name", "tool", "model_id"):
            value = attrs.get(key)
            if isinstance(value, str) and value.strip():
                return f"{kind} {value.strip()}"
    return kind


def _attach_turn_children(
    span: dict[str, object],
    children_by_parent: dict[str, list[dict[str, object]]],
) -> SpanNode:
    """Recursively build :class:`SpanNode` for one span and descendants.

    Args:
        span (dict[str, object]): Parent span row.
        children_by_parent (dict[str, list[dict[str, object]]]): Adjacency map.

    Returns:
        SpanNode: Nested span tree rooted at ``span``.

    Examples:
        >>> node = _attach_turn_children(
        ...     {"span_id": "r", "kind": "root", "status": "ok", "ts_start_ns": 0},
        ...     {},
        ... )
        >>> node.span_id
        'r'
    """
    span_id = str(span["span_id"])
    kids = sorted(
        children_by_parent.get(span_id, []),
        key=lambda row: int(str(row["ts_start_ns"])),
    )
    attrs_raw = span.get("attrs")
    attrs = dict(attrs_raw) if isinstance(attrs_raw, dict) else {}
    return SpanNode(
        span_id=span_id,
        kind=str(span.get("kind") or "span"),
        tier=str(span["tier"]) if span.get("tier") is not None else None,
        status=str(span.get("status") or "ok"),
        duration_ms=_span_duration_ms(span),
        attrs=attrs,
        children=[_attach_turn_children(child, children_by_parent) for child in kids],
    )


def _span_node_to_dict(node: SpanNode) -> dict[str, object]:
    """Serialize one :class:`SpanNode` for ``--json`` output.

    Args:
        node (SpanNode): Span tree node.

    Returns:
        dict[str, object]: JSON-serializable span dict with nested children.

    Examples:
        >>> _span_node_to_dict(SpanNode("s1", "k", None, "ok", 1.0, {}, []))
        {'span_id': 's1', 'kind': 'k', 'tier': None, 'status': 'ok', 'duration_ms': 1.0, 'attrs': {}, 'children': []}
    """
    return {
        "span_id": node.span_id,
        "kind": node.kind,
        "tier": node.tier,
        "status": node.status,
        "duration_ms": node.duration_ms,
        "attrs": node.attrs,
        "children": [_span_node_to_dict(child) for child in node.children],
    }


def _span_node_to_tree(node: SpanNode) -> SpanTreeNode:
    """Convert :class:`SpanNode` to :class:`SpanTreeNode` for Rich/plain trees.

    Args:
        node (SpanNode): Internal span node.

    Returns:
        SpanTreeNode: Render-ready tree node.

    Examples:
        >>> tree = _span_node_to_tree(SpanNode("s1", "tool.invoke", None, "ok", 5.0, {"tool_name": "x"}, []))
        >>> tree.label
        'tool.invoke x'
    """
    return SpanTreeNode(
        label=_span_label({"kind": node.kind, "attrs": node.attrs}),
        duration_ms=node.duration_ms,
        status=node.status,
        children=[_span_node_to_tree(child) for child in node.children],
    )


def _build_turn_tree(spans: list[dict[str, object]]) -> list[SpanNode]:
    """Build root span trees for one turn's flat span rows.

    Args:
        spans (list[dict[str, object]]): All spans for one turn.

    Returns:
        list[SpanNode]: Root nodes ordered by ``ts_start_ns``.

    Examples:
        >>> roots = _build_turn_tree([
        ...     {"span_id": "a", "parent_span_id": None, "kind": "k", "status": "ok", "ts_start_ns": 1},
        ... ])
        >>> len(roots)
        1
    """
    by_id = {str(span["span_id"]): span for span in spans}
    children_by_parent: dict[str, list[dict[str, object]]] = {}
    for span in spans:
        parent = span.get("parent_span_id")
        if parent and str(parent) in by_id:
            children_by_parent.setdefault(str(parent), []).append(span)
    roots = [
        span
        for span in spans
        if not span.get("parent_span_id") or str(span.get("parent_span_id")) not in by_id
    ]
    roots.sort(key=lambda row: int(str(row["ts_start_ns"])))
    return [_attach_turn_children(root, children_by_parent) for root in roots]


def _turn_status(spans: list[dict[str, object]]) -> str:
    """Return the worst status across spans in one turn.

    Args:
        spans (list[dict[str, object]]): Spans in one turn.

    Returns:
        str: ``ok`` or ``error``.

    Examples:
        >>> _turn_status([{"status": "ok"}, {"status": "ERROR"}])
        'error'
    """
    for span in spans:
        if str(span.get("status") or "ok").lower() not in {"ok", "success"}:
            return "error"
    return "ok"


def _since_ns(since: str | None) -> int:
    """Convert ``--since`` to inclusive ``ts_start_ns`` cutoff.

    Args:
        since (str | None): Lookback window (e.g. ``1h``) or ``None`` for default.

    Returns:
        int: Nanosecond timestamp cutoff.

    Examples:
        >>> cutoff = _since_ns("24h")
        >>> cutoff > 0
        True
    """
    window = _parse_since_window(since)
    cutoff = datetime.now(UTC) - window
    return int(cutoff.timestamp() * 1_000_000_000)


def _fetch_session_spans(
    conn: object,
    *,
    session_id: str,
    since_ns: int,
    policy: TraceRedactionPolicy,
) -> list[dict[str, object]]:
    """Load all spans for one session within the since window.

    Args:
        conn (object): Open SQLite connection from :func:`ensure_trace_connection`.
        session_id (str): Gateway session id filter.
        since_ns (int): Inclusive ``ts_start_ns`` cutoff.
        policy (TraceRedactionPolicy): Redaction policy for attrs.

    Returns:
        list[dict[str, object]]: Span rows sorted by start time.

    Examples:
        >>> import sqlite3
        >>> from sevn.agent.tracing.traces_migrate import apply_traces_migrations
        >>> _conn = sqlite3.connect(":memory:")
        >>> apply_traces_migrations(_conn)
        >>> _fetch_session_spans(
        ...     _conn, session_id="sess", since_ns=0, policy=TraceRedactionPolicy.from_defaults()
        ... )
        []
    """
    page = list_trace_events(
        conn,  # type: ignore[arg-type]
        limit=10_000,
        policy=policy,
        session_id=session_id,
        ts_from_ns=since_ns,
    )
    raw_items = page.get("items")
    items = cast("list[dict[str, object]]", raw_items) if isinstance(raw_items, list) else []
    items.sort(key=lambda row: int(str(row["ts_start_ns"])))
    return items


def _list_recent_sessions(conn: object, *, since_ns: int, limit: int) -> list[str]:
    """Return distinct session ids ordered by latest span start (desc).

    Args:
        conn (object): Open SQLite connection.
        since_ns (int): Inclusive ``ts_start_ns`` cutoff.
        limit (int): Max sessions to return.

    Returns:
        list[str]: Session ids newest-first.

    Examples:
        >>> import sqlite3
        >>> from sevn.agent.tracing.traces_migrate import apply_traces_migrations
        >>> _conn = sqlite3.connect(":memory:")
        >>> apply_traces_migrations(_conn)
        >>> _list_recent_sessions(_conn, since_ns=0, limit=5)
        []
    """
    rows = conn.execute(  # type: ignore[attr-defined]
        """
        SELECT session_id, MAX(ts_start_ns) AS latest_ns
        FROM trace_events
        WHERE ts_start_ns >= ?
        GROUP BY session_id
        ORDER BY latest_ns DESC
        LIMIT ?
        """,
        (since_ns, limit),
    ).fetchall()
    return [str(row[0]) for row in rows]


def load_trace_turns(
    dot_sevn: Path,
    *,
    session_id: str | None = None,
    last: int = 5,
    since: str | None = None,
    policy: TraceRedactionPolicy | None = None,
) -> list[dict[str, object]]:
    """Load span-grouped turns from ``traces.db``.

    Groups spans by ``(session_id, turn_id)`` and nests children via
    ``parent_span_id``. Reuses dashboard :func:`list_trace_events` (D2).

    Args:
        dot_sevn (Path): ``.sevn`` directory containing ``traces.db``.
        session_id (str | None): Filter to one session; when omitted, recent sessions.
        last (int): Max turns to return (newest first).
        since (str | None): Lookback window passed to :func:`_parse_since_window`.
        policy (TraceRedactionPolicy | None): Redaction policy; defaults when omitted.

    Returns:
        list[dict[str, object]]: Turn payloads with nested ``spans`` trees.

    Examples:
        >>> load_trace_turns(Path("/nonexistent/.sevn"))
        []
    """
    db_path = traces_sqlite_path(dot_sevn)
    if not db_path.is_file():
        return []
    effective_policy = policy or TraceRedactionPolicy.from_defaults()
    since_cutoff = _since_ns(since)
    try:
        conn = ensure_trace_connection(db_path)
    except OSError:
        return []
    try:
        session_ids = (
            [session_id]
            if session_id
            else _list_recent_sessions(conn, since_ns=since_cutoff, limit=max(last, 20))
        )
        turns: list[dict[str, object]] = []
        for sid in session_ids:
            spans = _fetch_session_spans(
                conn, session_id=sid, since_ns=since_cutoff, policy=effective_policy
            )
            by_turn: dict[str, list[dict[str, object]]] = {}
            for span in spans:
                by_turn.setdefault(str(span.get("turn_id") or ""), []).append(span)
            for turn_id, turn_spans in by_turn.items():
                if not turn_spans:
                    continue
                start_ns = min(int(str(span["ts_start_ns"])) for span in turn_spans)
                end_values = [
                    int(str(span["ts_end_ns"]))
                    for span in turn_spans
                    if span.get("ts_end_ns") is not None
                ]
                duration_ms = (
                    round((max(end_values) - start_ns) / 1_000_000, 1) if end_values else None
                )
                turns.append(
                    {
                        "session_id": sid,
                        "turn_id": turn_id,
                        "ts_start_ns": start_ns,
                        "duration_ms": duration_ms,
                        "status": _turn_status(turn_spans),
                        "spans": [
                            _span_node_to_dict(root) for root in _build_turn_tree(turn_spans)
                        ],
                    }
                )
        turns.sort(key=lambda row: int(str(row["ts_start_ns"])), reverse=True)
        return turns[: max(last, 1)]
    finally:
        conn.close()


def _dict_to_span_node(span_dict: dict[str, object]) -> SpanNode:
    """Rebuild :class:`SpanNode` from a JSON-shaped span dict.

    Args:
        span_dict (dict[str, object]): Serialized span from :func:`_span_node_to_dict`.

    Returns:
        SpanNode: In-memory span tree node.

    Examples:
        >>> node = _dict_to_span_node({"span_id": "x", "kind": "k", "status": "ok", "children": []})
        >>> node.span_id
        'x'
    """
    child_raw = span_dict.get("children")
    child_dicts = child_raw if isinstance(child_raw, list) else []
    children = [_dict_to_span_node(child) for child in child_dicts if isinstance(child, dict)]
    duration_raw = span_dict.get("duration_ms")
    duration_ms = float(duration_raw) if isinstance(duration_raw, (int, float)) else None
    attrs_raw = span_dict.get("attrs")
    attrs = dict(attrs_raw) if isinstance(attrs_raw, dict) else {}
    return SpanNode(
        span_id=str(span_dict.get("span_id") or ""),
        kind=str(span_dict.get("kind") or "span"),
        tier=str(span_dict["tier"]) if span_dict.get("tier") is not None else None,
        status=str(span_dict.get("status") or "ok"),
        duration_ms=duration_ms,
        attrs=attrs,
        children=children,
    )


def turn_to_span_tree_node(turn: dict[str, object]) -> SpanTreeNode:
    """Convert one turn payload to a :class:`SpanTreeNode` for rendering.

    Args:
        turn (dict[str, object]): One element from :func:`load_trace_turns`.

    Returns:
        SpanTreeNode: Tree with turn header label and nested span children.

    Examples:
        >>> turn_to_span_tree_node({"session_id": "s", "turn_id": "t", "status": "ok", "spans": []}).label
        's · t'
    """
    session = str(turn.get("session_id") or "")
    turn_id = str(turn.get("turn_id") or "")
    duration = turn.get("duration_ms")
    status = str(turn.get("status") or "ok")
    timing = f" ({duration}ms)" if duration is not None else ""
    status_suffix = f" [{status.upper()}]" if status.lower() not in {"ok", "success"} else ""
    label = f"{session} · {turn_id}{timing}{status_suffix}"
    children: list[SpanTreeNode] = []
    spans_raw = turn.get("spans")
    spans = spans_raw if isinstance(spans_raw, list) else []
    for span_dict in spans:
        if isinstance(span_dict, dict):
            children.append(_span_node_to_tree(_dict_to_span_node(span_dict)))
    return SpanTreeNode(label=label, children=children)


def traces_drilldown_hint(session_id: str) -> str:
    """Return a suggested ``sevn traces`` command for one session id.

    Args:
        session_id (str): Gateway session id from logs insight.

    Returns:
        str: Suggested CLI invocation.

    Examples:
        >>> traces_drilldown_hint("sess-abc")
        'sevn traces --session sess-abc'
    """
    text = session_id.strip()
    return "sevn traces --last 1" if not text else f"sevn traces --session {text}"


__all__ = [
    "SpanNode",
    "load_trace_turns",
    "traces_drilldown_hint",
    "turn_to_span_tree_node",
]
