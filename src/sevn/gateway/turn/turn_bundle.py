"""Turn-bundle diagnostics — schemas, collector, and index writer (W0 + W1).

Module: sevn.gateway.turn.turn_bundle
Depends: json, os, re, sqlite3, tempfile, datetime, sevn.agent.tracing.redacting_sink,
    sevn.config.defaults, sevn.config.workspace_config, sevn.storage.paths,
    sevn.tools.log_query, sevn.ui.dashboard.query.traces

Per-turn JSONL bundles live at ``<content_root>/.sevn/turns/<DDMMYY>/<safe_turn_id>.jsonl``
with a per-day ``index.json``. The post-turn hook calls :func:`write_turn_bundle`.

Exports:
    TurnBundleMetaRecord — JSONL meta line shape (first record).
    TurnBundleLogRecord — JSONL log stream line shape.
    TurnBundleMessageRecord — JSONL gateway message line shape.
    TurnBundleTraceRecord — JSONL trace stream line shape.
    TurnBundleIndexEntry — one row in ``index.json`` ``turns[]``.
    TurnBundleIndex — top-level ``index.json`` document.
    TurnBundlePaths — resolved bundle directory + file paths for a turn.
    safe_turn_id — filesystem slug for ``turn_id`` (D3).
    parse_channel_from_turn_id — channel prefix from correlation id.
    turn_msg_hex_suffix — ``msg=<hex>`` tail used for log grep (W0.5).
    turn_log_grep_needles — full ``turn_id`` + ``msg=<hex>`` needles for logs.
    log_line_matches_turn — whether a ``gateway.log`` line belongs to a turn.
    compute_has_error — ``has_error`` predicate (D5).
    bundle_paths — resolved bundle directory + file paths for a turn.
    effective_turn_bundles_enabled — resolve ``diagnostics.turn_bundles.enabled`` (D8).
    collect_turn_bundle_records — gather meta + stream rows for one turn.
    load_turn_bundle_index — read or initialise ``index.json``.
    upsert_turn_bundle_index_entry — atomic index upsert (preserve ``processed``).
    write_turn_bundle — serialize JSONL bundle + update index (W1).
    TurnExportCandidate — one turn selected for offline export (W2).
    parse_since_timestamp — normalize ``--since`` CLI filter (W2).
    resolve_turn_terminal_status — terminal status for backfill export (W2).
    list_turn_export_candidates — query turns from ``sevn.db`` (W2).
    export_turn_bundles — offline backfill exporter (W2).
    resolve_turn_bundle_file — map ``turn_id`` to bundle path via ``index.json`` (W3).
    load_turn_bundle_records — read one ``*.jsonl`` bundle from disk (W3).
    format_turn_bundle_record — one deterministic plain-text line per record (W3).
    format_turn_bundle_summary — compact bundle overview for agents (W3).
    bundle_record_is_error — whether one stream row is error-relevant (W3).
    view_turn_bundle — filtered plain-text explorer lines (W3).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal, TypedDict, cast

from sevn.agent.tracing.redacting_sink import TraceRedactionPolicy
from sevn.config.defaults import DEFAULT_TURN_BUNDLES_ENABLED
from sevn.config.workspace_config import WorkspaceConfig
from sevn.storage.paths import (
    is_turn_bundle_day_slug,
    turn_bundle_day_dir,
    turn_bundle_day_slug,
    turn_bundle_file_path,
    turn_bundle_index_path,
    turn_bundles_dir,
)

TURN_BUNDLE_INDEX_VERSION: Final[Literal[1]] = 1
TURN_BUNDLE_STREAM_META: Final[str] = "meta"

# D5 — terminal failure / no-answer / escalation (explicit terminal_status values).
TURN_TERMINAL_FAILURE_STATUSES: Final[frozenset[str]] = frozenset({"error"})

# D5 — any matching trace row marks the turn as an error candidate.
TRACE_ERROR_STATUSES: Final[frozenset[str]] = frozenset(
    {"error", "failed", "denied", "cancelled", "escalated"}
)

_ERROR_LOG_LEVELS: Final[frozenset[str]] = frozenset({"ERROR", "CRITICAL"})
_ERROR_LOG_SUBSTRINGS: Final[tuple[str, ...]] = ("executor_no_answer",)
_MESSAGE_ERROR_STATUSES: Final[frozenset[str]] = frozenset({"error", "failed", "timeout"})

TurnBundleViewStream = Literal["log", "message", "trace"]
TurnBundleViewSection = Literal["meta", "summary"]

_MSG_HEX_SUFFIX_RE: Final[re.Pattern[str]] = re.compile(r"msg=([0-9a-f]+)$", re.IGNORECASE)
_CHANNEL_PREFIX_RE: Final[re.Pattern[str]] = re.compile(r"^([^:]+):")
_LOG_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+(?:[+-]\d{2}:\d{2})?)\s*\|\s*"
    r"(?P<level>\w+)\s*\|\s*"
    r"(?P<ctx>[^|]*)\|\s*"
    r"(?P<loc>[^|]+)\|\s*"
    r"(?P<msg>.*)$",
)
_TRACE_PAGE_LIMIT: Final[int] = 500


class TurnBundleMetaRecord(TypedDict):
    """First JSONL line — bundle header (D2)."""

    stream: Literal["meta"]
    turn_id: str
    session_id: str
    channel: str
    terminal_status: str
    created_at: str


class TurnBundleLogRecord(TypedDict):
    """One ``gateway.log`` line in the bundle (D2)."""

    stream: Literal["log"]
    ts: str
    level: str
    message: str
    location: str


class TurnBundleMessageRecord(TypedDict):
    """One ``gateway_messages`` row in the bundle (D2)."""

    stream: Literal["message"]
    ts: str
    id: str
    role: str
    kind: str
    content: str
    status: str


class TurnBundleTraceRecord(TypedDict):
    """One ``trace_events`` row in the bundle (D2)."""

    stream: Literal["trace"]
    ts: str
    span_id: str
    kind: str
    status: str
    ts_start_ns: int
    attrs: dict[str, object]


class TurnBundleIndexEntry(TypedDict):
    """One element of ``index.json`` ``turns[]`` (D4)."""

    turn_id: str
    file: str
    session_id: str
    channel: str
    terminal_status: str
    has_error: bool
    processed: bool
    created_at: str


class TurnBundleIndex(TypedDict):
    """Top-level ``index.json`` document (D4)."""

    version: Literal[1]
    turns: list[TurnBundleIndexEntry]


@dataclass(frozen=True, slots=True)
class TurnBundlePaths:
    """Resolved on-disk paths for one turn's bundle artefacts."""

    turns_root: Path
    bundles_dir: Path
    index_path: Path
    bundle_path: Path
    safe_turn_id: str
    turn_id: str
    day_slug: str


@dataclass(frozen=True, slots=True)
class TurnExportCandidate:
    """One turn selected for offline backfill export (W2)."""

    session_id: str
    turn_id: str
    first_seen_at: str


