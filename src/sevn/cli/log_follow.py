"""Follow and merge workspace logs for operators (`sevn logs`, gateway/proxy presets).

Module: sevn.cli.log_follow
Depends: dataclasses, datetime, heapq, json, os, re, select, sqlite3, subprocess, sys, time,
    collections, pathlib, sevn.cli.cli_activity_log, sevn.cli.gateway_client, sevn.cli.log_redact,
    sevn.cli.render.console, sevn.cli.service_manager, sevn.config.loader, sevn.storage.paths

Exports:
    LogEntry — one parsed, sortable unified log line.
    resolve_gateway_log_path — ``{workspace}/logs/gateway.log``.
    resolve_service_log_path — canonical active log for ``gateway`` or ``proxy``.
    resolve_agent_log_path — ``{workspace}/logs/agent.log``.
    resolve_log_paths_for_sources — map sources to log paths under the workspace.
    parse_log_level — extract a normalized level token from one line.
    parse_log_timestamp — parse a timestamp prefix when present.
    collect_merged_log_entries — time-order merge across sources with filters.
    build_logs_insight_summary — error/warn counts, signatures, slow spans, restarts.
    render_logs_insight_summary — Rich panel or plain insight header.
    run_unified_logs — ``sevn logs`` implementation (tail, follow, ``--json``).
    run_gateway_logs — tail/follow gateway logs until interrupt or service stops.
    run_service_logs — tail/follow logs for ``gateway`` or ``proxy``.
"""

from __future__ import annotations

import os
import re
import select
import sqlite3
import subprocess  # nosec B404
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, TextIO

import typer

from sevn.cli.cli_activity_log import resolve_cli_log_path
from sevn.cli.errors import CliPreconditionError
from sevn.cli.gateway_client import probe_gateway_listen_state, probe_proxy_listen_state
from sevn.cli.log_redact import redact_log_line
from sevn.cli.render.console import get_console, is_rich, plain_echo
from sevn.cli.service_manager import plan_install, unit_is_active
from sevn.cli.workspace import sevn_home_dir
from sevn.config.loader import load_workspace
from sevn.storage.paths import traces_sqlite_path

LogSource = Literal["gateway", "proxy", "agent", "cli", "all"]
_ALL_SOURCES: tuple[str, ...] = ("gateway", "proxy", "agent", "cli")
SOURCE_TAGS: dict[str, str] = {
    "gateway": "gw",
    "proxy": "proxy",
    "agent": "agent",
    "cli": "cli",
}
_LEVEL_ORDER: dict[str, int] = {
    "TRACE": 0,
    "DEBUG": 1,
    "INFO": 2,
    "WARNING": 3,
    "WARN": 3,
    "ERROR": 4,
    "CRITICAL": 5,
}
_TS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:[+-]\d{2}:\d{2}|Z)?)"
)
_LEVEL_RE = re.compile(r"\|\s*(TRACE|DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL)\s*\|", re.I)
_RESTART_NAME_RE = re.compile(r"^(gateway|proxy)-(\d{8}T\d{6}Z)\.log$")
_SINCE_RE = re.compile(r"^(\d+)([smhd])$", re.I)
_DEFAULT_INSIGHT_WINDOW = timedelta(hours=24)

# Interval between "is the service still up?" checks while following a log file.
# Avoids hammering GET /health (which shows up in gateway.log as noise).
_GATEWAY_STOP_CHECK_INTERVAL_S = 60.0
_STOP_CHECK_INTERVAL_S = _GATEWAY_STOP_CHECK_INTERVAL_S


def resolve_gateway_log_path(*, operator_home: Path | None = None) -> Path:
    """Return the gateway log file for the operator install.

    Args:
        operator_home (Path | None): ``SEVN_HOME``; defaults to ``sevn_home_dir()``.

    Returns:
        Path: ``<content_root>/logs/gateway.log``.

    Raises:
        CliPreconditionError: When ``workspace/sevn.json`` is missing.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> ws = td / "workspace"
        >>> ws.mkdir()
        >>> _ = (ws / "sevn.json").write_text(
        ...     '{"schema_version": 1, "workspace_root": ".", '
        ...     '"gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        ...     encoding="utf-8",
        ... )
        >>> resolve_gateway_log_path(operator_home=td).name
        'gateway.log'
    """
    home = (operator_home or sevn_home_dir()).expanduser().resolve()
    sevn_json = home / "workspace" / "sevn.json"
    if not sevn_json.is_file():
        msg = f"no workspace/sevn.json under {home}"
        raise CliPreconditionError(msg, exit_code=4)
    _cfg, layout = load_workspace(sevn_json=sevn_json)
    return layout.logs_dir / "gateway.log"


def resolve_service_log_path(
    *,
    service: str,
    operator_home: Path | None = None,
) -> Path:
    """Return the active log file for ``gateway`` or ``proxy``.

    Args:
        service (str): ``gateway`` or ``proxy``.
        operator_home (Path | None): ``SEVN_HOME``; defaults to ``sevn_home_dir()``.

    Returns:
        Path: ``<content_root>/logs/{service}.log``.

    Raises:
        CliPreconditionError: When ``workspace/sevn.json`` is missing or service unknown.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> ws = td / "workspace"
        >>> ws.mkdir()
        >>> _ = (ws / "sevn.json").write_text(
        ...     '{"schema_version": 1, "workspace_root": ".", '
        ...     '"gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        ...     encoding="utf-8",
        ... )
        >>> resolve_service_log_path(service="proxy", operator_home=td).name
        'proxy.log'
    """
    if service not in ("gateway", "proxy"):
        msg = f"unknown service {service!r}; expected gateway or proxy"
        raise CliPreconditionError(msg, exit_code=4)
    home = (operator_home or sevn_home_dir()).expanduser().resolve()
    sevn_json = home / "workspace" / "sevn.json"
    if not sevn_json.is_file():
        msg = f"no workspace/sevn.json under {home}"
        raise CliPreconditionError(msg, exit_code=4)
    _cfg, layout = load_workspace(sevn_json=sevn_json)
    return layout.logs_dir / f"{service}.log"


