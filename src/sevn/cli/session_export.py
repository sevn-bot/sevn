"""Offline session export with redaction (#83; ``specs/23-cli.md``).

Module: sevn.cli.session_export
Depends: json, pathlib, re, sqlite3, uuid, sevn.agent.tracing.redacting_sink,
    sevn.gateway.session.session_mirror, sevn.gateway.session.sessions_query,
    sevn.gateway.turn.turn_bundle, sevn.logging.log_redact, sevn.storage.paths

Exports:
    export_sessions — gather SQLite, mirror JSONL, and turn bundles with redaction.
    record_session_export_job — optional audit row in ``session_export_jobs``.
    redact_export_text — redact one text line for export output.
    redact_export_value — recursively redact structured export payloads.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sevn.agent.tracing.redacting_sink import (
    TraceRedactionPolicy,
    _key_denied,
    redact_text_value,
)
from sevn.gateway.session.sessions_query import parse_session_metadata
from sevn.gateway.turn.turn_bundle import (
    list_turn_export_candidates,
    load_turn_bundle_index,
    load_turn_bundle_records,
)
from sevn.storage.paths import turn_bundle_index_path, turn_bundles_dir

_EXPORT_REDACTED = "[REDACTED]"


def _utc_now_iso() -> str:
    """Return a naive UTC ISO timestamp for audit rows.

    Returns:
        str: ISO-8601 timestamp without timezone suffix.

    Examples:
        >>> len(_utc_now_iso()) >= 19
        True
    """
    return datetime.now(tz=UTC).replace(tzinfo=None).isoformat()


def _normalize_formats(fmt: str) -> tuple[str, ...]:
    """Split a comma-separated export format list.

    Args:
        fmt (str): Comma-separated format names.

    Returns:
        tuple[str, ...]: Lowercased format tokens defaulting to ``markdown``.

    Examples:
        >>> _normalize_formats("jsonl,markdown")
        ('jsonl', 'markdown')
    """
    parts = [part.strip().lower() for part in fmt.split(",") if part.strip()]
    if not parts:
        return ("markdown",)
    return tuple(parts)


def _message_in_window(created_at: str, *, since: str | None, until: str | None) -> bool:
    """Return whether ``created_at`` falls in the optional since/until window.

    Args:
        created_at (str): Message ISO timestamp.
        since (str | None): Lower bound inclusive when set.
        until (str | None): Upper bound by calendar day when set.

    Returns:
        bool: ``True`` when the row should be included.

    Examples:
        >>> _message_in_window("2026-07-01T10:00:00+00:00", since="2026-07-01", until="2026-07-02")
        True
    """
    if since is not None and created_at < since:
        return False
    return until is None or created_at[:10] <= until[:10]


def _session_matches_profile(
    *,
    scope_key: str,
    metadata_json: str | None,
    profile: str,
) -> bool:
    """Return whether a session row matches a routing profile filter.

    Args:
        scope_key (str): Gateway session scope key.
        metadata_json (str | None): Stored session metadata JSON.
        profile (str): Requested routing profile name.

    Returns:
        bool: ``True`` when the session matches ``profile``.

    Examples:
        >>> _session_matches_profile(scope_key="telegram:7", metadata_json=None, profile="telegram")
        True
    """
    if profile == scope_key.split(":", 1)[0]:
        return True
    meta = parse_session_metadata(str(metadata_json) if metadata_json is not None else None)
    routing = meta.get("routing_profile") or meta.get("profile")
    return routing == profile


_EXPORT_EXTRA_DENY_KEYS: tuple[str, ...] = ("token",)


def _export_key_denied(key: str, policy: TraceRedactionPolicy) -> bool:
    """Return whether an export dict key should be replaced with ``[REDACTED]``.

    Args:
        key (str): Attribute or metadata key.
        policy (TraceRedactionPolicy): Workspace trace redaction rules.

    Returns:
        bool: ``True`` when the key names sensitive material.

    Examples:
        >>> _export_key_denied("api_key", TraceRedactionPolicy.from_defaults())
        True
    """
    lowered = key.lower()
    if lowered in _EXPORT_EXTRA_DENY_KEYS:
        return True
    return _key_denied(key, policy.deny_keys)


def redact_export_text(text: str, policy: TraceRedactionPolicy) -> str:
    """Apply log-line and trace redaction for export artifacts.

    Args:
        text (str): Raw operator/model text.
        policy (TraceRedactionPolicy): Active redaction rules.

    Returns:
        str: Redacted text using the ``[REDACTED]`` export placeholder.

    Examples:
        >>> redact_export_text("token=abc123", TraceRedactionPolicy.from_defaults())
        '[REDACTED]'
    """
    return redact_text_value(text, policy, placeholder=_EXPORT_REDACTED)


def redact_export_value(value: object, policy: TraceRedactionPolicy) -> object:
    """Recursively redact export payloads.

    Args:
        value (object): Scalar or nested JSON-compatible structure.
        policy (TraceRedactionPolicy): Active redaction rules.

    Returns:
        object: Redacted copy safe for export artifacts.

    Examples:
        >>> redact_export_value({"api_key": "secret"}, TraceRedactionPolicy.from_defaults())
        {'api_key': '[REDACTED]'}
    """
    if isinstance(value, str):
        return redact_export_text(value, policy)
    if isinstance(value, dict):
        out: dict[str, object] = {}
        for key, item in value.items():
            key_s = str(key)
            if _export_key_denied(key_s, policy):
                out[key_s] = _EXPORT_REDACTED
            else:
                out[key_s] = redact_export_value(item, policy)
        return out
    if isinstance(value, list):
        return [redact_export_value(item, policy) for item in value]
    return value


def _parse_extras_json(raw: str | None) -> dict[str, object] | None:
    """Decode ``gateway_messages.extras_json`` for export.

    Args:
        raw (str | None): Stored JSON blob.

    Returns:
        dict[str, object] | None: Parsed mapping or ``None`` when empty.

    Examples:
        >>> _parse_extras_json('{"tool_name":"x"}')["tool_name"]
        'x'
    """
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}
    return parsed if isinstance(parsed, dict) else {"raw": parsed}


def _load_sqlite_messages(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    since: str | None,
    until: str | None,
    policy: TraceRedactionPolicy,
) -> list[dict[str, object]]:
    """Load redacted ``gateway_messages`` rows for one session.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle.
        session_id (str): Target session id.
        since (str | None): Optional lower bound on ``created_at``.
        until (str | None): Optional upper bound by calendar day.
        policy (TraceRedactionPolicy): Redaction rules applied on read.

    Returns:
        list[dict[str, object]]: Redacted message records.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> _load_sqlite_messages(c, session_id="missing", since=None, until=None, policy=TraceRedactionPolicy.from_defaults())
        []
    """
    rows = conn.execute(
        """
        SELECT id, role, kind, content, status, created_at, turn_id, extras_json
        FROM gateway_messages
        WHERE session_id = ?
        ORDER BY id ASC
        """,
        (session_id,),
    ).fetchall()
    records: list[dict[str, object]] = []
    for mid, role, kind, content, status, created_at, turn_id, extras_json in rows:
        created = str(created_at)
        if not _message_in_window(created, since=since, until=until):
            continue
        extras = _parse_extras_json(str(extras_json) if extras_json is not None else None)
        record: dict[str, object] = {
            "source": "sqlite",
            "session_id": session_id,
            "message_id": int(mid),
            "role": str(role),
            "kind": str(kind),
            "content": redact_export_text(str(content or ""), policy),
            "status": str(status),
            "created_at": created,
            "turn_id": str(turn_id or ""),
        }
        if extras is not None:
            record["extras"] = redact_export_value(extras, policy)
        records.append(record)
    return records


def _load_turn_metadata(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    policy: TraceRedactionPolicy,
) -> list[dict[str, object]]:
    """Load redacted ``gateway_turn_metadata`` rows for one session.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle.
        session_id (str): Target session id.
        policy (TraceRedactionPolicy): Redaction rules applied on read.

    Returns:
        list[dict[str, object]]: Turn metadata export records.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> _load_turn_metadata(c, session_id="missing", policy=TraceRedactionPolicy.from_defaults())
        []
    """
    rows = conn.execute(
        """
        SELECT turn_id, intent, tier, confidence, model_id, started_at, finished_at, status
        FROM gateway_turn_metadata
        WHERE session_id = ?
        ORDER BY started_at ASC
        """,
        (session_id,),
    ).fetchall()
    out: list[dict[str, object]] = []
    for turn_id, intent, tier, confidence, model_id, started_at, finished_at, status in rows:
        out.append(
            {
                "source": "turn_metadata",
                "session_id": session_id,
                "turn_id": str(turn_id),
                "intent": str(intent),
                "tier": str(tier),
                "confidence": float(confidence),
                "model_id": redact_export_text(str(model_id or ""), policy) or None,
                "started_at": str(started_at),
                "finished_at": str(finished_at) if finished_at is not None else None,
                "status": str(status),
            },
        )
    return out


def _load_mirror_messages(
    content_root: Path,
    *,
    session_id: str,
    since: str | None,
    until: str | None,
    policy: TraceRedactionPolicy,
) -> list[dict[str, object]]:
    """Load redacted workspace session mirror JSONL rows when present.

    Args:
        content_root (Path): Workspace content root.
        session_id (str): Target session id.
        since (str | None): Optional lower bound on row timestamps.
        until (str | None): Optional upper bound by calendar day.
        policy (TraceRedactionPolicy): Redaction rules applied on read.

    Returns:
        list[dict[str, object]]: Mirror JSONL records.

    Examples:
        >>> from pathlib import Path
        >>> _load_mirror_messages(Path("/missing"), session_id="s", since=None, until=None, policy=TraceRedactionPolicy.from_defaults())
        []
    """
    index_path = content_root / "sessions" / "_index.json"
    if not index_path.is_file():
        return []
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    sessions = index.get("sessions")
    if not isinstance(sessions, dict):
        return []
    entry = sessions.get(session_id)
    if not isinstance(entry, dict):
        return []
    jsonl_rel = entry.get("jsonl")
    if not isinstance(jsonl_rel, str) or not jsonl_rel.strip():
        return []
    jsonl_path = content_root / jsonl_rel
    if not jsonl_path.is_file():
        return []
    records: list[dict[str, object]] = []
    with jsonl_path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            created = str(row.get("created_at") or row.get("ts") or "")
            if created and not _message_in_window(created, since=since, until=until):
                continue
            payload = redact_export_value(row, policy)
            if isinstance(payload, dict):
                payload.setdefault("source", "mirror")
                payload.setdefault("session_id", session_id)
                records.append(payload)
    return records


def _load_turn_bundle_records_with_conn(
    conn: sqlite3.Connection,
    dot_sevn: Path,
    *,
    session_id: str,
    since: str | None,
    policy: TraceRedactionPolicy,
) -> list[dict[str, object]]:
    """Load redacted on-disk turn bundle records for one session.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle.
        dot_sevn (Path): Workspace ``.sevn`` directory.
        session_id (str): Target session id.
        since (str | None): Optional lower bound passed to turn listing.
        policy (TraceRedactionPolicy): Redaction rules applied on read.

    Returns:
        list[dict[str, object]]: Turn bundle stream records.

    Examples:
        >>> import sqlite3
        >>> from pathlib import Path
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> _load_turn_bundle_records_with_conn(c, Path("/tmp/.sevn"), session_id="s", since=None, policy=TraceRedactionPolicy.from_defaults())
        []
    """
    turns_root = turn_bundles_dir(dot_sevn)
    if not turns_root.is_dir():
        return []
    records: list[dict[str, object]] = []
    for candidate in list_turn_export_candidates(conn, session_id=session_id, since=since):
        for day_dir in sorted(turns_root.iterdir()):
            if not day_dir.is_dir():
                continue
            index = load_turn_bundle_index(turn_bundle_index_path(day_dir))
            for entry in index.get("turns", []):
                if str(entry.get("turn_id", "")) != candidate.turn_id:
                    continue
                bundle_name = str(entry.get("file") or "")
                if not bundle_name:
                    continue
                bundle_path = day_dir / bundle_name
                if not bundle_path.is_file():
                    continue
                for row in load_turn_bundle_records(bundle_path):
                    payload = redact_export_value(dict(row), policy)
                    if isinstance(payload, dict):
                        payload.setdefault("source", "turn_bundle")
                        payload.setdefault("session_id", session_id)
                        records.append(payload)
    return records


def _select_sessions(
    conn: sqlite3.Connection,
    *,
    channel: str | None,
    profile: str | None,
    session_id: str | None,
) -> list[tuple[str, str, str, str | None]]:
    """Select gateway sessions matching export filters.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle.
        channel (str | None): Optional channel filter.
        profile (str | None): Optional routing profile filter.
        session_id (str | None): Optional single-session filter.

    Returns:
        list[tuple[str, str, str, str | None]]: Matching session rows.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> _select_sessions(c, channel=None, profile=None, session_id=None)
        []
    """
    rows = conn.execute(
        """
        SELECT session_id, scope_key, channel, metadata_json
        FROM gateway_sessions
        ORDER BY updated_at DESC
        """,
    ).fetchall()
    selected: list[tuple[str, str, str, str | None]] = []
    for sid, scope_key, ch, metadata_json in rows:
        sid_s = str(sid)
        if session_id is not None and sid_s != session_id:
            continue
        if channel is not None and str(ch) != channel:
            continue
        if profile is not None and not _session_matches_profile(
            scope_key=str(scope_key),
            metadata_json=str(metadata_json) if metadata_json is not None else None,
            profile=profile,
        ):
            continue
        selected.append((sid_s, str(scope_key), str(ch), metadata_json))
    return selected


def _render_markdown(
    session: dict[str, object],
    records: list[dict[str, object]],
) -> str:
    """Render one session export as markdown.

    Args:
        session (dict[str, object]): Session header fields.
        records (list[dict[str, object]]): Combined export records.

    Returns:
        str: Markdown document text.

    Examples:
        >>> _render_markdown({"session_id": "s", "channel": "webui", "scope_key": "webui:1"}, [])
        '# Session export: s\\n\\n- **Channel:** webui\\n- **Scope:** webui:1\\n\\n## Messages\\n'
    """
    lines = [
        f"# Session export: {session['session_id']}",
        "",
        f"- **Channel:** {session.get('channel', '')}",
        f"- **Scope:** {session.get('scope_key', '')}",
        "",
        "## Messages",
        "",
    ]
    for record in records:
        if record.get("source") not in {"sqlite", "mirror"}:
            continue
        lines.append(
            f"### [{record.get('created_at', '')}] {record.get('role', '')}/{record.get('kind', '')}",
        )
        lines.append(str(record.get("content", "")))
        extras = record.get("extras")
        if isinstance(extras, dict) and extras:
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(extras, indent=2, sort_keys=True))
            lines.append("```")
        lines.append("")
    meta_rows = [row for row in records if row.get("source") == "turn_metadata"]
    if meta_rows:
        lines.extend(["## Turn metadata", ""])
        for row in meta_rows:
            lines.append(
                f"- `{row.get('turn_id')}` tier={row.get('tier')} intent={row.get('intent')} "
                f"status={row.get('status')}",
            )
        lines.append("")
    bundle_rows = [row for row in records if row.get("source") == "turn_bundle"]
    if bundle_rows:
        lines.extend(["## Turn bundles", ""])
        for row in bundle_rows[:20]:
            lines.append(
                f"- turn `{row.get('turn_id', row.get('stream', ''))}` stream={row.get('stream')}"
            )
        if len(bundle_rows) > 20:
            lines.append(f"- … and {len(bundle_rows) - 20} more bundle records")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_jsonl(records: list[dict[str, object]]) -> str:
    """Render export records as one JSON object per line.

    Args:
        records (list[dict[str, object]]): Combined export records.

    Returns:
        str: JSONL payload.

    Examples:
        >>> _render_jsonl([{"source": "sqlite", "content": "hi"}]).startswith("{")
        True
    """
    return "\n".join(json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records)


def record_session_export_job(
    conn: sqlite3.Connection,
    *,
    export_id: str,
    session_id: str | None,
    channel: str | None,
    profile: str | None,
    since: str | None,
    until: str | None,
    formats: str,
    output_path: str | None,
    row_count: int,
    status: str,
    error: str | None = None,
) -> None:
    """Insert one audit row when ``session_export_jobs`` exists.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle.
        export_id (str): Stable export job id.
        session_id (str | None): Requested session filter.
        channel (str | None): Requested channel filter.
        profile (str | None): Requested profile filter.
        since (str | None): Requested lower bound.
        until (str | None): Requested upper bound.
        formats (str): Requested format string.
        output_path (str | None): Output directory when written to disk.
        row_count (int): Exported record count.
        status (str): ``completed`` or ``failed``.
        error (str | None, optional): Failure summary when ``status`` is ``failed``.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> record_session_export_job(
        ...     c, export_id="e1", session_id="s", channel=None, profile=None,
        ...     since=None, until=None, formats="jsonl", output_path=None,
        ...     row_count=0, status="completed",
        ... )
    """
    try:
        conn.execute(
            """
            INSERT INTO session_export_jobs (
                export_id, session_id, channel, profile, since, until,
                formats, output_path, row_count, status, created_at, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                export_id,
                session_id,
                channel,
                profile,
                since,
                until,
                formats,
                output_path,
                int(row_count),
                status,
                _utc_now_iso(),
                error,
            ),
        )
        conn.commit()
    except sqlite3.OperationalError:
        return