def safe_turn_id(turn_id: str) -> str:
    """Return a filesystem-safe slug for ``turn_id`` (D3).

    Replaces ``:``, ``=``, and ``/`` with ``_``. The original ``turn_id`` is
    stored verbatim inside the bundle meta record and index entry.

    Args:
        turn_id (str): Gateway correlation id
            (``channel:user=…:session=<hex>:msg=<hex>``).

    Returns:
        str: Safe basename stem for ``<safe_turn_id>.jsonl``.

    Examples:
        >>> safe_turn_id("telegram:user=1:session=abc:msg=deadbeef")
        'telegram_user_1_session_abc_msg_deadbeef'
    """
    return turn_id.replace(":", "_").replace("=", "_").replace("/", "_")


def parse_channel_from_turn_id(turn_id: str) -> str:
    """Extract the channel prefix from a correlation id.

    Args:
        turn_id (str): Gateway correlation id.

    Returns:
        str: Channel name, or empty string when the id is malformed.

    Examples:
        >>> parse_channel_from_turn_id("telegram:user=1:session=abc:msg=1")
        'telegram'
    """
    match = _CHANNEL_PREFIX_RE.match(turn_id.strip())
    return match.group(1) if match else ""


def turn_msg_hex_suffix(turn_id: str) -> str | None:
    """Return the ``msg=<hex>`` suffix from ``turn_id`` for log correlation (W0.5).

    Loguru's bound ``msg=`` context field pins the session's **first** message id,
    so per-turn correlation must grep the full ``turn_id`` and this suffix in the
    log line body (see ``tools/explore_gateway_log.py``).

    Args:
        turn_id (str): Gateway correlation id.

    Returns:
        str | None: Lowercase hex id after ``msg=``, or ``None`` when absent.

    Examples:
        >>> turn_msg_hex_suffix("telegram:user=1:session=abc:msg=DeadBeef")
        'deadbeef'
    """
    match = _MSG_HEX_SUFFIX_RE.search(turn_id.strip())
    return match.group(1).lower() if match else None


def turn_log_grep_needles(turn_id: str) -> tuple[str, ...]:
    """Return grep needles for ``logs/gateway.log`` turn correlation (W0.5).

    Always includes the full ``turn_id`` string. When present, also includes
    ``msg=<hex>`` so lines that embed the per-turn suffix match.

    Args:
        turn_id (str): Gateway correlation id.

    Returns:
        tuple[str, ...]: Non-empty needles for :func:`log_line_matches_turn`.

    Examples:
        >>> needles = turn_log_grep_needles("telegram:user=1:session=a:msg=ff")
        >>> needles[0].startswith("telegram:")
        True
        >>> needles[-1]
        'msg=ff'
    """
    needles: list[str] = [turn_id]
    suffix = turn_msg_hex_suffix(turn_id)
    if suffix is not None:
        needles.append(f"msg={suffix}")
    return tuple(needles)


def log_line_matches_turn(line: str, turn_id: str) -> bool:
    """Return whether a raw ``gateway.log`` line belongs to ``turn_id`` (W0.5).

    Matches when any :func:`turn_log_grep_needles` substring appears in the line.
    Reuses the same correlation contract as ``sevn.tools.log_query`` ``pattern``
    filters and ``tools/explore_gateway_log.py``.

    Args:
        line (str): One physical log line (unredacted).
        turn_id (str): Gateway correlation id.

    Returns:
        bool: ``True`` when the line should be included in the turn bundle.

    Examples:
        >>> tid = "telegram:user=1:session=abc:msg=c88777"
        >>> log_line_matches_turn(
        ...     "INFO | x | y | event=triager.input turn_id='telegram:user=1:session=abc:msg=c88777'",
        ...     tid,
        ... )
        True
    """
    return any(needle in line for needle in turn_log_grep_needles(turn_id))


def _log_line_indicates_error(line: str) -> bool:
    """Return whether a log line satisfies the D5 log-error criterion.

    Args:
        line (str): One physical ``gateway.log`` line.

    Returns:
        bool: ``True`` when the line is ERROR-level or contains ``executor_no_answer``.

    Examples:
        >>> _log_line_indicates_error("INFO | x | y | ok")
        False
        >>> _log_line_indicates_error("ERROR | x | y | executor_no_answer tier=B")
        True
    """
    if any(marker in line for marker in _ERROR_LOG_SUBSTRINGS):
        return True
    return any(f"| {level}" in line or f"| {level:<8}" in line for level in _ERROR_LOG_LEVELS)


def compute_has_error(
    *,
    terminal_status: str,
    trace_statuses: list[str] | tuple[str, ...] | None = None,
    log_lines: list[str] | tuple[str, ...] | None = None,
) -> bool:
    """Compute ``has_error`` for ``index.json`` (D5).

    ``True`` when any of:

    * ``terminal_status`` is a terminal failure (currently ``error``).
    * Any trace ``status`` is in :data:`TRACE_ERROR_STATUSES`.
    * Any correlated log line contains ``executor_no_answer`` or an ERROR/CRITICAL level.

    Args:
        terminal_status (str): Gateway turn-end status from ``PostTurnContext``.
        trace_statuses (list[str] | tuple[str, ...] | None): Status column values
            from ``list_trace_events`` for the turn.
        log_lines (list[str] | tuple[str, ...] | None): Correlated ``gateway.log`` lines.

    Returns:
        bool: Whether the turn is an error candidate for ``build-plan-from-errors``.

    Examples:
        >>> compute_has_error(terminal_status="ok")
        False
        >>> compute_has_error(terminal_status="error")
        True
        >>> compute_has_error(terminal_status="ok", trace_statuses=["failed"])
        True
        >>> compute_has_error(
        ...     terminal_status="ok",
        ...     log_lines=["INFO | x | y | executor_no_answer tier=B"],
        ... )
        True
    """
    if terminal_status in TURN_TERMINAL_FAILURE_STATUSES:
        return True
    for status in trace_statuses or ():
        if status in TRACE_ERROR_STATUSES:
            return True
    return any(_log_line_indicates_error(line) for line in log_lines or ())


TurnBundleRecord = (
    TurnBundleMetaRecord | TurnBundleLogRecord | TurnBundleMessageRecord | TurnBundleTraceRecord
)


def effective_turn_bundles_enabled(ws: WorkspaceConfig) -> bool:
    """Return whether the post-turn bundle writer is enabled (D8).

    Args:
        ws (WorkspaceConfig): Parsed workspace root model.

    Returns:
        bool: ``True`` when ``diagnostics.turn_bundles.enabled`` is truthy.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> effective_turn_bundles_enabled(WorkspaceConfig.minimal())
        False
        >>> ws = WorkspaceConfig.minimal(diagnostics={"turn_bundles": {"enabled": True}})
        >>> effective_turn_bundles_enabled(ws)
        True
    """
    extra = ws.model_extra or {}
    diagnostics = extra.get("diagnostics")
    if isinstance(diagnostics, dict):
        turn_bundles = diagnostics.get("turn_bundles")
        if isinstance(turn_bundles, dict) and "enabled" in turn_bundles:
            return bool(turn_bundles["enabled"])
    return DEFAULT_TURN_BUNDLES_ENABLED