def resolve_agent_log_path(*, operator_home: Path | None = None) -> Path:
    """Return ``{workspace}/logs/agent.log`` for tier-B/agent structured logs.

    Args:
        operator_home (Path | None): ``SEVN_HOME``; defaults to ``sevn_home_dir()``.

    Returns:
        Path: ``<content_root>/logs/agent.log``.

    Raises:
        CliPreconditionError: When ``workspace/sevn.json`` is missing.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> ws = td / "workspace"
        >>> ws.mkdir()
        >>> _ = (ws / "sevn.json").write_text(
        ...     '{"schema_version": 1, "workspace_root": ".", '
        ...     '"gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        ...     encoding="utf-8",
        ... )
        >>> resolve_agent_log_path(operator_home=td).name
        'agent.log'
    """
    home = (operator_home or sevn_home_dir()).expanduser().resolve()
    sevn_json = home / "workspace" / "sevn.json"
    if not sevn_json.is_file():
        msg = f"no workspace/sevn.json under {home}"
        raise CliPreconditionError(msg, exit_code=4)
    _cfg, layout = load_workspace(sevn_json=sevn_json)
    return layout.logs_dir / "agent.log"


def _normalize_sources(source: LogSource) -> tuple[str, ...]:
    """Expand ``all`` into the four unified log sources.

    Args:
        source (LogSource): Requested source selector.

    Returns:
        tuple[str, ...]: Concrete source names.

    Examples:
        >>> _normalize_sources("all") == ("gateway", "proxy", "agent", "cli")
        True
    """
    if source == "all":
        return _ALL_SOURCES
    return (source,)


def resolve_log_paths_for_sources(
    *,
    source: LogSource,
    operator_home: Path | None = None,
) -> dict[str, Path]:
    """Map log sources to absolute paths under the bound workspace.

    Args:
        source (LogSource): One source or ``all``.
        operator_home (Path | None): ``SEVN_HOME`` override.

    Returns:
        dict[str, Path]: ``{source: path}`` for each requested source.

    Raises:
        CliPreconditionError: When the workspace is not bound.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> ws = td / "workspace"
        >>> ws.mkdir()
        >>> _ = (ws / "sevn.json").write_text(
        ...     '{"schema_version": 1, "workspace_root": ".", '
        ...     '"gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        ...     encoding="utf-8",
        ... )
        >>> paths = resolve_log_paths_for_sources(source="gateway", operator_home=td)
        >>> paths["gateway"].name
        'gateway.log'
    """
    names = _normalize_sources(source)
    resolvers = {
        "gateway": lambda: resolve_service_log_path(service="gateway", operator_home=operator_home),
        "proxy": lambda: resolve_service_log_path(service="proxy", operator_home=operator_home),
        "agent": lambda: resolve_agent_log_path(operator_home=operator_home),
        "cli": lambda: resolve_cli_log_path(operator_home=operator_home),
    }
    return {name: resolvers[name]() for name in names}


def parse_log_timestamp(line: str) -> datetime | None:
    """Parse a leading timestamp from a service or ``[cli]`` log line.

    Args:
        line (str): One log line.

    Returns:
        datetime | None: Parsed aware timestamp, or ``None`` when absent.

    Examples:
        >>> parse_log_timestamp("2026-06-17 12:00:00.123+00:00 | INFO | x")
        datetime.datetime(2026, 6, 17, 12, 0, 0, 123000, tzinfo=datetime.timezone.utc)
    """
    match = _TS_RE.match(line.strip())
    if match is None:
        return None
    raw = match.group(1).replace("T", " ")
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            parsed = datetime.strptime(raw, fmt)  # noqa: DTZ007 — naive results localized to UTC below
        except ValueError:
            continue
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed
    return None


def parse_log_level(line: str) -> str:
    """Extract a normalized level token from one log line.

    Args:
        line (str): One log line.

    Returns:
        str: Uppercase level (defaults to ``INFO``).

    Examples:
        >>> parse_log_level("2026-06-17 12:00:00.123+00:00 | ERROR | - | x")
        'ERROR'
        >>> parse_log_level("plain line without level")
        'INFO'
    """
    match = _LEVEL_RE.search(line)
    if match is None:
        upper = line.upper()
        for level in ("ERROR", "WARNING", "WARN", "DEBUG", "TRACE", "CRITICAL"):
            if level in upper:
                return "WARN" if level == "WARNING" else level  # nosec B105 — log level alias
        return "INFO"
    token = match.group(1).upper()
    return "WARN" if token == "WARNING" else token  # nosec B105 — log level alias