def export_sessions(
    *,
    channel: str | None = None,
    profile: str | None = None,
    session_id: str | None = None,
    since: str | None = None,
    until: str | None = None,
    fmt: str = "jsonl",
    output: Path | str | None = None,
    conn: sqlite3.Connection | None = None,
    content_root: Path | None = None,
    dot_sevn: Path | None = None,
) -> str:
    """Export redacted session history from SQLite, mirror JSONL, and turn bundles.

    When ``output`` is set, writes one artifact per session per requested format.
    Otherwise returns the rendered payload for ``fmt`` (first format when several).

    Args:
        channel (str | None, optional): Filter by gateway channel.
        profile (str | None, optional): Filter by routing profile name.
        session_id (str | None, optional): Export one session id.
        since (str | None, optional): Include rows at or after this ISO timestamp/date.
        until (str | None, optional): Include rows on or before this ISO date.
        fmt (str, optional): Comma-separated ``markdown`` and/or ``jsonl``.
        output (Path | str | None, optional): Directory for on-disk artifacts.
        conn (sqlite3.Connection | None, optional): Existing DB handle for tests.
        content_root (Path | None, optional): Workspace root when ``conn`` is supplied.
        dot_sevn (Path | None, optional): ``.sevn`` path override for tests.

    Returns:
        str: Summary message when ``output`` is set, otherwise rendered export text.

    Raises:
        ValueError: When ``conn`` is supplied without ``content_root``.

    Examples:
        >>> import sqlite3
        >>> from pathlib import Path
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> export_sessions(session_id="s", fmt="jsonl", conn=c, content_root=Path("/tmp/ws"))
        ''
    """
    from sevn.cli.commands.sessions import _resolve_db

    own_conn = conn is None
    if conn is None:
        conn, resolved_root = _resolve_db()
        content_root = content_root or resolved_root
        dot_sevn = dot_sevn or (content_root / ".sevn")
    elif content_root is None:
        msg = "export_sessions requires content_root when conn is supplied"
        raise ValueError(msg)
    else:
        dot_sevn = dot_sevn or (content_root / ".sevn")

    policy = TraceRedactionPolicy.from_defaults()
    formats = _normalize_formats(fmt)
    export_id = uuid.uuid4().hex
    out_dir = Path(output) if output is not None else None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)

    sessions = _select_sessions(conn, channel=channel, profile=profile, session_id=session_id)
    rendered_parts: list[str] = []
    total_rows = 0

    try:
        for sid, scope_key, ch, _metadata_json in sessions:
            session_info: dict[str, object] = {
                "session_id": sid,
                "scope_key": scope_key,
                "channel": ch,
            }
            records: list[dict[str, object]] = []
            records.extend(
                _load_sqlite_messages(
                    conn,
                    session_id=sid,
                    since=since,
                    until=until,
                    policy=policy,
                ),
            )
            records.extend(
                _load_mirror_messages(
                    content_root,
                    session_id=sid,
                    since=since,
                    until=until,
                    policy=policy,
                ),
            )
            records.extend(_load_turn_metadata(conn, session_id=sid, policy=policy))
            records.extend(
                _load_turn_bundle_records_with_conn(
                    conn,
                    dot_sevn,
                    session_id=sid,
                    since=since,
                    policy=policy,
                ),
            )
            total_rows += len(records)

            if out_dir is not None:
                for format_name in formats:
                    if format_name == "markdown":
                        path = out_dir / f"{sid}.md"
                        path.write_text(_render_markdown(session_info, records), encoding="utf-8")
                    elif format_name == "jsonl":
                        path = out_dir / f"{sid}.jsonl"
                        path.write_text(_render_jsonl(records), encoding="utf-8")
            else:
                primary = formats[0]
                if primary == "markdown":
                    rendered_parts.append(_render_markdown(session_info, records))
                else:
                    rendered_parts.append(_render_jsonl(records))

        record_session_export_job(
            conn,
            export_id=export_id,
            session_id=session_id,
            channel=channel,
            profile=profile,
            since=since,
            until=until,
            formats=fmt,
            output_path=str(out_dir) if out_dir is not None else None,
            row_count=total_rows,
            status="completed",
        )
    except Exception as exc:
        record_session_export_job(
            conn,
            export_id=export_id,
            session_id=session_id,
            channel=channel,
            profile=profile,
            since=since,
            until=until,
            formats=fmt,
            output_path=str(out_dir) if out_dir is not None else None,
            row_count=total_rows,
            status="failed",
            error=str(exc)[:500],
        )
        raise
    finally:
        if own_conn:
            conn.close()

    if out_dir is not None:
        return f"exported {len(sessions)} session(s), {total_rows} record(s) -> {out_dir}"
    return "\n\n".join(rendered_parts)


__all__ = [
    "export_sessions",
    "record_session_export_job",
    "redact_export_text",
    "redact_export_value",
]