def _utc_now_iso() -> str:
    """Return a timezone-aware UTC ISO-8601 timestamp.

    Returns:
        str: ISO-8601 with explicit ``+00:00`` offset.

    Examples:
        >>> _utc_now_iso().endswith("+00:00")
        True
    """
    return datetime.now(tz=UTC).isoformat()


def _ns_to_iso(ts_ns: int) -> str:
    """Convert trace nanoseconds to UTC ISO-8601.

    Args:
        ts_ns (int): ``trace_events.ts_start_ns`` value.

    Returns:
        str: ISO-8601 timestamp.

    Examples:
        >>> _ns_to_iso(0).startswith("1970")
        True
    """
    seconds = max(0, int(ts_ns)) / 1_000_000_000
    return datetime.fromtimestamp(seconds, tz=UTC).isoformat()


def _parse_log_record(line: str) -> TurnBundleLogRecord | None:
    """Parse one loguru ``gateway.log`` line into a bundle log record.

    Args:
        line (str): One physical log line.

    Returns:
        TurnBundleLogRecord | None: Parsed record, or ``None`` when the line shape
            does not match the service log format.

    Examples:
        >>> rec = _parse_log_record(
        ...     "2026-05-28 19:55:15.377+02:00 | INFO  | ctx | path:1 fn | hello"
        ... )
        >>> rec is not None and rec["level"] == "INFO"
        True
    """
    match = _LOG_LINE_RE.match(line)
    if match is None:
        return None
    groups = match.groupdict()
    return TurnBundleLogRecord(
        stream="log",
        ts=groups["ts"].strip(),
        level=groups["level"].strip(),
        message=groups["msg"].strip(),
        location=groups["loc"].strip(),
    )


def _fetch_turn_messages(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    turn_id: str,
) -> list[TurnBundleMessageRecord]:
    """Load ``gateway_messages`` rows for one turn.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle.
        session_id (str): Gateway session id.
        turn_id (str): Turn correlation id.

    Returns:
        list[TurnBundleMessageRecord]: Message stream records ordered by row id.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> _fetch_turn_messages(c, session_id="s", turn_id="t")
        []
    """
    rows = conn.execute(
        """
        SELECT id, role, kind, content, status, created_at
        FROM gateway_messages
        WHERE session_id = ? AND turn_id = ?
        ORDER BY id ASC
        """,
        (session_id, turn_id),
    ).fetchall()
    return [
        TurnBundleMessageRecord(
            stream="message",
            ts=str(created_at),
            id=str(row_id),
            role=str(role),
            kind=str(kind),
            content=str(content),
            status=str(status),
        )
        for row_id, role, kind, content, status, created_at in rows
    ]


def _fetch_turn_traces(
    trace_conn: sqlite3.Connection,
    *,
    session_id: str,
    turn_id: str,
) -> list[TurnBundleTraceRecord]:
    """Load ``trace_events`` rows for one turn via :func:`list_trace_events`.

    Args:
        trace_conn (sqlite3.Connection): Open ``traces.db`` handle.
        session_id (str): Gateway session id.
        turn_id (str): Turn correlation id.

    Returns:
        list[TurnBundleTraceRecord]: Trace stream records sorted by ``ts``.

    Examples:
        >>> import sqlite3
        >>> from sevn.agent.tracing.traces_migrate import apply_traces_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_traces_migrations(c)
        >>> _fetch_turn_traces(c, session_id="s", turn_id="t")
        []
    """
    from sevn.ui.dashboard.query.traces import list_trace_events

    policy = TraceRedactionPolicy.from_defaults()
    items: list[dict[str, object]] = []
    cursor: str | None = None
    while True:
        page = list_trace_events(
            trace_conn,
            limit=_TRACE_PAGE_LIMIT,
            policy=policy,
            cursor=cursor,
            session_id=session_id,
            turn_id=turn_id,
        )
        batch = page.get("items")
        if isinstance(batch, list):
            items.extend(cast("list[dict[str, object]]", batch))
        if not page.get("has_more"):
            break
        next_cursor = page.get("next_cursor")
        cursor = str(next_cursor) if next_cursor else None
        if cursor is None:
            break

    records: list[TurnBundleTraceRecord] = []
    for span in items:
        ts_start_ns = int(str(span.get("ts_start_ns", 0)))
        attrs = span.get("attrs")
        records.append(
            TurnBundleTraceRecord(
                stream="trace",
                ts=_ns_to_iso(ts_start_ns),
                span_id=str(span.get("span_id", "")),
                kind=str(span.get("kind", "")),
                status=str(span.get("status", "")),
                ts_start_ns=ts_start_ns,
                attrs=cast("dict[str, object]", attrs) if isinstance(attrs, dict) else {},
            ),
        )
    records.sort(key=lambda row: (row["ts"], row["span_id"]))
    return records


def _fetch_turn_log_lines(
    content_root: Path, turn_id: str
) -> tuple[list[TurnBundleLogRecord], list[str]]:
    """Grep ``logs/gateway.log`` for lines belonging to ``turn_id`` (W0.5).

    Args:
        content_root (Path): Workspace content root.
        turn_id (str): Turn correlation id.

    Returns:
        tuple[list[TurnBundleLogRecord], list[str]]: Parsed log records and the raw
            matched lines (for :func:`compute_has_error`).

    Examples:
        >>> from pathlib import Path
        >>> recs, raw = _fetch_turn_log_lines(Path("/missing"), "t")
        >>> recs == [] and raw == []
        True
    """
    from sevn.tools.log_query import resolve_log_path

    log_path = resolve_log_path(content_root, "gateway.log")
    if not log_path.is_file():
        return [], []
    raw_lines: list[str] = []
    records: list[TurnBundleLogRecord] = []
    with log_path.open(encoding="utf-8", errors="replace") as handle:
        for physical in handle:
            line = physical.rstrip("\n")
            if not log_line_matches_turn(line, turn_id):
                continue
            raw_lines.append(line)
            parsed = _parse_log_record(line)
            records.append(
                parsed
                if parsed is not None
                else TurnBundleLogRecord(
                    stream="log",
                    ts="",
                    level="",
                    message=line,
                    location="",
                ),
            )
    return records, raw_lines