def _parse_since_window(since: str | None) -> timedelta:
    """Parse ``--since`` duration strings such as ``1h`` or ``30m``.

    Args:
        since (str | None): Operator duration or ``None`` for the default window.

    Returns:
        timedelta: Lookback window for filters and insight summary.

    Examples:
        >>> _parse_since_window("1h") == timedelta(hours=1)
        True
    """
    if since is None:
        return _DEFAULT_INSIGHT_WINDOW
    text = since.strip()
    if not text:
        return _DEFAULT_INSIGHT_WINDOW
    match = _SINCE_RE.fullmatch(text)
    if match is None:
        parsed = parse_log_timestamp(text)
        if parsed is not None:
            delta = datetime.now(UTC) - parsed.astimezone(UTC)
            return max(delta, timedelta(seconds=1))
        return _DEFAULT_INSIGHT_WINDOW
    amount = int(match.group(1))
    unit = match.group(2).lower()
    if unit == "s":
        return timedelta(seconds=amount)
    if unit == "m":
        return timedelta(minutes=amount)
    if unit == "h":
        return timedelta(hours=amount)
    return timedelta(days=amount)


def _level_matches(level: str, minimum: str | None) -> bool:
    """Return True when ``level`` meets the ``--level`` minimum threshold.

    Args:
        level (str): Parsed line level.
        minimum (str | None): Requested minimum level.

    Returns:
        bool: Whether the line passes the threshold filter.

    Examples:
        >>> _level_matches("ERROR", "WARNING")
        True
        >>> _level_matches("INFO", "ERROR")
        False
    """
    if minimum is None:
        return True
    floor = minimum.upper()
    if floor == "WARNING":  # nosec B105 — log level alias
        floor = "WARN"
    line_level = level.upper()
    if line_level == "WARNING":  # nosec B105 — log level alias
        line_level = "WARN"
    return _LEVEL_ORDER.get(line_level, 2) >= _LEVEL_ORDER.get(floor, 2)


@dataclass(frozen=True, order=True)
class LogEntry:
    """One parsed, sortable log line from a unified merge."""

    sort_key: tuple[float, int, str]
    timestamp: datetime | None
    level: str
    source: str
    raw_line: str
    display_line: str


def _decorate_line(*, source: str, line: str) -> str:
    """Prefix a line with a source tag when not already present.

    Args:
        source (str): Canonical source name.
        line (str): Redacted log line.

    Returns:
        str: Display line with ``[tag]`` when missing.

    Examples:
        >>> "[gw]" in _decorate_line(source="gateway", line="hello")
        True
    """
    tag = SOURCE_TAGS[source]
    bracket = f"[{tag}]"
    if bracket in line:
        return line
    parts = line.split(" | ", 2)
    if len(parts) >= 3 and _TS_RE.match(parts[0]):
        return f"{parts[0]} | {parts[1]} | {bracket} | {parts[2]}"
    return f"{bracket} | {line}"


def _read_source_lines(path: Path, *, source: str) -> list[tuple[int, str]]:
    """Read lines from ``path`` when it exists.

    Args:
        path (Path): Log file path.
        source (str): Source name (for doctest stability only).

    Returns:
        list[tuple[int, str]]: ``(line_no, text)`` pairs.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> p = td / "g.log"
        >>> _ = p.write_text("a\\n", encoding="utf-8")
        >>> _read_source_lines(p, source="gateway")
        [(1, 'a')]
    """
    _ = source
    if not path.is_file():
        return []
    try:
        raw = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return list(enumerate(raw, start=1))


def collect_merged_log_entries(
    paths: dict[str, Path],
    *,
    lines: int = 50,
    since: str | None = None,
    grep: str | None = None,
    level: str | None = None,
) -> list[LogEntry]:
    """Merge log lines across sources in timestamp order.

    Args:
        paths (dict[str, Path]): Source → log path map.
        lines (int): Maximum merged lines to return (tail window).
        since (str | None): Duration or timestamp cutoff.
        grep (str | None): Case-insensitive substring filter.
        level (str | None): Minimum log level filter.

    Returns:
        list[LogEntry]: Newest ``lines`` entries after filters, oldest-first.

    Examples:
        >>> import tempfile
        >>> from datetime import timedelta
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> gw = td / "gateway.log"
        >>> cli = td / "cli.log"
        >>> base = datetime.now(UTC) - timedelta(hours=1)  # within the since="30d" window
        >>> def _ts(offset_s):
        ...     return (base + timedelta(seconds=offset_s)).isoformat(sep=" ")
        >>> _ = gw.write_text(
        ...     f"{_ts(0)} | INFO | - | - | early\\n"
        ...     f"{_ts(1)} | ERROR | - | - | boom\\n",
        ...     encoding="utf-8",
        ... )
        >>> _ = cli.write_text(
        ...     f"{_ts(0.5)} | INFO | [cli] | mid\\n",
        ...     encoding="utf-8",
        ... )
        >>> entries = collect_merged_log_entries(
        ...     {"gateway": gw, "cli": cli}, lines=10, since="30d"
        ... )
        >>> [e.source for e in entries]
        ['gateway', 'cli', 'gateway']
    """
    window = _parse_since_window(since)
    cutoff = datetime.now(UTC) - window
    pattern = re.compile(grep, re.I) if grep else None
    merged: list[LogEntry] = []
    for source, path in paths.items():
        for line_no, raw in _read_source_lines(path, source=source):
            redacted = redact_log_line(raw)
            if pattern is not None and pattern.search(redacted) is None:
                continue
            level_token = parse_log_level(redacted)
            if not _level_matches(level_token, level):
                continue
            ts = parse_log_timestamp(redacted)
            if ts is not None and ts.astimezone(UTC) < cutoff:
                continue
            sort_ts = ts.timestamp() if ts is not None else float(line_no)
            display = _decorate_line(source=source, line=redacted)
            merged.append(
                LogEntry(
                    sort_key=(sort_ts, line_no, source),
                    timestamp=ts,
                    level=level_token,
                    source=source,
                    raw_line=redacted,
                    display_line=display,
                )
            )
    merged.sort()
    if lines > 0 and len(merged) > lines:
        merged = merged[-lines:]
    return merged


