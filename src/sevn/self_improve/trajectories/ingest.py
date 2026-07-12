"""Ingest ``trajectory_fact`` rows from persisted trace spans (`specs/33-self-improvement.md` §3.1).

Module: sevn.self_improve.trajectories.ingest
Depends: json, sqlite3, datetime, pathlib, sevn.ui.dashboard.query.traces

Exports:
    TrajectoryIngestResult — aggregate ingest counters.
    ingest_trajectory_facts_from_traces — pull ``tool.*`` / ``triage.complete`` rows.
    ingest_trajectory_fact_for_turn — ingest one ``turn_id`` from ``traces.db``.
    trajectory_reconciliation_rate — fixture join rate for §9 trace-join tests.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sevn.ui.dashboard.query.traces import ensure_trace_connection

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

_TRACE_KIND_SQL = "(kind LIKE 'tool.%' OR kind = 'triage.complete')"


@dataclass(frozen=True, slots=True)
class TrajectoryIngestResult:
    """Counters returned after one ingest pass."""

    turns_processed: int
    rows_upserted: int


def _parse_attrs(raw: str) -> dict[str, Any]:
    """Parse ``attrs_json`` defensively.

    Args:
        raw (str): Serialized JSON from ``trace_events``.

    Returns:
        dict[str, Any]: Parsed object or empty dict.

    Examples:
        >>> _parse_attrs('{"intent":"chat"}')["intent"]
        'chat'
    """
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _complexity_to_tier(complexity: object) -> str | None:
    """Map triager complexity labels to executor tier letters.

    Args:
        complexity (object): Raw ``complexity`` attr from ``triage.complete``.

    Returns:
        str | None: ``A``-``D`` when recognised.

    Examples:
        >>> _complexity_to_tier("B")
        'B'
    """
    token = str(complexity or "").strip().upper()
    if token in ("A", "B", "C", "D"):
        return token
    return None


def _tool_signal_row(
    *,
    span_id: str,
    kind: str,
    status: str,
    attrs: dict[str, Any],
) -> dict[str, object]:
    """Build one tool span entry for ``signals_json.tools``.

    Args:
        span_id (str): Trace span id.
        kind (str): Trace kind (``tool.invoke``, …).
        status (str): Span status.
        attrs (dict[str, Any]): Redacted-safe attrs subset.

    Returns:
        dict[str, object]: Serializable tool signal row.

    Examples:
        >>> _tool_signal_row(span_id="s", kind="tool.invoke", status="ok", attrs={"name": "read"})["kind"]
        'tool.invoke'
    """
    name = attrs.get("name") or attrs.get("tool.name") or attrs.get("tool_name")
    return {
        "span_id": span_id,
        "kind": kind,
        "status": status,
        "name": name,
    }


def _merge_turn_facts(
    *,
    session_id: str,
    turn_id: str,
    tier: str | None,
    triage_span_id: str | None,
    triage_attrs: dict[str, Any] | None,
    tool_rows: list[dict[str, object]],
) -> tuple[str, str, str, str | None, str | None, str | None, str | None, str, str | None]:
    """Project one ``trajectory_fact`` tuple from grouped trace rows.

    Args:
        session_id (str): Session id shared by grouped spans.
        turn_id (str): Turn key.
        tier (str | None): Executor tier from trace column when present.
        triage_span_id (str | None): ``triage.complete`` span id when present.
        triage_attrs (dict[str, Any] | None): Parsed triage attrs.
        tool_rows (list[dict[str, object]]): Tool signal entries.

    Returns:
        tuple: ``(turn_id, session_id, channel, intent, tier, budget_regime, model_id, signals_json, trace_span_id)``.

    Examples:
        >>> row = _merge_turn_facts(
        ...     session_id="s",
        ...     turn_id="t",
        ...     tier="B",
        ...     triage_span_id="sp",
        ...     triage_attrs={"intent": "chat", "complexity": "B", "budget_regime": "SUBSCRIPTION", "model_id": "m"},
        ...     tool_rows=[{"span_id": "x", "kind": "tool.invoke", "status": "ok", "name": "read"}],
        ... )
        >>> row[3]
        'chat'
    """
    attrs = triage_attrs or {}
    channel = str(attrs.get("channel") or "unknown")
    intent = attrs.get("intent")
    intent_str = str(intent) if intent is not None else None
    budget_regime = attrs.get("budget_regime")
    budget_str = str(budget_regime) if budget_regime is not None else None
    model_id = attrs.get("model_id")
    model_str = str(model_id) if model_id is not None else None
    tier_out = tier or _complexity_to_tier(attrs.get("complexity"))
    signals: dict[str, object] = {"tools": tool_rows}
    if triage_attrs:
        signals["triage"] = {
            "intent": intent_str,
            "complexity": attrs.get("complexity"),
            "confidence": attrs.get("confidence"),
        }
    trace_span_id = triage_span_id
    if trace_span_id is None and tool_rows:
        trace_span_id = str(tool_rows[0].get("span_id") or "")
    signals_json = json.dumps(signals, sort_keys=True)
    return (
        turn_id,
        session_id,
        channel,
        intent_str,
        tier_out,
        budget_str,
        model_str,
        signals_json,
        trace_span_id or None,
    )


def _fetch_trace_rows(
    traces_db_path: Path,
    *,
    turn_id: str | None = None,
    since_ns: int | None = None,
) -> list[tuple[str, str, str, str | None, str, str, str, int]]:
    """Load tool/triage spans from ``traces.db`` with optional filters.

    Args:
        traces_db_path (Path): Path to ``traces.db``.
        turn_id (str | None): Restrict to one turn when set.
        since_ns (int | None): Lower bound on ``ts_start_ns``.

    Returns:
        list[tuple[str, str, str, str | None, str, str, str, int]]: Raw span rows.

    Examples:
        >>> _fetch_trace_rows.__name__
        '_fetch_trace_rows'
    """
    trace_conn = ensure_trace_connection(traces_db_path)
    try:
        sql = f"""SELECT span_id, session_id, turn_id, tier, kind, status, attrs_json, ts_start_ns
            FROM trace_events WHERE {_TRACE_KIND_SQL}"""  # nosec B608 — kind filter is fixed
        params: list[object] = []
        if turn_id is not None:
            sql += " AND turn_id = ?"
            params.append(turn_id)
        if since_ns is not None:
            sql += " AND ts_start_ns >= ?"
            params.append(since_ns)
        sql += " ORDER BY ts_start_ns ASC"
        return trace_conn.execute(sql, tuple(params)).fetchall()
    finally:
        trace_conn.close()


def _upsert_grouped_facts(
    sevn_conn: sqlite3.Connection,
    grouped: dict[str, dict[str, object]],
) -> TrajectoryIngestResult:
    """Write grouped trace buckets into ``trajectory_fact``.

    Args:
        sevn_conn (sqlite3.Connection): Open ``sevn.db`` connection.
        grouped (dict[str, dict[str, object]]): Turn-keyed span buckets.

    Returns:
        TrajectoryIngestResult: Turn and upsert counters.

    Examples:
        >>> _upsert_grouped_facts.__name__
        '_upsert_grouped_facts'
    """
    created_at = datetime.now(tz=UTC).isoformat()
    upserted = 0
    for turn_key, bucket in grouped.items():
        tools = bucket["tools"]
        if not isinstance(tools, list):
            continue
        triage_attrs = bucket.get("triage_attrs")
        if triage_attrs is not None and not isinstance(triage_attrs, dict):
            triage_attrs = None
        tier_val = bucket.get("tier")
        tier_str = tier_val if isinstance(tier_val, str) else None
        triage_span_val = bucket.get("triage_span_id")
        triage_span_str = triage_span_val if isinstance(triage_span_val, str) else None
        fact = _merge_turn_facts(
            session_id=str(bucket["session_id"]),
            turn_id=turn_key,
            tier=tier_str,
            triage_span_id=triage_span_str,
            triage_attrs=triage_attrs,
            tool_rows=tools,
        )
        sevn_conn.execute(
            """INSERT INTO trajectory_fact (
                turn_id, session_id, channel, intent, tier, budget_regime,
                model_id, signals_json, trace_span_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(turn_id) DO UPDATE SET
                session_id = excluded.session_id,
                channel = excluded.channel,
                intent = excluded.intent,
                tier = excluded.tier,
                budget_regime = excluded.budget_regime,
                model_id = excluded.model_id,
                signals_json = excluded.signals_json,
                trace_span_id = excluded.trace_span_id,
                created_at = excluded.created_at""",
            (*fact, created_at),
        )
        upserted += 1
    if upserted:
        sevn_conn.commit()
    return TrajectoryIngestResult(turns_processed=len(grouped), rows_upserted=upserted)


def _group_trace_rows(
    rows: list[tuple[str, str, str, str | None, str, str, str, int]],
) -> dict[str, dict[str, object]]:
    """Group raw trace rows by ``turn_id``.

    Args:
        rows (list[tuple[str, str, str, str | None, str, str, str, int]]): Raw span rows.

    Returns:
        dict[str, dict[str, object]]: Turn-keyed span buckets.

    Examples:
        >>> _group_trace_rows([])
        {}
    """
    grouped: dict[str, dict[str, object]] = {}
    for span_id, session_id, turn_id, tier, kind, status, attrs_json, _ts in rows:
        turn_key = str(turn_id)
        bucket = grouped.setdefault(
            turn_key,
            {
                "session_id": str(session_id),
                "tier": str(tier) if tier else None,
                "triage_span_id": None,
                "triage_attrs": None,
                "tools": [],
            },
        )
        attrs = _parse_attrs(str(attrs_json))
        kind_str = str(kind)
        if kind_str == "triage.complete":
            bucket["triage_span_id"] = str(span_id)
            bucket["triage_attrs"] = attrs
            if tier:
                bucket["tier"] = str(tier)
        elif kind_str.startswith("tool."):
            tools = bucket["tools"]
            if not isinstance(tools, list):
                continue
            tools.append(
                _tool_signal_row(
                    span_id=str(span_id),
                    kind=kind_str,
                    status=str(status),
                    attrs=attrs,
                ),
            )
    return grouped


def ingest_trajectory_facts_from_traces(
    sevn_conn: sqlite3.Connection,
    traces_db_path: Path,
    *,
    since_ns: int | None = None,
) -> TrajectoryIngestResult:
    """Upsert ``trajectory_fact`` rows by joining ``traces.db`` tool/triage spans.

    Reads ``trace_events`` rows whose ``kind`` matches ``tool.%`` or
    ``triage.complete``, groups by ``turn_id``, and writes denormalised facts
    into ``sevn.db``.

    Args:
        sevn_conn (sqlite3.Connection): Open ``sevn.db`` connection with migration 18.
        traces_db_path (Path): Path to ``traces.db``.
        since_ns (int | None): Optional lower bound on ``ts_start_ns``.

    Returns:
        TrajectoryIngestResult: Turn and upsert counters.

    Examples:
        >>> import sqlite3
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.agent.tracing.traces_migrate import apply_traces_migrations
        >>> from sevn.storage.migrate import apply_migrations
        >>> td = Path(tempfile.mkdtemp())
        >>> traces_path = td / "traces.db"
        >>> sevn = sqlite3.connect(":memory:")
        >>> apply_migrations(sevn)
        >>> tconn = sqlite3.connect(traces_path)
        >>> apply_traces_migrations(tconn)
        >>> _ = tconn.execute(
        ...     '''INSERT INTO trace_events (
        ...         span_id, parent_span_id, session_id, turn_id, tier, kind,
        ...         ts_start_ns, ts_end_ns, status, attrs_json
        ...     ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)''',
        ...     ("sp1", "sess", "turn1", "B", "triage.complete", 1, 2, "ok", '{"intent":"chat","complexity":"B","budget_regime":"SUBSCRIPTION","model_id":"m"}'),
        ... )
        >>> tconn.commit()
        >>> tconn.commit()
        >>> tconn.close()
        >>> result = ingest_trajectory_facts_from_traces(sevn, traces_path)
        >>> result.rows_upserted >= 1
        True
        >>> sevn.close()
    """
    rows = _fetch_trace_rows(traces_db_path, since_ns=since_ns)
    grouped = _group_trace_rows(rows)
    return _upsert_grouped_facts(sevn_conn, grouped)


def ingest_trajectory_fact_for_turn(
    sevn_conn: sqlite3.Connection,
    traces_db_path: Path,
    *,
    turn_id: str,
) -> TrajectoryIngestResult:
    """Upsert one ``trajectory_fact`` row for a single gateway turn.

    Args:
        sevn_conn (sqlite3.Connection): Open ``sevn.db`` connection.
        traces_db_path (Path): Path to ``traces.db``.
        turn_id (str): Gateway correlation / turn id.

    Returns:
        TrajectoryIngestResult: Turn and upsert counters (zero when no spans).

    Examples:
        >>> ingest_trajectory_fact_for_turn.__name__
        'ingest_trajectory_fact_for_turn'
    """
    rows = _fetch_trace_rows(traces_db_path, turn_id=turn_id)
    grouped = _group_trace_rows(rows)
    return _upsert_grouped_facts(sevn_conn, grouped)


def trajectory_reconciliation_rate(
    sevn_conn: sqlite3.Connection,
    traces_db_path: Path,
) -> float:
    """Return the share of ``tool.*`` spans whose ``turn_id`` exists in ``trajectory_fact``.

    Args:
        sevn_conn (sqlite3.Connection): Open ``sevn.db`` with trajectory rows.
        traces_db_path (Path): Path to ``traces.db``.

    Returns:
        float: Fraction in ``[0.0, 1.0]``; ``1.0`` when no tool spans exist.

    Examples:
        >>> trajectory_reconciliation_rate.__name__
        'trajectory_reconciliation_rate'
    """
    trace_conn = ensure_trace_connection(traces_db_path)
    try:
        tool_turns = [
            str(row[0])
            for row in trace_conn.execute(
                "SELECT DISTINCT turn_id FROM trace_events WHERE kind LIKE 'tool.%'",
            ).fetchall()
        ]
    finally:
        trace_conn.close()
    if not tool_turns:
        return 1.0
    matched = 0
    for turn_id in tool_turns:
        row = sevn_conn.execute(
            "SELECT 1 FROM trajectory_fact WHERE turn_id = ?",
            (turn_id,),
        ).fetchone()
        if row is not None:
            matched += 1
    return matched / len(tool_turns)


__all__ = [
    "TrajectoryIngestResult",
    "ingest_trajectory_fact_for_turn",
    "ingest_trajectory_facts_from_traces",
    "trajectory_reconciliation_rate",
]