def collect_turn_bundle_records(
    conn: sqlite3.Connection,
    trace_conn: sqlite3.Connection | None,
    *,
    session_id: str,
    turn_id: str,
    terminal_status: str,
    content_root: Path,
    created_at: str | None = None,
) -> tuple[list[TurnBundleRecord], bool]:
    """Gather meta + interleaved stream records for one turn (W1.1).

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle.
        trace_conn (sqlite3.Connection | None): Open ``traces.db`` handle, or ``None``.
        session_id (str): Gateway session id.
        turn_id (str): Turn correlation id.
        terminal_status (str): Gateway turn-end status.
        content_root (Path): Workspace content root for ``gateway.log``.
        created_at (str | None): Bundle header timestamp; defaults to UTC now.

    Returns:
        tuple[list[TurnBundleRecord], bool]: Records with ``meta`` first, then stream
            rows sorted by ``ts``, and the computed ``has_error`` flag.

    Examples:
        >>> import sqlite3
        >>> from pathlib import Path
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> records, has_error = collect_turn_bundle_records(
        ...     c,
        ...     None,
        ...     session_id="s",
        ...     turn_id="telegram:user=1:session=a:msg=b",
        ...     terminal_status="ok",
        ...     content_root=Path("/tmp"),
        ... )
        >>> records[0]["stream"]
        'meta'
        >>> has_error
        False
    """
    stamp = created_at or _utc_now_iso()
    meta = TurnBundleMetaRecord(
        stream="meta",
        turn_id=turn_id,
        session_id=session_id,
        channel=parse_channel_from_turn_id(turn_id),
        terminal_status=terminal_status,
        created_at=stamp,
    )
    messages = _fetch_turn_messages(conn, session_id=session_id, turn_id=turn_id)
    traces = (
        _fetch_turn_traces(trace_conn, session_id=session_id, turn_id=turn_id)
        if trace_conn is not None
        else []
    )
    log_records, raw_log_lines = _fetch_turn_log_lines(content_root, turn_id)
    stream_rows: list[TurnBundleRecord] = [*messages, *traces, *log_records]
    stream_rows.sort(key=lambda row: (row.get("ts", ""), row["stream"]))
    has_error = compute_has_error(
        terminal_status=terminal_status,
        trace_statuses=[row["status"] for row in traces],
        log_lines=raw_log_lines,
    )
    return [meta, *stream_rows], has_error


def _atomic_write_bytes(final_path: Path, payload: bytes) -> None:
    """Write bytes via temp file + ``os.replace``.

    Args:
        final_path (Path): Destination path.
        payload (bytes): File body.

    Returns:
        None: Always.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> p = Path(tempfile.mkdtemp()) / "bundle.jsonl"
        >>> _atomic_write_bytes(p, b"line\\n")
        >>> p.read_bytes()
        b'line\\n'
    """
    final_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=final_path.parent,
        prefix=f".{final_path.name}-",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        os.replace(tmp_name, final_path)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def load_turn_bundle_index(index_path: Path) -> TurnBundleIndex:
    """Read ``index.json`` or return an empty document when missing.

    Args:
        index_path (Path): ``<content_root>/.sevn/turns/index.json`` path.

    Returns:
        TurnBundleIndex: Parsed index with ``version`` 1.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> idx = load_turn_bundle_index(Path(tempfile.mkdtemp()) / "index.json")
        >>> idx["version"]
        1
    """
    if not index_path.is_file():
        return TurnBundleIndex(version=TURN_BUNDLE_INDEX_VERSION, turns=[])
    try:
        parsed = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return TurnBundleIndex(version=TURN_BUNDLE_INDEX_VERSION, turns=[])
    if not isinstance(parsed, dict):
        return TurnBundleIndex(version=TURN_BUNDLE_INDEX_VERSION, turns=[])
    turns_raw = parsed.get("turns")
    turns: list[TurnBundleIndexEntry] = []
    if isinstance(turns_raw, list):
        for row in turns_raw:
            if isinstance(row, dict) and row.get("turn_id"):
                turns.append(cast("TurnBundleIndexEntry", row))
    return TurnBundleIndex(version=TURN_BUNDLE_INDEX_VERSION, turns=turns)