def _normalize_error_signature(line: str) -> str:
    """Collapse volatile tokens so error lines group by signature.

    Args:
        line (str): One log line.

    Returns:
        str: Normalized signature string.

    Examples:
        >>> sig = _normalize_error_signature("2026-06-17 | ERROR | timeout id=99")
        >>> "99" not in sig
        True
    """
    text = line
    text = _TS_RE.sub("", text)
    text = re.sub(r"\b[0-9a-f]{8,}\b", "<id>", text, flags=re.I)
    text = re.sub(r"\b\d+\b", "<n>", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:160] or line[:160]


def _recent_restarts(logs_dir: Path, *, since: datetime) -> list[dict[str, str]]:
    """List rotated ``gateway``/``proxy`` logs created after ``since``.

    Args:
        logs_dir (Path): Workspace ``logs/`` directory.
        since (datetime): Cutoff timestamp.

    Returns:
        list[dict[str, str]]: Recent restart events newest-first.

    Examples:
        >>> _recent_restarts(Path("/missing"), since=datetime.now(UTC))
        []
    """
    if not logs_dir.is_dir():
        return []
    events: list[dict[str, str]] = []
    for path in logs_dir.iterdir():
        if not path.is_file():
            continue
        match = _RESTART_NAME_RE.match(path.name)
        if match is None:
            continue
        service, stamp = match.group(1), match.group(2)
        try:
            rotated_at = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        except ValueError:
            continue
        if rotated_at < since.astimezone(UTC):
            continue
        events.append(
            {
                "service": service,
                "rotated_at": rotated_at.isoformat(),
                "path": path.name,
            }
        )
    events.sort(key=lambda row: row["rotated_at"], reverse=True)
    return events[:5]