def upsert_turn_bundle_index_entry(
    index_path: Path,
    entry: TurnBundleIndexEntry,
) -> TurnBundleIndex:
    """Upsert one turn row into ``index.json`` without duplicating ``turn_id`` (W1.2).

    Preserves an existing ``processed`` flag and ``created_at`` when the turn was
    already indexed.

    Args:
        index_path (Path): ``index.json`` path.
        entry (TurnBundleIndexEntry): New or refreshed index row.

    Returns:
        TurnBundleIndex: Updated in-memory index after atomic write.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> root = Path(tempfile.mkdtemp())
        >>> path = root / "index.json"
        >>> row = TurnBundleIndexEntry(
        ...     turn_id="t1",
        ...     file="t1.jsonl",
        ...     session_id="s",
        ...     channel="telegram",
        ...     terminal_status="ok",
        ...     has_error=False,
        ...     processed=False,
        ...     created_at="2026-06-16T00:00:00+00:00",
        ... )
        >>> upsert_turn_bundle_index_entry(path, row)["turns"][0]["turn_id"]
        't1'
    """
    index = load_turn_bundle_index(index_path)
    turns = list(index["turns"])
    replaced = False
    for idx, existing in enumerate(turns):
        if existing["turn_id"] != entry["turn_id"]:
            continue
        merged = TurnBundleIndexEntry(
            turn_id=entry["turn_id"],
            file=entry["file"],
            session_id=entry["session_id"],
            channel=entry["channel"],
            terminal_status=entry["terminal_status"],
            has_error=entry["has_error"],
            processed=existing.get("processed", False),
            created_at=existing.get("created_at", entry["created_at"]),
        )
        turns[idx] = merged
        replaced = True
        break
    if not replaced:
        turns.append(entry)
    updated = TurnBundleIndex(version=TURN_BUNDLE_INDEX_VERSION, turns=turns)
    payload = (json.dumps(updated, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _atomic_write_bytes(index_path, payload)
    return updated


def _resolve_first_seen_at(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    turn_id: str,
    first_seen_at: str | None,
) -> str:
    """Return the UTC first-seen timestamp used for day-folder assignment.

    Prefers an explicit ``first_seen_at`` (export candidates), otherwise the
    earliest ``gateway_messages.created_at`` for the turn, otherwise UTC now.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle.
        session_id (str): Gateway session id.
        turn_id (str): Turn correlation id.
        first_seen_at (str | None): Caller-supplied first-seen ISO timestamp.

    Returns:
        str: ISO-8601 timestamp for :func:`turn_bundle_day_slug`.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> _ = c.execute(
        ...     "INSERT INTO gateway_messages (session_id, turn_id, role, kind, content, status, created_at)"
        ...     " VALUES ('s', 't', 'user', 'message', 'hi', 'sent', '2026-06-16T01:00:00+00:00')"
        ... )
        >>> c.commit()
        >>> _resolve_first_seen_at(c, session_id="s", turn_id="t", first_seen_at=None)
        '2026-06-16T01:00:00+00:00'
    """
    if first_seen_at is not None:
        return first_seen_at
    row = conn.execute(
        """
        SELECT MIN(created_at)
        FROM gateway_messages
        WHERE session_id = ? AND turn_id = ?
        """,
        (session_id, turn_id),
    ).fetchone()
    if row is not None and row[0]:
        return str(row[0])
    return _utc_now_iso()


def write_turn_bundle(
    conn: sqlite3.Connection,
    trace_conn: sqlite3.Connection | None,
    *,
    content_root: Path,
    session_id: str,
    turn_id: str,
    terminal_status: str,
    first_seen_at: str | None = None,
) -> TurnBundlePaths:
    """Serialize one turn bundle JSONL file and upsert ``index.json`` (W1).

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle.
        trace_conn (sqlite3.Connection | None): Open ``traces.db`` handle, or ``None``.
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.
        turn_id (str): Turn correlation id.
        terminal_status (str): Gateway turn-end status.
        first_seen_at (str | None): UTC first-seen timestamp for day-folder assignment
            and bundle meta ``created_at``; defaults to earliest message timestamp.

    Returns:
        TurnBundlePaths: Resolved paths for the written bundle.

    Examples:
        >>> import sqlite3
        >>> from pathlib import Path
        >>> from sevn.storage.migrate import apply_migrations
        >>> root = Path("/tmp/turn-bundle-example")
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> paths = write_turn_bundle(
        ...     c,
        ...     None,
        ...     content_root=root,
        ...     session_id="s",
        ...     turn_id="telegram:user=1:session=a:msg=b",
        ...     terminal_status="ok",
        ... )
        >>> paths.safe_turn_id.startswith("telegram_")
        True
    """
    stamp = _resolve_first_seen_at(
        conn,
        session_id=session_id,
        turn_id=turn_id,
        first_seen_at=first_seen_at,
    )
    paths = bundle_paths(content_root, turn_id, first_seen_at=stamp)
    records, has_error = collect_turn_bundle_records(
        conn,
        trace_conn,
        session_id=session_id,
        turn_id=turn_id,
        terminal_status=terminal_status,
        content_root=content_root,
        created_at=stamp,
    )
    meta = cast("TurnBundleMetaRecord", records[0])
    lines = [json.dumps(record, separators=(",", ":"), sort_keys=True) for record in records]
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    _atomic_write_bytes(paths.bundle_path, payload)
    entry = TurnBundleIndexEntry(
        turn_id=turn_id,
        file=paths.bundle_path.name,
        session_id=session_id,
        channel=meta["channel"],
        terminal_status=terminal_status,
        has_error=has_error,
        processed=False,
        created_at=meta["created_at"],
    )
    upsert_turn_bundle_index_entry(paths.index_path, entry)
    return paths


def parse_since_timestamp(since: str) -> str:
    """Normalize a ``--since`` filter to UTC ISO-8601 for lexicographic compare.

    Args:
        since (str): Operator-supplied timestamp (ISO-8601 or date-only).

    Returns:
        str: Normalized UTC ISO-8601 string.

    Raises:
        ValueError: When ``since`` cannot be parsed.

    Examples:
        >>> parse_since_timestamp("2026-06-16")
        '2026-06-16T00:00:00+00:00'
        >>> parse_since_timestamp("2026-06-16T12:00:00+00:00").endswith("+00:00")
        True
    """
    raw = since.strip()
    if not raw:
        msg = "empty --since value"
        raise ValueError(msg)
    if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
        return f"{raw}T00:00:00+00:00"
    normalized = raw.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def resolve_turn_terminal_status(conn: sqlite3.Connection, turn_id: str) -> str:
    """Resolve ``terminal_status`` for offline export from ``gateway_turn_metadata``.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle.
        turn_id (str): Turn correlation id.

    Returns:
        str: Metadata ``status`` when present, otherwise ``ok``.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> resolve_turn_terminal_status(c, "missing")
        'ok'
    """
    from sevn.gateway.turn.turn_metadata import load_turn_metadata

    meta = load_turn_metadata(conn, turn_id)
    if meta is None:
        return "ok"
    return meta.status


def list_turn_export_candidates(
    conn: sqlite3.Connection,
    *,
    turn_id: str | None = None,
    session_id: str | None = None,
    since: str | None = None,
) -> list[TurnExportCandidate]:
    """List distinct turns matching export selectors (W2.1).

    Candidates come from ``gateway_messages`` grouped by ``(session_id, turn_id)``.
    When ``turn_id`` is set but no message row exists, falls back to
    ``gateway_turn_metadata``.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle.
        turn_id (str | None): Export exactly this correlation id.
        session_id (str | None): Restrict to one gateway session.
        since (str | None): Include turns whose first message is at or after this
            UTC ISO-8601 timestamp (from :func:`parse_since_timestamp`).

    Returns:
        list[TurnExportCandidate]: Distinct turns ordered by ``first_seen_at``.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> list_turn_export_candidates(c)
        []
    """
    since_cutoff: str | None = None
    if since is not None:
        since_cutoff = parse_since_timestamp(since)

    rows = conn.execute(
        """
        SELECT session_id, turn_id, MIN(created_at) AS first_seen_at
        FROM gateway_messages
        WHERE turn_id IS NOT NULL
          AND turn_id != ''
          AND (? IS NULL OR turn_id = ?)
          AND (? IS NULL OR session_id = ?)
        GROUP BY session_id, turn_id
        ORDER BY first_seen_at ASC, turn_id ASC
        """,
        (turn_id, turn_id, session_id, session_id),
    ).fetchall()

    candidates: list[TurnExportCandidate] = []
    seen: set[tuple[str, str]] = set()
    for sess, tid, first_at in rows:
        key = (str(sess), str(tid))
        if key in seen:
            continue
        first_seen = str(first_at)
        if since_cutoff is not None and first_seen < since_cutoff:
            continue
        seen.add(key)
        candidates.append(
            TurnExportCandidate(session_id=key[0], turn_id=key[1], first_seen_at=first_seen),
        )

    if turn_id is not None and not candidates:
        meta_row = conn.execute(
            """
            SELECT session_id, turn_id, started_at
            FROM gateway_turn_metadata
            WHERE turn_id = ?
            LIMIT 1
            """,
            (turn_id,),
        ).fetchone()
        if meta_row is not None:
            sess_s, tid_s, started = str(meta_row[0]), str(meta_row[1]), str(meta_row[2])
            first_seen = started or _utc_now_iso()
            if (since_cutoff is None or first_seen >= since_cutoff) and (
                session_id is None or sess_s == session_id
            ):
                candidates.append(
                    TurnExportCandidate(
                        session_id=sess_s,
                        turn_id=tid_s,
                        first_seen_at=first_seen,
                    ),
                )
    return candidates


def export_turn_bundles(
    conn: sqlite3.Connection,
    trace_conn: sqlite3.Connection | None,
    *,
    content_root: Path,
    turn_id: str | None = None,
    session_id: str | None = None,
    since: str | None = None,
) -> list[TurnBundlePaths]:
    """Backfill or refresh turn bundles from SQLite + logs (W2).

    Overwrites each ``<safe_turn_id>.jsonl`` and upserts ``index.json``. An
    existing ``processed`` flag is preserved via :func:`upsert_turn_bundle_index_entry`.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle.
        trace_conn (sqlite3.Connection | None): Open ``traces.db`` handle, or ``None``.
        content_root (Path): Workspace content root.
        turn_id (str | None): Export exactly this correlation id.
        session_id (str | None): Restrict to one gateway session.
        since (str | None): Lower bound on first message timestamp.

    Returns:
        list[TurnBundlePaths]: Paths written for each exported turn.

    Examples:
        >>> import sqlite3
        >>> from pathlib import Path
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> export_turn_bundles(c, None, content_root=Path("/tmp/w2-empty"))
        []
    """
    candidates = list_turn_export_candidates(
        conn,
        turn_id=turn_id,
        session_id=session_id,
        since=since,
    )
    written: list[TurnBundlePaths] = []
    for candidate in candidates:
        terminal_status = resolve_turn_terminal_status(conn, candidate.turn_id)
        paths = write_turn_bundle(
            conn,
            trace_conn,
            content_root=content_root,
            session_id=candidate.session_id,
            turn_id=candidate.turn_id,
            terminal_status=terminal_status,
            first_seen_at=candidate.first_seen_at,
        )
        written.append(paths)
    return written


def _find_index_entry(index: TurnBundleIndex, turn_id: str) -> TurnBundleIndexEntry | None:
    """Return the index row for ``turn_id``, if present.

    Args:
        index (TurnBundleIndex): Parsed ``index.json`` document.
        turn_id (str): Gateway correlation id.

    Returns:
        TurnBundleIndexEntry | None: Matching row or ``None``.

    Examples:
        >>> row = TurnBundleIndexEntry(
        ...     turn_id="t1",
        ...     file="t1.jsonl",
        ...     session_id="s",
        ...     channel="telegram",
        ...     terminal_status="ok",
        ...     has_error=False,
        ...     processed=False,
        ...     created_at="2026-06-16T00:00:00+00:00",
        ... )
        >>> idx = TurnBundleIndex(version=1, turns=[row])
        >>> _find_index_entry(idx, "t1") is row
        True
        >>> _find_index_entry(idx, "missing") is None
        True
    """
    for entry in index["turns"]:
        if entry["turn_id"] == turn_id:
            return entry
    return None


def _iter_turn_bundle_storage_dirs(turns_root: Path) -> list[Path]:
    """Return day partition dirs and legacy flat ``turns/`` when indexed.

    Args:
        turns_root (Path): ``<content_root>/.sevn/turns`` root.

    Returns:
        list[Path]: Day folders (sorted) plus legacy root when it holds bundles.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> root = Path(tempfile.mkdtemp())
        >>> day = root / "160626"
        >>> day.mkdir()
        >>> _ = (day / "index.json").write_text('{"version":1,"turns":[]}', encoding="utf-8")
        >>> [p.name for p in _iter_turn_bundle_storage_dirs(root)]
        ['160626']
    """
    dirs: list[Path] = []
    if not turns_root.is_dir():
        return dirs
    for child in sorted(turns_root.iterdir()):
        if child.is_dir() and is_turn_bundle_day_slug(child.name):
            dirs.append(child)
    legacy_index = turn_bundle_index_path(turns_root)
    if (legacy_index.is_file() or any(turns_root.glob("*.jsonl"))) and turns_root not in dirs:
        dirs.append(turns_root)
    return dirs


def _resolve_indexed_turn_bundle(
    turns_root: Path,
    turn_id: str,
) -> tuple[Path, TurnBundleIndexEntry] | None:
    """Locate a turn bundle via per-day or legacy flat ``index.json`` files.

    Args:
        turns_root (Path): ``<content_root>/.sevn/turns`` root.
        turn_id (str): Gateway correlation id.

    Returns:
        tuple[Path, TurnBundleIndexEntry] | None: Bundle path and index row when found.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> root = Path(tempfile.mkdtemp())
        >>> _resolve_indexed_turn_bundle(root, "missing") is None
        True
    """
    for storage_dir in _iter_turn_bundle_storage_dirs(turns_root):
        entry = _find_index_entry(
            load_turn_bundle_index(turn_bundle_index_path(storage_dir)), turn_id
        )
        if entry is None:
            continue
        bundle_path = storage_dir / entry["file"]
        if bundle_path.is_file():
            return bundle_path, entry
    return None


def resolve_turn_bundle_file(content_root: Path, turn_id: str) -> tuple[Path, TurnBundleIndexEntry]:
    """Resolve a turn's JSONL bundle path via ``index.json`` (W3.2).

    Args:
        content_root (Path): Workspace ``content_root``.
        turn_id (str): Gateway correlation id.

    Returns:
        tuple[Path, TurnBundleIndexEntry]: Bundle file path and matching index row.

    Raises:
        ValueError: When ``turn_id`` is absent from the index or the bundle file
            is missing on disk.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> root = Path(tempfile.mkdtemp())
        >>> paths = bundle_paths(root, "telegram:user=1:session=a:msg=b", first_seen_at="2026-06-16T00:00:00+00:00")
        >>> paths.bundles_dir.mkdir(parents=True)
        >>> _ = paths.bundle_path.write_text('{"stream":"meta"}\\n', encoding="utf-8")
        >>> _ = upsert_turn_bundle_index_entry(
        ...     paths.index_path,
        ...     TurnBundleIndexEntry(
        ...         turn_id="telegram:user=1:session=a:msg=b",
        ...         file=paths.bundle_path.name,
        ...         session_id="s",
        ...         channel="telegram",
        ...         terminal_status="ok",
        ...         has_error=False,
        ...         processed=False,
        ...         created_at="2026-06-16T00:00:00+00:00",
        ...     ),
        ... )
        >>> bundle, _row = resolve_turn_bundle_file(root, "telegram:user=1:session=a:msg=b")
        >>> bundle == paths.bundle_path
        True
    """
    turns_root = turn_bundles_dir(content_root / ".sevn")
    found = _resolve_indexed_turn_bundle(turns_root, turn_id)
    if found is None:
        msg = f"No turn bundle indexed for turn_id: {turn_id}"
        raise ValueError(msg)
    return found


def load_turn_bundle_records(bundle_path: Path) -> list[TurnBundleRecord]:
    """Read one turn bundle JSONL file from disk (W3).

    Args:
        bundle_path (Path): ``<safe_turn_id>.jsonl`` path.

    Returns:
        list[TurnBundleRecord]: Parsed records in file order.

    Raises:
        ValueError: When the file is empty or the first line is not a ``meta`` record.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> p = Path(tempfile.mkdtemp()) / "bundle.jsonl"
        >>> meta = TurnBundleMetaRecord(
        ...     stream="meta",
        ...     turn_id="t",
        ...     session_id="s",
        ...     channel="telegram",
        ...     terminal_status="ok",
        ...     created_at="2026-06-16T00:00:00+00:00",
        ... )
        >>> _ = p.write_text(json.dumps(meta) + "\\n", encoding="utf-8")
        >>> load_turn_bundle_records(p)[0]["stream"]
        'meta'
    """
    if not bundle_path.is_file():
        msg = f"bundle file not found: {bundle_path}"
        raise ValueError(msg)
    records: list[TurnBundleRecord] = []
    for line_no, raw in enumerate(bundle_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            msg = f"invalid JSON on line {line_no} in {bundle_path}"
            raise ValueError(msg) from exc
        if not isinstance(parsed, dict) or "stream" not in parsed:
            msg = f"invalid bundle record on line {line_no} in {bundle_path}"
            raise ValueError(msg)
        records.append(cast("TurnBundleRecord", parsed))
    if not records or records[0].get("stream") != TURN_BUNDLE_STREAM_META:
        msg = f"bundle missing meta header: {bundle_path}"
        raise ValueError(msg)
    return records


def format_turn_bundle_record(record: TurnBundleRecord) -> str:
    """Format one bundle record as a deterministic plain-text line (W3).

    Args:
        record (TurnBundleRecord): One JSONL object from a turn bundle.

    Returns:
        str: Agent-friendly single-line representation prefixed by ``[stream]``.

    Examples:
        >>> line = format_turn_bundle_record(
        ...     TurnBundleLogRecord(
        ...         stream="log",
        ...         ts="2026-06-16T00:00:00+00:00",
        ...         level="ERROR",
        ...         message="boom",
        ...         location="path:1 fn",
        ...     )
        ... )
        >>> line.startswith("[log]")
        True
        >>> "level=ERROR" in line
        True
    """
    stream = record["stream"]
    if stream == TURN_BUNDLE_STREAM_META:
        meta = cast("TurnBundleMetaRecord", record)
        return (
            f"[meta] turn_id={meta['turn_id']} session_id={meta['session_id']} "
            f"channel={meta['channel']} terminal_status={meta['terminal_status']} "
            f"created_at={meta['created_at']}"
        )
    if stream == "log":
        log = cast("TurnBundleLogRecord", record)
        return (
            f"[log] ts={log['ts']} level={log['level']} location={log['location']} "
            f"message={log['message']}"
        )
    if stream == "message":
        msg = cast("TurnBundleMessageRecord", record)
        return (
            f"[message] ts={msg['ts']} id={msg['id']} role={msg['role']} kind={msg['kind']} "
            f"status={msg['status']} content={msg['content']}"
        )
    trace = cast("TurnBundleTraceRecord", record)
    return (
        f"[trace] ts={trace['ts']} span_id={trace['span_id']} kind={trace['kind']} "
        f"status={trace['status']} ts_start_ns={trace['ts_start_ns']}"
    )


def bundle_record_is_error(
    record: TurnBundleRecord,
    *,
    terminal_status: str,
) -> bool:
    """Return whether a stream row should appear under ``--errors-only`` (W3).

    Args:
        record (TurnBundleRecord): One JSONL bundle row (not ``meta``).
        terminal_status (str): Turn header status from the meta record.

    Returns:
        bool: ``True`` when the row indicates an error condition.

    Examples:
        >>> bundle_record_is_error(
        ...     TurnBundleLogRecord(
        ...         stream="log",
        ...         ts="t",
        ...         level="ERROR",
        ...         message="x",
        ...         location="l",
        ...     ),
        ...     terminal_status="ok",
        ... )
        True
        >>> bundle_record_is_error(
        ...     TurnBundleTraceRecord(
        ...         stream="trace",
        ...         ts="t",
        ...         span_id="s",
        ...         kind="k",
        ...         status="ok",
        ...         ts_start_ns=0,
        ...         attrs={},
        ...     ),
        ...     terminal_status="ok",
        ... )
        False
    """
    stream = record["stream"]
    if stream == "log":
        log = cast("TurnBundleLogRecord", record)
        if any(marker in log["message"] for marker in _ERROR_LOG_SUBSTRINGS):
            return True
        return log["level"].upper() in _ERROR_LOG_LEVELS
    if stream == "trace":
        return cast("TurnBundleTraceRecord", record)["status"] in TRACE_ERROR_STATUSES
    if stream == "message":
        return cast("TurnBundleMessageRecord", record)["status"] in _MESSAGE_ERROR_STATUSES
    if stream == TURN_BUNDLE_STREAM_META:
        return terminal_status in TURN_TERMINAL_FAILURE_STATUSES
    return False


def format_turn_bundle_summary(
    meta: TurnBundleMetaRecord,
    records: list[TurnBundleRecord],
    *,
    has_error: bool | None = None,
) -> str:
    """Render a compact bundle overview for ``--section summary`` (W3).

    Args:
        meta (TurnBundleMetaRecord): Bundle header record.
        records (list[TurnBundleRecord]): Full bundle including ``meta``.
        has_error (bool | None): Index ``has_error`` when known; otherwise derived.

    Returns:
        str: Multi-line plain-text summary.

    Examples:
        >>> meta = TurnBundleMetaRecord(
        ...     stream="meta",
        ...     turn_id="t",
        ...     session_id="s",
        ...     channel="telegram",
        ...     terminal_status="ok",
        ...     created_at="2026-06-16T00:00:00+00:00",
        ... )
        >>> "log_lines:" in format_turn_bundle_summary(meta, [meta])
        True
    """
    stream_rows = [row for row in records if row["stream"] != TURN_BUNDLE_STREAM_META]
    log_rows = [row for row in stream_rows if row["stream"] == "log"]
    message_rows = [row for row in stream_rows if row["stream"] == "message"]
    trace_rows = [row for row in stream_rows if row["stream"] == "trace"]
    terminal_status = meta["terminal_status"]
    error_log = sum(
        1 for row in log_rows if bundle_record_is_error(row, terminal_status=terminal_status)
    )
    error_trace = sum(
        1 for row in trace_rows if bundle_record_is_error(row, terminal_status=terminal_status)
    )
    error_message = sum(
        1 for row in message_rows if bundle_record_is_error(row, terminal_status=terminal_status)
    )
    if has_error is None:
        has_error = compute_has_error(
            terminal_status=terminal_status,
            trace_statuses=[row["status"] for row in trace_rows if row["stream"] == "trace"],
            log_lines=[row["message"] for row in log_rows if row["stream"] == "log"],
        )
    lines = [
        f"turn_id: {meta['turn_id']}",
        f"session_id: {meta['session_id']}",
        f"channel: {meta['channel']}",
        f"terminal_status: {terminal_status}",
        f"created_at: {meta['created_at']}",
        f"has_error: {str(has_error).lower()}",
        f"log_lines: {len(log_rows)}",
        f"message_lines: {len(message_rows)}",
        f"trace_lines: {len(trace_rows)}",
        f"error_log_lines: {error_log}",
        f"error_message_lines: {error_message}",
        f"error_trace_lines: {error_trace}",
    ]
    return "\n".join(lines)


def view_turn_bundle(
    content_root: Path,
    turn_id: str,
    *,
    stream: TurnBundleViewStream | None = None,
    grep: str | None = None,
    errors_only: bool = False,
    section: TurnBundleViewSection | None = None,
) -> list[str]:
    """Return filtered plain-text lines for ``sevn turn-bundle view`` (W3).

    Args:
        content_root (Path): Workspace ``content_root``.
        turn_id (str): Gateway correlation id.
        stream (TurnBundleViewStream | None): Restrict to one stream type.
        grep (str | None): Regex applied to each output line after formatting.
        errors_only (bool): When ``True``, keep only error-indicating stream rows.
        section (TurnBundleViewSection | None): ``meta`` or ``summary`` shortcut view.

    Returns:
        list[str]: Deterministic plain-text lines ready for stdout.

    Raises:
        ValueError: When ``turn_id`` cannot be resolved or ``grep`` is invalid regex.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> root = Path(tempfile.mkdtemp())
        >>> tid = "telegram:user=1:session=a:msg=b"
        >>> paths = bundle_paths(root, tid, first_seen_at="2026-06-16T00:00:00+00:00")
        >>> paths.bundles_dir.mkdir(parents=True)
        >>> meta = TurnBundleMetaRecord(
        ...     stream="meta",
        ...     turn_id=tid,
        ...     session_id="s",
        ...     channel="telegram",
        ...     terminal_status="ok",
        ...     created_at="2026-06-16T00:00:00+00:00",
        ... )
        >>> _ = paths.bundle_path.write_text(json.dumps(meta) + "\\n", encoding="utf-8")
        >>> _ = upsert_turn_bundle_index_entry(
        ...     paths.index_path,
        ...     TurnBundleIndexEntry(
        ...         turn_id=tid,
        ...         file=paths.bundle_path.name,
        ...         session_id="s",
        ...         channel="telegram",
        ...         terminal_status="ok",
        ...         has_error=False,
        ...         processed=False,
        ...         created_at="2026-06-16T00:00:00+00:00",
        ...     ),
        ... )
        >>> view_turn_bundle(root, tid, section="meta")[0].startswith("[meta]")
        True
    """
    bundle_path, index_entry = resolve_turn_bundle_file(content_root, turn_id)
    records = load_turn_bundle_records(bundle_path)
    meta = cast("TurnBundleMetaRecord", records[0])
    if section == "meta":
        lines = [format_turn_bundle_record(meta)]
    elif section == "summary":
        lines = format_turn_bundle_summary(
            meta,
            records,
            has_error=index_entry.get("has_error"),
        ).splitlines()
    else:
        stream_rows = [row for row in records if row["stream"] != TURN_BUNDLE_STREAM_META]
        if stream is not None:
            stream_rows = [row for row in stream_rows if row["stream"] == stream]
        if errors_only:
            stream_rows = [
                row
                for row in stream_rows
                if bundle_record_is_error(row, terminal_status=meta["terminal_status"])
            ]
        lines = [format_turn_bundle_record(row) for row in stream_rows]
    if grep is not None:
        try:
            pattern = re.compile(grep)
        except re.error as exc:
            msg = f"invalid --grep pattern: {grep}"
            raise ValueError(msg) from exc
        lines = [line for line in lines if pattern.search(line)]
    return lines


def bundle_paths(content_root: Path, turn_id: str, *, first_seen_at: str) -> TurnBundlePaths:
    """Resolve bundle directory and file paths for ``turn_id``.

    Day folder assignment uses :func:`turn_bundle_day_slug` on ``first_seen_at``
    (UTC calendar day of the turn's first-seen timestamp).

    Args:
        content_root (Path): Resolved workspace ``content_root``.
        turn_id (str): Gateway correlation id.
        first_seen_at (str): UTC first-seen ISO timestamp for day partitioning.

    Returns:
        TurnBundlePaths: ``.sevn/turns/<DDMMYY>`` paths for the turn bundle.

    Examples:
        >>> from pathlib import Path
        >>> paths = bundle_paths(
        ...     Path("/w"),
        ...     "telegram:user=1:session=a:msg=b",
        ...     first_seen_at="2026-06-16T00:00:00+00:00",
        ... )
        >>> paths.turns_root == Path("/w/.sevn/turns")
        True
        >>> paths.day_slug
        '160626'
        >>> paths.bundles_dir == Path("/w/.sevn/turns/160626")
        True
        >>> paths.bundle_path.name.endswith(".jsonl")
        True
    """
    slug = safe_turn_id(turn_id)
    turns_root = turn_bundles_dir(content_root / ".sevn")
    day_slug = turn_bundle_day_slug(first_seen_at)
    day_dir = turn_bundle_day_dir(turns_root, day_slug)
    return TurnBundlePaths(
        turns_root=turns_root,
        bundles_dir=day_dir,
        index_path=turn_bundle_index_path(day_dir),
        bundle_path=turn_bundle_file_path(day_dir, slug),
        safe_turn_id=slug,
        turn_id=turn_id,
        day_slug=day_slug,
    )


__all__ = [
    "TRACE_ERROR_STATUSES",
    "TURN_BUNDLE_INDEX_VERSION",
    "TURN_BUNDLE_STREAM_META",
    "TURN_TERMINAL_FAILURE_STATUSES",
    "TurnBundleIndex",
    "TurnBundleIndexEntry",
    "TurnBundleLogRecord",
    "TurnBundleMessageRecord",
    "TurnBundleMetaRecord",
    "TurnBundlePaths",
    "TurnBundleRecord",
    "TurnBundleTraceRecord",
    "TurnBundleViewSection",
    "TurnBundleViewStream",
    "TurnExportCandidate",
    "bundle_paths",
    "bundle_record_is_error",
    "collect_turn_bundle_records",
    "compute_has_error",
    "effective_turn_bundles_enabled",
    "export_turn_bundles",
    "format_turn_bundle_record",
    "format_turn_bundle_summary",
    "list_turn_export_candidates",
    "load_turn_bundle_index",
    "load_turn_bundle_records",
    "log_line_matches_turn",
    "parse_channel_from_turn_id",
    "parse_since_timestamp",
    "resolve_turn_bundle_file",
    "resolve_turn_terminal_status",
    "safe_turn_id",
    "turn_log_grep_needles",
    "turn_msg_hex_suffix",
    "upsert_turn_bundle_index_entry",
    "view_turn_bundle",
    "write_turn_bundle",
]