def _query_slow_spans(dot_sevn: Path, *, since_ns: int, limit: int = 5) -> list[dict[str, Any]]:
    """Return slowest completed spans from ``traces.db`` when present.

    Args:
        dot_sevn (Path): Workspace ``.sevn`` directory.
        since_ns (int): Inclusive ``ts_start_ns`` cutoff.
        limit (int): Maximum rows.

    Returns:
        list[dict[str, Any]]: Span summaries for the insight header.

    Examples:
        >>> _query_slow_spans(Path("/nonexistent/.sevn"), since_ns=0)
        []
    """
    db_path = traces_sqlite_path(dot_sevn)
    if not db_path.is_file():
        return []
    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error:
        return []
    try:
        rows = conn.execute(
            """
            SELECT span_id, session_id, turn_id, kind,
                   (ts_end_ns - ts_start_ns) AS duration_ns, status
            FROM trace_events
            WHERE ts_end_ns IS NOT NULL
              AND ts_start_ns IS NOT NULL
              AND ts_start_ns >= ?
            ORDER BY duration_ns DESC
            LIMIT ?
            """,
            (since_ns, limit),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    return [
        {
            "span_id": row[0],
            "session_id": row[1],
            "turn_id": row[2],
            "kind": row[3],
            "duration_ms": round(int(row[4]) / 1_000_000, 1),
            "status": row[5],
        }
        for row in rows
    ]


def _query_top_error_kinds(
    dot_sevn: Path, *, since_ns: int, limit: int = 5
) -> list[dict[str, Any]]:
    """Aggregate hourly rollup error counts by span kind.

    Args:
        dot_sevn (Path): Workspace ``.sevn`` directory.
        since_ns (int): Inclusive ``hour_bucket_ns`` cutoff.
        limit (int): Maximum rows.

    Returns:
        list[dict[str, Any]]: Top error kinds for the insight header.

    Examples:
        >>> _query_top_error_kinds(Path("/nonexistent/.sevn"), since_ns=0)
        []
    """
    db_path = traces_sqlite_path(dot_sevn)
    if not db_path.is_file():
        return []
    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error:
        return []
    try:
        rows = conn.execute(
            """
            SELECT kind, SUM(error_count) AS errors
            FROM trace_rollups_hourly
            WHERE hour_bucket_ns >= ?
            GROUP BY kind
            HAVING errors > 0
            ORDER BY errors DESC
            LIMIT ?
            """,
            (since_ns, limit),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    return [{"kind": row[0], "errors": int(row[1])} for row in rows]


def build_logs_insight_summary(
    entries: list[LogEntry],
    *,
    logs_dir: Path,
    dot_sevn: Path,
    since: str | None = None,
) -> dict[str, Any]:
    """Build the insight summary object for ``sevn logs``.

    Args:
        entries (list[LogEntry]): Merged lines in the active window.
        logs_dir (Path): Workspace ``logs/`` directory.
        dot_sevn (Path): Workspace ``.sevn`` directory.
        since (str | None): Lookback window for trace queries.

    Returns:
        dict[str, Any]: Summary payload for human/JSON rendering.

    Examples:
        >>> from pathlib import Path
        >>> build_logs_insight_summary([], logs_dir=Path("/tmp"), dot_sevn=Path("/tmp/.sevn"))[
        ...     "error_count"
        ... ]
        0
    """
    window = _parse_since_window(since)
    cutoff = datetime.now(UTC) - window
    since_ns = int(cutoff.timestamp() * 1_000_000_000)
    errors = sum(1 for entry in entries if entry.level == "ERROR")
    warnings = sum(1 for entry in entries if entry.level in {"WARN", "WARNING"})
    signatures = Counter(
        _normalize_error_signature(entry.raw_line) for entry in entries if entry.level == "ERROR"
    )
    top_errors = [
        {"signature": sig, "count": count} for sig, count in signatures.most_common(5) if sig
    ]
    return {
        "window": since or "24h",
        "error_count": errors,
        "warning_count": warnings,
        "top_error_signatures": top_errors,
        "slowest_spans": _query_slow_spans(dot_sevn, since_ns=since_ns),
        "top_error_kinds": _query_top_error_kinds(dot_sevn, since_ns=since_ns),
        "recent_restarts": _recent_restarts(logs_dir, since=cutoff),
    }


def render_logs_insight_summary(summary: dict[str, Any]) -> None:
    """Render the insight summary header (Rich panel or plain text).

    Args:
        summary (dict[str, Any]): Payload from :func:`build_logs_insight_summary`.

    Returns:
        None

    Examples:
        >>> import io
        >>> from contextlib import redirect_stdout
        >>> buf = io.StringIO()
        >>> with redirect_stdout(buf):
        ...     render_logs_insight_summary({"window": "1h", "error_count": 0, "warning_count": 0,
        ...         "top_error_signatures": [], "slowest_spans": [], "top_error_kinds": [],
        ...         "recent_restarts": []})
        >>> "Insight" in buf.getvalue()
        True
    """
    lines = [
        f"Insight ({summary.get('window', '24h')}): "
        f"{summary.get('error_count', 0)} errors · "
        f"{summary.get('warning_count', 0)} warnings",
    ]
    for item in summary.get("top_error_signatures", [])[:3]:
        lines.append(f"  top error: {item['count']}x {item['signature']}")
    for item in summary.get("slowest_spans", [])[:3]:
        from sevn.cli.traces_read import traces_drilldown_hint

        session = str(item.get("session_id") or "")
        session_hint = f"{session[:8]}…" if len(session) > 8 else session or "?"
        lines.append(
            f"  slow span: {item['duration_ms']}ms {item['kind']} (session {session_hint})"
        )
        if session:
            lines.append(f"    → {traces_drilldown_hint(session)}")
    for item in summary.get("recent_restarts", [])[:3]:
        lines.append(f"  restart: {item['service']} rotated at {item['rotated_at']}")
    body = "\n".join(lines)
    if is_rich():
        from rich.panel import Panel

        get_console().print(Panel(body, title="sevn logs insight", border_style="cyan"))
        return
    plain_echo(body)
    plain_echo("")


def _emit_log_entries(entries: list[LogEntry], *, json_mode: bool) -> list[str]:
    """Print or collect decorated log lines.

    Args:
        entries (list[LogEntry]): Lines to emit.
        json_mode (bool): When True, skip stdout and return strings only.

    Returns:
        list[str]: Display lines (for ``--json`` payloads).

    Examples:
        >>> from pathlib import Path
        >>> e = LogEntry((1.0, 1, "gateway"), None, "INFO", "gateway", "x", "[gw] | x")
        >>> _emit_log_entries([e], json_mode=True)
        ['[gw] | x']
    """
    out: list[str] = []
    for entry in entries:
        line = entry.display_line
        out.append(line)
        if not json_mode:
            if is_rich():
                style = None
                if entry.level == "ERROR":
                    style = "red"
                elif entry.level in {"WARN", "WARNING"}:
                    style = "yellow"
                get_console().print(line, style=style)
            else:
                plain_echo(line)
    return out


def _follow_unified_plain(
    paths: dict[str, Path],
    *,
    poll_s: float = 1.0,
    level: str | None = None,
    grep: str | None = None,
) -> None:
    """Stream merged follow output on non-TTY stdout.

    Args:
        paths (dict[str, Path]): Active log paths per source.
        poll_s (float): Poll interval when no new data.
        level (str | None): Minimum level filter.
        grep (str | None): Substring filter.

    Returns:
        None

    Examples:
        >>> _follow_unified_plain({}, poll_s=0.01) is None
        True
    """
    if not paths:
        return
    handles: dict[str, Any] = {}
    pattern = re.compile(grep, re.I) if grep else None
    try:
        for source, path in paths.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            fh = path.open("a+", encoding="utf-8", errors="replace")
            fh.seek(0, os.SEEK_END)
            handles[source] = fh
        while True:
            batch: list[LogEntry] = []
            for source, fh in handles.items():
                while True:
                    line = fh.readline()
                    if not line:
                        break
                    redacted = redact_log_line(line.rstrip("\n"))
                    if pattern is not None and pattern.search(redacted) is None:
                        continue
                    level_token = parse_log_level(redacted)
                    if not _level_matches(level_token, level):
                        continue
                    ts = parse_log_timestamp(redacted)
                    sort_ts = ts.timestamp() if ts is not None else time.time()
                    batch.append(
                        LogEntry(
                            sort_key=(sort_ts, 0, source),
                            timestamp=ts,
                            level=level_token,
                            source=source,
                            raw_line=redacted,
                            display_line=_decorate_line(source=source, line=redacted),
                        )
                    )
            for entry in sorted(batch):
                plain_echo(entry.display_line)
            if not batch:
                time.sleep(poll_s)
    except KeyboardInterrupt:
        return
    finally:
        for fh in handles.values():
            fh.close()


def _follow_unified_tty(
    paths: dict[str, Path],
    *,
    seed_entries: list[LogEntry],
    level: str | None = None,
    grep: str | None = None,
) -> None:
    """Follow logs in the Textual viewer on an interactive TTY.

    Args:
        paths (dict[str, Path]): Active log paths per source.
        seed_entries (list[LogEntry]): Initial scrollback.
        level (str | None): Minimum level filter.
        grep (str | None): Substring filter.

    Returns:
        None

    Examples:
        >>> from pathlib import Path
        >>> from unittest.mock import patch
        >>> with patch("sevn.cli.tui.textual_ui_allowed", return_value=False):
        ...     _follow_unified_tty({}, seed_entries=[]) is None
        True
    """
    from sevn.cli.tui import textual_ui_allowed

    if not textual_ui_allowed():
        _follow_unified_plain(paths, level=level, grep=grep)
        return
    from sevn.cli.tui.log_viewer import LogViewerApp

    level_filter = {level.upper()} if level else None
    if level_filter and "WARNING" in level_filter:  # nosec B105 — log level alias
        level_filter.add("WARN")
    app = LogViewerApp(
        title="sevn logs",
        status=f"sources={','.join(sorted(paths))} follow=on",
        level_filter=level_filter,
        grep=grep,
    )
    for entry in seed_entries:
        app.append_entry(entry.display_line, source=entry.source, level=entry.level)
    pattern = re.compile(grep, re.I) if grep else None

    def _poll_files() -> None:
        handles: dict[str, Any] = {}
        try:
            for source, path in paths.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                fh = path.open("a+", encoding="utf-8", errors="replace")
                fh.seek(0, os.SEEK_END)
                handles[source] = fh
            # This thread is started *before* ``app.run()`` below, so the app is
            # not running yet at this point. Wait for it to come up; otherwise the
            # ``while app.is_running`` guard trips on the initial pre-run False
            # state and the thread exits without ever tailing a line — the seed
            # scrollback renders but live updates never arrive until the operator
            # quits and re-runs (which only rebuilds the seed).
            startup_deadline = time.monotonic() + 10.0
            while not app.is_running and time.monotonic() < startup_deadline:
                time.sleep(0.05)
            while app.is_running:
                for source, fh in handles.items():
                    while True:
                        line = fh.readline()
                        if not line:
                            break
                        redacted = redact_log_line(line.rstrip("\n"))
                        if pattern is not None and pattern.search(redacted) is None:
                            continue
                        level_token = parse_log_level(redacted)
                        display = _decorate_line(source=source, line=redacted)
                        app.call_from_thread(
                            app.append_entry,
                            display,
                            source=source,
                            level=level_token,
                        )
                time.sleep(0.5)
        finally:
            for fh in handles.values():
                fh.close()

    import threading

    thread = threading.Thread(target=_poll_files, daemon=True)
    thread.start()
    app.run()


def run_unified_logs(
    *,
    source: LogSource = "all",
    lines: int = 50,
    follow: bool = False,
    since: str | None = None,
    grep: str | None = None,
    level: str | None = None,
    json_mode: bool = False,
    include_summary: bool = True,
    operator_home: Path | None = None,
    json_stream: TextIO | None = None,
) -> None:
    """Run unified ``sevn logs`` tail/follow with optional insight summary.

    Args:
        source (LogSource): One source or ``all``.
        lines (int): Tail size before follow.
        follow (bool): Follow new lines until interrupt.
        since (str | None): Lookback window for tail + summary.
        grep (str | None): Case-insensitive pattern filter.
        level (str | None): Minimum log level.
        json_mode (bool): Emit JSON envelope instead of human output.
        include_summary (bool): Render/return the insight header.
        operator_home (Path | None): ``SEVN_HOME`` override.
        json_stream (TextIO | None): Optional stream for JSON tests.

    Returns:
        None

    Raises:
        typer.Exit: On workspace precondition failures or invalid follow context.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from unittest.mock import patch
        >>> td = Path(tempfile.mkdtemp())
        >>> ws = td / "workspace"
        >>> ws.mkdir()
        >>> _ = (ws / "sevn.json").write_text(
        ...     '{"schema_version": 1, "workspace_root": ".", '
        ...     '"gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        ...     encoding="utf-8",
        ... )
        >>> (ws / "logs").mkdir(exist_ok=True)
        >>> _ = (ws / "logs" / "gateway.log").write_text("plain\\n", encoding="utf-8")
        >>> with patch("sevn.cli.log_follow.typer.echo"):
        ...     run_unified_logs(source="gateway", lines=1, follow=False, operator_home=td)
    """
    from sevn.cli.json_util import emit_json_success

    try:
        home = (operator_home or sevn_home_dir()).expanduser().resolve()
        _cfg, layout = load_workspace(sevn_json=home / "workspace" / "sevn.json")
        paths = resolve_log_paths_for_sources(source=source, operator_home=home)
    except CliPreconditionError as exc:
        typer.secho(str(exc), err=True)
        raise typer.Exit(getattr(exc, "exit_code", 4)) from exc

    entries = collect_merged_log_entries(
        paths,
        lines=lines,
        since=since,
        grep=grep,
        level=level,
    )
    summary = build_logs_insight_summary(
        entries,
        logs_dir=layout.logs_dir,
        dot_sevn=layout.dot_sevn,
        since=since,
    )

    if json_mode:
        if follow:
            typer.secho("--json does not support --follow", err=True)
            raise typer.Exit(2)
        payload = {
            "summary": summary,
            "lines": _emit_log_entries(entries, json_mode=True),
            "sources": sorted(paths),
        }
        emit_json_success(command="sevn logs", data=payload, stream=json_stream)
        return

    if include_summary:
        render_logs_insight_summary(summary)

    _emit_log_entries(entries, json_mode=False)

    if not follow:
        return
    if not sys.stdout.isatty():
        _follow_unified_plain(paths, level=level, grep=grep)
        return
    _follow_unified_tty(paths, seed_entries=entries, level=level, grep=grep)


def _probe_proxy_running(*, workspace_cfg: object) -> bool:
    """Return True when the proxy user unit or ``/healthz`` reports running.

    Args:
        workspace_cfg (object): Parsed workspace config.

    Returns:
        bool: Whether the proxy appears to be up.

    Examples:
        >>> from unittest.mock import patch
        >>> with patch("sevn.cli.log_follow.unit_is_active", return_value=False), patch(
        ...     "sevn.cli.log_follow.probe_proxy_listen_state", return_value="running"
        ... ):
        ...     _probe_proxy_running(workspace_cfg=object()) is True
        True
    """
    if unit_is_active(home=Path.home(), service="proxy"):
        return True
    return probe_proxy_listen_state(workspace=workspace_cfg) == "running"  # type: ignore[arg-type]


def _service_stopped(*, service: str, workspace_cfg: object) -> bool:
    """Return True when neither the user unit nor health probe reports running.

    Args:
        service (str): ``gateway`` or ``proxy``.
        workspace_cfg (object): Parsed workspace config.

    Returns:
        bool: Whether follow should end.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _service_stopped(service="gateway", workspace_cfg=WorkspaceConfig.minimal()) in (True, False)
        True
    """
    if service == "proxy":
        return not _probe_proxy_running(workspace_cfg=workspace_cfg)
    return _gateway_stopped(workspace_cfg=workspace_cfg)


def _gateway_stopped(*, workspace_cfg: object) -> bool:
    """Return True when neither the user unit nor ``/health`` reports running.

    Args:
        workspace_cfg (object): Parsed workspace config.

    Returns:
        bool: Whether follow should end.

    Examples:
        >>> from unittest.mock import patch
        >>> with patch("sevn.cli.log_follow.unit_is_active", return_value=False), patch(
        ...     "sevn.cli.log_follow.probe_gateway_listen_state", return_value="absent"
        ... ):
        ...     _gateway_stopped(workspace_cfg=object()) is True
        True
    """
    home = Path.home()
    if unit_is_active(home=home, service="gateway"):
        return False
    state = probe_gateway_listen_state(workspace=workspace_cfg)  # type: ignore[arg-type]
    return state != "running"


def _print_tail(path: Path, *, lines: int) -> None:
    """Print the last ``lines`` redacted lines from ``path``.

    Args:
        path (Path): Log file.
        lines (int): Maximum lines to emit.

    Returns:
        None

    Examples:
        >>> _print_tail(Path("/nonexistent"), lines=0) is None
        True
    """
    if not path.is_file():
        return
    try:
        raw = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    for line in raw[-lines:]:
        typer.echo(redact_log_line(line))


def _follow_file(
    path: Path,
    *,
    workspace_cfg: object,
    poll_s: float = 1.0,
    service: str = "gateway",
) -> None:
    """Follow ``path`` until Ctrl+C or the service stops.

    Args:
        path (Path): Log file (created if missing when following).
        workspace_cfg (object): Parsed workspace for health probes.
        poll_s (float): Interval between stop checks.
        service (str): ``gateway`` or ``proxy`` for stop probes.

    Returns:
        None

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from unittest.mock import patch
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> td = Path(tempfile.mkdtemp())
        >>> p = td / "g.log"
        >>> _ = p.write_text("a\\n", encoding="utf-8")
        >>> with patch("sevn.cli.log_follow.unit_is_active", return_value=False), patch(
        ...     "sevn.cli.log_follow.probe_gateway_listen_state", return_value="absent"
        ... ):
        ...     _follow_file(p, workspace_cfg=WorkspaceConfig.minimal(), poll_s=0.01) is None
        True
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8", errors="replace") as fh:
        fh.seek(0, os.SEEK_END)
        last_stop_check = 0.0
        gateway_stopped = False
        try:
            while True:
                now = time.monotonic()
                if now - last_stop_check >= _STOP_CHECK_INTERVAL_S:
                    gateway_stopped = _service_stopped(service=service, workspace_cfg=workspace_cfg)
                    last_stop_check = now
                if gateway_stopped:
                    return
                line = fh.readline()
                if line:
                    typer.echo(redact_log_line(line))
                    continue
                if sys.stdin.isatty():
                    rlist, _, _ = select.select([fh], [], [], poll_s)
                    if not rlist:
                        continue
                else:
                    time.sleep(poll_s)
        except KeyboardInterrupt:
            return


def _follow_journal(*, lines: int) -> None:
    """Stream systemd user unit logs for the gateway.

    Args:
        lines (int): Historical lines before follow.

    Returns:
        None

    Raises:
        CliPreconditionError: When ``journalctl`` is unavailable.

    Examples:
        >>> from unittest.mock import MagicMock, patch
        >>> proc = MagicMock()
        >>> proc.stdout = iter([])
        >>> proc.wait.return_value = 0
        >>> with patch("subprocess.Popen", return_value=proc):
        ...     _follow_journal(lines=0) is None
        True
    """
    cmd = [
        "journalctl",
        "--user",
        "-u",
        "sevn-gateway.service",
        "-f",
        "-n",
        str(lines),
        "--no-pager",
    ]
    try:
        proc = subprocess.Popen(  # nosec B603
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except OSError as exc:
        msg = f"cannot run journalctl: {exc}"
        raise CliPreconditionError(msg, exit_code=4) from exc
    stdout = proc.stdout
    if stdout is None:
        return
    try:
        for line in stdout:
            typer.echo(redact_log_line(line))
    except KeyboardInterrupt:
        proc.terminate()
    finally:
        proc.wait(timeout=2)


def _follow_macos_log(*, lines: int) -> None:
    """Stream launchd gateway logs via ``log stream`` when no log file exists.

    Args:
        lines (int): Ignored for stream; macOS has no trivial tail count.

    Returns:
        None

    Examples:
        >>> from unittest.mock import MagicMock, patch
        >>> proc = MagicMock()
        >>> proc.stdout = iter([])
        >>> proc.wait.return_value = 0
        >>> with patch("subprocess.Popen", return_value=proc):
        ...     _follow_macos_log(lines=0) is None
        True
    """
    _ = lines
    cmd = [
        "log",
        "stream",
        "--style",
        "compact",
        "--predicate",
        'process CONTAINS "uvicorn" OR process CONTAINS "sevn"',
    ]
    typer.echo("following system log stream (gateway unit; no gateway.log yet)", err=True)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)  # nosec B603
    except OSError as exc:
        msg = f"cannot run log stream: {exc}"
        raise CliPreconditionError(msg, exit_code=4) from exc
    stdout = proc.stdout
    if stdout is None:
        return
    try:
        for line in stdout:
            typer.echo(redact_log_line(line))
    except KeyboardInterrupt:
        proc.terminate()
    finally:
        proc.wait(timeout=2)


def run_service_logs(
    *,
    service: str,
    lines: int = 50,
    follow: bool = True,
    operator_home: Path | None = None,
) -> None:
    """Tail or follow service logs until interrupt or the service stops.

    Args:
        service (str): ``gateway`` or ``proxy``.
        lines (int): Lines of history before follow.
        follow (bool): When False, print tail only and return.
        operator_home (Path | None): Override ``SEVN_HOME``.

    Returns:
        None

    Raises:
        typer.Exit: On precondition failure or non-TTY follow without file.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from unittest.mock import patch
        >>> td = Path(tempfile.mkdtemp())
        >>> ws = td / "workspace"
        >>> ws.mkdir()
        >>> _ = (ws / "sevn.json").write_text(
        ...     '{"schema_version": 1, "workspace_root": ".", '
        ...     '"gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        ...     encoding="utf-8",
        ... )
        >>> (ws / "logs").mkdir(exist_ok=True)
        >>> _ = (ws / "logs" / "proxy.log").write_text("ok\\n", encoding="utf-8")
        >>> with patch("sevn.cli.log_follow._probe_proxy_running", return_value=False), patch(
        ...     "sevn.cli.log_follow.typer.echo"
        ... ):
        ...     run_service_logs(service="proxy", lines=1, follow=False, operator_home=td) is None
        True
    """
    try:
        log_path = resolve_service_log_path(service=service, operator_home=operator_home)
        home = (operator_home or sevn_home_dir()).expanduser().resolve()
        workspace_cfg, _layout = load_workspace(sevn_json=home / "workspace" / "sevn.json")
    except CliPreconditionError as exc:
        typer.secho(str(exc), err=True)
        raise typer.Exit(getattr(exc, "exit_code", 4)) from exc

    if log_path.is_file():
        run_unified_logs(
            source=service,  # type: ignore[arg-type]
            lines=lines,
            follow=follow,
            include_summary=False,
            operator_home=operator_home,
        )
        return

    unit_up = unit_is_active(home=Path.home(), service=service)  # type: ignore[arg-type]
    if not unit_up and _service_stopped(service=service, workspace_cfg=workspace_cfg):
        typer.secho(
            f"{service} is not running and no log file exists — start with `sevn {service} start`",
            err=True,
        )
        raise typer.Exit(4)

    if not follow:
        typer.echo("(no log file yet; nothing to tail)")
        return
    if not sys.stdout.isatty():
        typer.secho("follow requires a TTY; use without --no-follow", err=True)
        raise typer.Exit(2)

    plan = plan_install(Path.home())
    if plan.platform == "launchd":
        _follow_macos_log(lines=lines)
    else:
        _follow_journal(lines=lines)


def run_gateway_logs(
    *,
    lines: int = 50,
    follow: bool = True,
    operator_home: Path | None = None,
) -> None:
    """Tail or follow gateway logs until interrupt or the gateway stops.

    Args:
        lines (int): Lines of history before follow.
        follow (bool): When False, print tail only and return.
        operator_home (Path | None): Override ``SEVN_HOME``.

    Returns:
        None

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from unittest.mock import patch
        >>> td = Path(tempfile.mkdtemp())
        >>> ws = td / "workspace"
        >>> ws.mkdir()
        >>> _ = (ws / "sevn.json").write_text(
        ...     '{"schema_version": 1, "workspace_root": ".", '
        ...     '"gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        ...     encoding="utf-8",
        ... )
        >>> (ws / "logs").mkdir(exist_ok=True)
        >>> _ = (ws / "logs" / "gateway.log").write_text("ok\\n", encoding="utf-8")
        >>> with patch("sevn.cli.log_follow._service_stopped", return_value=False), patch(
        ...     "sevn.cli.log_follow.typer.echo"
        ... ):
        ...     run_gateway_logs(lines=1, follow=False, operator_home=td) is None
        True
    """
    run_service_logs(
        service="gateway",
        lines=lines,
        follow=follow,
        operator_home=operator_home,
    )


__all__ = [
    "SOURCE_TAGS",
    "LogEntry",
    "LogSource",
    "build_logs_insight_summary",
    "collect_merged_log_entries",
    "parse_log_level",
    "parse_log_timestamp",
    "render_logs_insight_summary",
    "resolve_agent_log_path",
    "resolve_gateway_log_path",
    "resolve_log_paths_for_sources",
    "resolve_service_log_path",
    "run_gateway_logs",
    "run_service_logs",
    "run_unified_logs",
]
