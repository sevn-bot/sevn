"""Gateway log read/filter tool (`plan/tools-skills-full-inventory-wave-plan.md` Wave 7).

Reads files under ``<workspace>/logs/`` (default ``gateway.log``), applies operator-safe
redaction, and returns lines with optional regex filter. Supports tail windows with
``offset_from_tail``, forward reads from ``starting_reading_line``, and explicit
``ranges``.

Module: sevn.tools.log_query
Depends: collections, re, sevn.cli.log_redact, sevn.tools.base, sevn.tools.context,
    sevn.tools.decorator

Exports:
    LogLineSpan — inclusive 1-based line interval for ranges mode.
    LogQueryResult — redacted lines plus read-mode metadata.
    log_query_tool — read/filter a log file under ``<workspace>/logs/`` with redaction.
    register_log_query_tool — register ``log_query`` on a ``ToolExecutor``.
    query_log_lines — testable read helper (tail, offset, from-line, ranges).
    tail_log_lines — backward-compatible tail-only alias.
    parse_log_ranges — parse ``ranges`` argument strings.
    coerce_log_range_args — normalize dict/negative-tail range shapes from models.
    summarize_log_result — compact tail summary for inline log reads.
    resolve_log_path — canonical log path under a workspace ``logs/`` directory.
    resolve_sevn_log_path — deprecated alias that resolves to the default log file.
    list_available_log_files — sorted list of ``*.log`` files under ``<workspace>/logs/``.

Examples:
    >>> from pathlib import Path
    >>> resolve_log_path(Path("/tmp/w"), "gateway.log").name
    'gateway.log'
    >>> "tail_default" in LOG_QUERY_ARGUMENT_FORMS
    True
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

from sevn.cli.log_redact import redact_log_line
from sevn.gateway.session.sessions_query import session_operator_timezone
from sevn.gateway.util.timestamps import resolve_time_range
from sevn.storage import open_sevn_sqlite
from sevn.tools.base import enveloped_failure, enveloped_success
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.decorator import sevn_tool, tool_from_decorated

if TYPE_CHECKING:
    from sevn.tools.base import ToolExecutor

DEFAULT_LOG_QUERY_LINES: Final[int] = 50
MAX_LOG_QUERY_LINES: Final[int] = 500
SUMMARY_INLINE_MAX_LINES: Final[int] = 25
# Inline byte budget so a ``log_query`` envelope never crosses the spill threshold
# (``TOOL_LARGE_RESULT_THRESHOLD_BYTES`` = 32 KB). A spilled log read previously returned a
# non-JSON descriptor that the model couldn't parse and then tried to crack open via
# ``run_code`` (which froze the gateway). Keeping log reads inline + bounded avoids that path
# entirely. Leaves headroom for the envelope wrapper and metadata.
LOG_QUERY_INLINE_MAX_BYTES: Final[int] = 24_000
# Per-line cap so a single pathological log line can't blow the inline budget on its own.
LOG_QUERY_MAX_LINE_CHARS: Final[int] = 2_000
DEFAULT_LOG_FILE: Final[str] = "gateway.log"
_LOG_DIR_NAME: Final[str] = "logs"
# Cap files scanned in date mode so a workspace with thousands of rotated logs
# never turns one query into an unbounded read; newest-by-mtime win.
_MAX_DATE_MODE_FILES: Final[int] = 120
_RANGE_SPEC_RE: Final[re.Pattern[str]] = re.compile(r"^\s*(\d+)\s*[-:]\s*(\d+)\s*$")

LogReadMode = Literal["tail", "from_line", "ranges"]

# Example ``log_query`` tool ``arguments`` objects (one positioning mode each).
LOG_QUERY_ARGUMENT_FORMS: Final[Mapping[str, dict[str, Any]]] = {
    "tail_default": {},
    "tail_lines": {"lines": 100},
    "tail_pattern": {"pattern": "msg=abc123", "lines": 200},
    "tail_offset_page2": {"offset_from_tail": 50, "lines": 50},
    "tail_offset_deep": {"offset_from_tail": 300, "lines": 50},
    "tail_offset_pattern": {
        "pattern": "ERROR|WARN",
        "offset_from_tail": 20,
        "lines": 30,
    },
    "from_line": {"starting_reading_line": 100, "lines": 50},
    "from_line_pattern": {
        "starting_reading_line": 1,
        "lines": 200,
        "pattern": "tool_call",
    },
    "ranges_single": {"ranges": ["10-50"], "lines": 500},
    "ranges_multi": {"ranges": ["100:120", "500-520"], "lines": 500},
    "ranges_pattern": {"ranges": ["1-1000"], "lines": 500, "pattern": "session_id="},
    "file_proxy": {"file": "proxy.log", "lines": 80},
    "file_rotated": {
        "file": "gateway-20260525T143417Z.log",
        "starting_reading_line": 1,
        "lines": 100,
    },
}


@dataclass(frozen=True)
class LogLineSpan:
    """One inclusive 1-based line interval in a log file."""

    start: int
    end: int


@dataclass(frozen=True)
class LogQueryResult:
    """Redacted lines plus read-mode metadata for tool envelopes."""

    lines: list[str]
    line_numbers: list[int]
    mode: LogReadMode
    total_file_lines: int


def _normalize_log_filename(file: str) -> str:
    """Normalize model-friendly log paths to a bare filename under ``logs/``.

    Accepts ``logs/gateway.log``, ``./logs/proxy.log``, and leading ``./`` before
    ``resolve_log_path`` validation. Traversal attempts (``..``, extra separators)
    are left intact so :func:`resolve_log_path` can reject them.

    Args:
        file (str): Raw ``file`` argument from a tool call.

    Returns:
        str: Bare filename or unchanged value when traversal markers remain.

    Examples:
        >>> _normalize_log_filename("  logs/gateway.log  ")
        'gateway.log'
        >>> _normalize_log_filename("./logs/proxy.log")
        'proxy.log'
        >>> _normalize_log_filename("../gateway.log")
        '../gateway.log'
    """
    name = (file or "").strip()
    if name.startswith("./logs/"):
        name = name[len("./logs/") :]
    elif name.startswith("logs/"):
        name = name[len("logs/") :]
    if name.startswith("./"):
        name = name[2:]
    if "/" not in name and "\\" not in name and ".." not in name:
        name = Path(name).name
    return name


def resolve_log_path(workspace_path: Path, file_name: str = DEFAULT_LOG_FILE) -> Path:
    """Return ``<workspace>/logs/<file_name>`` after rejecting traversal attempts.

    Args:
        workspace_path (Path): Workspace content root.
        file_name (str): Filename inside ``<workspace>/logs/``. Must not contain a path
            separator or ``..``; default ``gateway.log``.

    Returns:
        Path: Absolute or relative log file path.

    Raises:
        ValueError: When ``file_name`` is empty, contains ``/``, ``\\``, or ``..``, or
            resolves outside ``<workspace>/logs/``.

    Examples:
        >>> from pathlib import Path
        >>> resolve_log_path(Path("/tmp/w")) == Path("/tmp/w/logs/gateway.log")
        True
        >>> resolve_log_path(Path("/tmp/w"), "proxy.log").name
        'proxy.log'
    """
    name = (file_name or "").strip()
    if not name:
        msg = "log_query: 'file' must be a non-empty filename under logs/"
        raise ValueError(msg)
    if "/" in name or "\\" in name or ".." in name:
        msg = f"log_query: 'file' must be a bare filename without separators or '..' (got {file_name!r})"
        raise ValueError(msg)
    logs_dir = workspace_path / _LOG_DIR_NAME
    candidate = logs_dir / name
    try:
        candidate.relative_to(logs_dir)
    except ValueError as exc:  # pragma: no cover - guarded by name check
        msg = f"log_query: resolved path escapes logs/ (got {candidate})"
        raise ValueError(msg) from exc
    return candidate


def resolve_sevn_log_path(workspace_path: Path) -> Path:
    """Deprecated. Return ``<workspace>/logs/gateway.log`` for backwards compatibility.

    Args:
        workspace_path (Path): Workspace content root.

    Returns:
        Path: Path to the default workspace log file (``gateway.log``).

    Examples:
        >>> from pathlib import Path
        >>> resolve_sevn_log_path(Path("/tmp/w")) == Path("/tmp/w/logs/gateway.log")
        True
    """
    return resolve_log_path(workspace_path, DEFAULT_LOG_FILE)


def list_available_log_files(workspace_path: Path) -> list[str]:
    """Return sorted list of ``*.log`` filenames under ``<workspace>/logs/``.

    Args:
        workspace_path (Path): Workspace content root.

    Returns:
        list[str]: Sorted log filenames (bare names, not paths). Empty when the
        ``logs/`` directory does not exist.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> (td / "logs").mkdir()
        >>> _ = (td / "logs" / "gateway.log").write_text("x")
        >>> list_available_log_files(td)
        ['gateway.log']
    """
    logs_dir = workspace_path / _LOG_DIR_NAME
    if not logs_dir.is_dir():
        return []
    return sorted(p.name for p in logs_dir.iterdir() if p.is_file() and p.suffix == ".log")


def _clamp_line_limit(lines: int) -> int:
    """Clamp a requested line count to ``[1, MAX_LOG_QUERY_LINES]``.

    Args:
        lines (int): Requested maximum lines.

    Returns:
        int: Clamped line count.

    Examples:
        >>> _clamp_line_limit(0)
        1
        >>> _clamp_line_limit(999)
        500
    """
    return max(1, min(int(lines), MAX_LOG_QUERY_LINES))


_BOOL_TRUE_STRINGS: Final[frozenset[str]] = frozenset({"true", "1", "yes", "on"})
_BOOL_FALSE_STRINGS: Final[frozenset[str]] = frozenset({"false", "0", "no", "off", ""})


def _coerce_int_arg(value: Any, *, field: str) -> tuple[int | None, str | None]:
    """Coerce a model-supplied integer arg that may arrive as a numeric string.

    Under CodeMode (``run_code``), MiniMax-class models routinely pass typed kwargs as
    strings — ``log_query(offset_from_tail='300')`` — which would otherwise raise inside
    arithmetic and get silently dropped by the sandbox. Accept clean numeric strings and
    integral floats; return a readable error for anything else so the model gets an
    ``ok=false`` envelope it can act on rather than a vanished call.

    Args:
        value (Any): Raw argument value (``int``, numeric ``str``, integral ``float``, or ``None``).
        field (str): Parameter name, used in the error message.

    Returns:
        tuple[int | None, str | None]: ``(coerced, None)`` on success, ``(None, error)`` on failure.
            ``(None, None)`` when ``value`` is ``None`` (caller applies its default).

    Examples:
        >>> _coerce_int_arg("300", field="offset_from_tail")
        (300, None)
        >>> _coerce_int_arg(50, field="lines")
        (50, None)
        >>> _coerce_int_arg(None, field="lines")
        (None, None)
        >>> _coerce_int_arg("abc", field="lines")[0] is None
        True
    """
    if value is None:
        return None, None
    if isinstance(value, bool):
        # bool is an int subclass; reject so summarize-style typos don't become 0/1.
        return None, f"log_query: '{field}' must be an integer, got boolean {value!r}"
    if isinstance(value, int):
        return value, None
    if isinstance(value, float):
        if value.is_integer():
            return int(value), None
        return None, f"log_query: '{field}' must be a whole number (got {value!r})"
    text = str(value).strip()
    if text.lstrip("+-").isdigit():
        return int(text), None
    return None, f"log_query: '{field}' must be an integer (got {value!r})"


def _coerce_bool_arg(value: Any, *, field: str) -> tuple[bool | None, str | None]:
    """Coerce a model-supplied boolean arg that may arrive as a string like ``'true'``.

    A bare truthiness check is wrong here: under CodeMode the model sends ``summarize='false'``
    as a non-empty (truthy) string, which would silently flip the flag on. Map the usual
    string spellings explicitly and reject the rest.

    Args:
        value (Any): Raw argument value (``bool``, ``'true'``/``'false'`` string, ``int``, or ``None``).
        field (str): Parameter name, used in the error message.

    Returns:
        tuple[bool | None, str | None]: ``(coerced, None)`` on success, ``(None, error)`` on failure.

    Examples:
        >>> _coerce_bool_arg("true", field="summarize")
        (True, None)
        >>> _coerce_bool_arg("false", field="summarize")
        (False, None)
        >>> _coerce_bool_arg(None, field="summarize")
        (False, None)
        >>> _coerce_bool_arg("maybe", field="summarize")[0] is None
        True
    """
    if isinstance(value, bool):
        return value, None
    if value is None:
        return False, None
    if isinstance(value, (int, float)):
        return bool(value), None
    text = str(value).strip().lower()
    if text in _BOOL_TRUE_STRINGS:
        return True, None
    if text in _BOOL_FALSE_STRINGS:
        return False, None
    return None, f"log_query: '{field}' must be a boolean true/false (got {value!r})"


# Appended to arg-shape validation errors so a model relays the fix silently and
# corrects its call, rather than quoting the raw diagnostic into the user's reply
# (observed 2026-07-13: "log_query failed: invalid range '[2578, 2632]'…" leaked to chat).
_RANGE_ERR_INTERNAL_HINT = (
    " (internal diagnostic — correct the call and retry; do not quote this to the user)"
)


def parse_log_ranges(ranges: Sequence[str]) -> tuple[list[LogLineSpan], str | None]:
    """Parse ``ranges`` entries like ``10-50`` or ``10:50`` (1-based inclusive).

    Args:
        ranges (Sequence[str]): One or more range specifiers.

    Returns:
        tuple[list[LogLineSpan], str | None]: Parsed spans, or ``([], error)`` on failure.

    Examples:
        >>> spans, err = parse_log_ranges(["10-50", "100:120"])
        >>> err is None and len(spans) == 2
        True
        >>> spans[0].start, spans[0].end
        (10, 50)
    """
    if not ranges:
        return [], "log_query: 'ranges' must be a non-empty list of strings like '10-50'"
    parsed: list[LogLineSpan] = []
    for spec in ranges:
        text = str(spec).strip()
        if not text:
            return [], "log_query: 'ranges' entries must be non-empty strings like '10-50'"
        match = _RANGE_SPEC_RE.match(text)
        if match is None:
            return [], (
                f"log_query: invalid range {spec!r}; use inclusive 1-based form 'start-end' "
                "or 'start:end' (e.g. '10-50')" + _RANGE_ERR_INTERNAL_HINT
            )
        start = int(match.group(1))
        end = int(match.group(2))
        if start < 1:
            return [], f"log_query: range start must be >= 1 (got {start} in {spec!r})"
        if end < start:
            return [], f"log_query: range end must be >= start (got {spec!r})"
        parsed.append(LogLineSpan(start=start, end=end))
    return parsed, None


def _both_plain_ints(items: Sequence[Any]) -> bool:
    """Return True when every entry is a bare non-negative integer (int or digit string).

    Used to detect a ``[start, end]`` pair passed as two bare integers. Booleans,
    dicts, signed/tail markers, and already-hyphenated range strings are excluded so
    tail-mode and canonical ``'start-end'`` inputs are never reinterpreted.

    Args:
        items (Sequence[Any]): Candidate range entries.

    Returns:
        bool: ``True`` when every entry is a bare non-negative integer.

    Examples:
        >>> _both_plain_ints([2578, 2632])
        True
        >>> _both_plain_ints(["10", "50"])
        True
        >>> _both_plain_ints(["10-50", "60"])
        False
        >>> _both_plain_ints([-100, 200])
        False
    """
    for item in items:
        if isinstance(item, bool):
            return False
        if isinstance(item, int):
            if item < 0:
                return False
            continue
        if isinstance(item, str) and item.strip().isdigit():
            continue
        return False
    return True


def coerce_log_range_args(
    ranges: Sequence[Any] | None,
) -> tuple[list[str] | None, int | None, int | None, str | None]:
    """Normalize model-friendly ``ranges`` shapes before positional mode selection.

    Accepts canonical ``'start-end'`` strings plus dict forms such as
    ``{'start': '-100', 'limit': '200'}`` (negative ``start`` → tail mode). Also tolerates a
    bare string (``'10-50'``) or a single comma/space-separated string (``'10-50, 100-120'``)
    instead of a list, since models frequently pass ``ranges`` that way.

    Args:
        ranges (Sequence[Any] | None): Raw ``ranges`` argument from the tool call.

    Returns:
        tuple[list[str] | None, int | None, int | None, str | None]: Canonical string
        ranges (possibly empty), optional tail ``lines`` override, optional tail
        ``offset_from_tail`` override, or a validation error message.

    Examples:
        >>> coerce_log_range_args([{"start": "-100", "limit": "200"}])
        (None, 200, 0, None)
        >>> coerce_log_range_args("10-50")
        (['10-50'], None, None, None)
        >>> coerce_log_range_args("10-50, 100-120")
        (['10-50', '100-120'], None, None, None)
    """
    if ranges is None:
        return None, None, None, None
    if isinstance(ranges, str):
        # Model passed a bare string instead of a list; split on commas/whitespace so a
        # single ``'10-50'`` or ``'10-50, 100-120'`` is accepted rather than iterated as chars.
        # Also tolerate a JSON-array-looking string such as ``'[2578, 2632]'`` by stripping the
        # surrounding brackets first (a frequent model mistake surfaced in live-session logs).
        ranges = [seg for seg in re.split(r"[,\s]+", ranges.strip().strip("[](){}")) if seg]
    if isinstance(ranges, (list, tuple)) and len(ranges) == 2 and _both_plain_ints(ranges):
        # Model passed ``[start, end]`` as two bare integers meaning one inclusive range
        # (e.g. ``[2578, 2632]`` → ``'2578-2632'``). Without this each number parses as an
        # invalid standalone range. Only when neither is a dict/separator string.
        ranges = [f"{int(str(ranges[0]).strip())}-{int(str(ranges[1]).strip())}"]
    if len(ranges) == 0:
        return (
            [],
            None,
            None,
            "log_query: 'ranges' must be a non-empty list of strings like '10-50'",
        )
    string_ranges: list[str] = []
    tail_lines: int | None = None
    tail_offset: int | None = None
    for item in ranges:
        if isinstance(item, dict):
            start_raw = item.get("start")
            limit_raw = item.get("limit", item.get("lines"))
            end_raw = item.get("end", item.get("stop"))
            if start_raw is not None and str(start_raw).strip().startswith("-"):
                try:
                    tail_lines = _clamp_line_limit(
                        int(limit_raw) if limit_raw is not None else DEFAULT_LOG_QUERY_LINES,
                    )
                except (TypeError, ValueError):
                    return (
                        None,
                        None,
                        None,
                        (
                            f"log_query: invalid negative-tail range dict {item!r}; "
                            "use tail mode with {'lines': N} or string ranges like '10-50'"
                        ),
                    )
                # Models use negative ``start`` to mean "tail read"; ``limit`` is the window.
                tail_offset = 0
                continue
            if start_raw is not None and end_raw is not None:
                try:
                    string_ranges.append(f"{int(start_raw)}-{int(end_raw)}")
                except (TypeError, ValueError):
                    return (
                        None,
                        None,
                        None,
                        (
                            f"log_query: invalid range dict {item!r}; use 'start-end' strings "
                            "or {'start': '-N', 'limit': M} for tail reads"
                        ),
                    )
                continue
            return (
                None,
                None,
                None,
                (
                    f"log_query: invalid range dict {item!r}; use inclusive 'start-end' strings "
                    "or {'start': '-N', 'limit': M} for tail reads"
                ),
            )
        string_ranges.append(str(item))
    return (string_ranges or None), tail_lines, tail_offset, None


def _count_log_levels(lines: Sequence[str]) -> dict[str, int]:
    """Count coarse log level tokens in raw lines.

    Args:
        lines (Sequence[str]): Redacted or raw log lines.

    Returns:
        dict[str, int]: Counts for ERROR/WARN/INFO buckets.

    Examples:
        >>> _count_log_levels(["ERROR boom", "INFO ok", "WARN slow"])
        {'ERROR': 1, 'WARN': 1, 'INFO': 1}
    """
    counts = {"ERROR": 0, "WARN": 0, "INFO": 0}
    for line in lines:
        upper = line.upper()
        if " ERROR " in upper or upper.startswith("ERROR"):
            counts["ERROR"] += 1
        elif " WARN " in upper or upper.startswith("WARN"):
            counts["WARN"] += 1
        elif " INFO " in upper or upper.startswith("INFO"):
            counts["INFO"] += 1
    return counts


def _truncate_line(line: str) -> str:
    """Cap a single log line so one pathological line can't blow the inline budget.

    Args:
        line (str): Redacted log line.

    Returns:
        str: The line, truncated with an ellipsis marker when over the per-line cap.

    Examples:
        >>> _truncate_line("short")
        'short'
        >>> _truncate_line("x" * 5000).endswith("…[truncated]")
        True
    """
    if len(line) <= LOG_QUERY_MAX_LINE_CHARS:
        return line
    return line[:LOG_QUERY_MAX_LINE_CHARS] + "…[truncated]"


def _fit_inline_lines(
    lines: Sequence[str],
    numbers: Sequence[int],
    *,
    max_lines: int = SUMMARY_INLINE_MAX_LINES,
    max_bytes: int = LOG_QUERY_INLINE_MAX_BYTES,
) -> tuple[list[str], list[int]]:
    """Return the most recent lines that fit under the line/byte budget.

    Keeps the tail (most recent) lines, truncates each to the per-line cap, and drops from the
    front until the UTF-8 size fits ``max_bytes`` so the envelope never spills.

    Args:
        lines (Sequence[str]): Candidate log lines (chronological).
        numbers (Sequence[int]): 1-based line numbers aligned with *lines*.
        max_lines (int): Hard cap on inline line count.
        max_bytes (int): Byte budget for the joined inline lines.

    Returns:
        tuple[list[str], list[int]]: Bounded lines and their line numbers.

    Examples:
        >>> ls, ns = _fit_inline_lines(["a", "b", "c"], [1, 2, 3], max_lines=2)
        >>> ls
        ['b', 'c']
        >>> _fit_inline_lines(["x" * 30000], [1])[0][0].endswith("…[truncated]")
        True
    """
    kept = [_truncate_line(line) for line in lines[-max_lines:]]
    kept_numbers = list(numbers[-max_lines:])
    while kept and len("\n".join(kept).encode("utf-8")) > max_bytes:
        kept.pop(0)
        kept_numbers.pop(0)
    return kept, kept_numbers


def summarize_log_result(
    result: LogQueryResult,
    *,
    requested_lines: int,
) -> dict[str, Any]:
    """Build a compact tail summary that stays inline under spill thresholds.

    Args:
        result (LogQueryResult): Full redacted read result.
        requested_lines (int): Original ``lines`` argument from the tool call.

    Returns:
        dict[str, Any]: Summary envelope fields for ``enveloped_success``.

    Examples:
        >>> sample = LogQueryResult(
        ...     lines=[f"INFO line{i}" for i in range(1, 6)],
        ...     line_numbers=[1, 2, 3, 4, 5],
        ...     mode="tail",
        ...     total_file_lines=100,
        ... )
        >>> payload = summarize_log_result(sample, requested_lines=200)
        >>> payload["mode"]
        'tail_summary'
        >>> payload["returned_lines"] <= SUMMARY_INLINE_MAX_LINES
        True
    """
    inline_lines, inline_numbers = _fit_inline_lines(result.lines, result.line_numbers)
    sampled = len(result.lines)
    return {
        "path": None,
        "file": None,
        "mode": "tail_summary",
        "total_file_lines": result.total_file_lines,
        "requested_lines": requested_lines,
        "sampled_lines": sampled,
        "returned_lines": len(inline_lines),
        "level_counts": _count_log_levels(result.lines),
        "lines": inline_lines,
        "line_numbers": inline_numbers,
        "count": len(inline_lines),
        "summary_notice": (
            f"Tail summary: read {sampled} line(s) from the log; showing the last "
            f"{len(inline_lines)} inline to avoid a large spill. "
            "Use `read` on a spill path or narrow with `pattern` / smaller `lines` for detail."
        ),
    }


def _line_matches(pattern: re.Pattern[str] | None, line: str) -> bool:
    """Return whether ``line`` passes the optional regex filter.

    Args:
        pattern (re.Pattern[str] | None): Compiled filter, or ``None`` for all lines.
        line (str): Raw log line (without trailing newline).

    Returns:
        bool: ``True`` when the line should be included.

    Examples:
        >>> _line_matches(re.compile("WARN"), "WARN slow")
        True
        >>> _line_matches(re.compile("WARN"), "INFO ok")
        False
    """
    return pattern is None or pattern.search(line) is not None


def _read_file_lines(log_path: Path) -> tuple[list[str], int]:
    """Load all lines from ``log_path`` (stripped, no trailing newline).

    Args:
        log_path (Path): Log file path.

    Returns:
        tuple[list[str], int]: Lines and count.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> log = td / "gateway.log"
        >>> _ = log.write_text("a\\nb\\n", encoding="utf-8")
        >>> lines, count = _read_file_lines(log)
        >>> count == 2 and lines == ["a", "b"]
        True
    """
    with log_path.open(encoding="utf-8", errors="replace") as handle:
        physical = [raw.rstrip("\n") for raw in handle]
    return physical, len(physical)


def query_log_lines(
    log_path: Path,
    *,
    lines: int,
    pattern: re.Pattern[str] | None = None,
    offset_from_tail: int = 0,
    starting_reading_line: int | None = None,
    ranges: Sequence[str] | None = None,
) -> tuple[LogQueryResult | None, bool, str | None]:
    """Read redacted log lines using tail, forward, or explicit range modes.

    Exactly one positioning mode applies per call:

    - **tail** (default): last ``lines`` physical lines, or last ``lines`` regex
      matches when ``pattern`` is set. ``offset_from_tail`` skips that many lines
      (or matches) from the newest end before returning the window — e.g.
      ``offset_from_tail=300`` with ``lines=50`` returns the 50 lines *older* than
      the newest 300.
    - **from_line**: ``starting_reading_line`` (1-based) through
      ``starting_reading_line + lines - 1``, optionally filtered by ``pattern``.
    - **ranges**: inclusive 1-based intervals from ``ranges`` (e.g. ``["10-50"]``),
      optionally filtered by ``pattern``. Total returned lines capped at
      ``MAX_LOG_QUERY_LINES``.

    Args:
        log_path (Path): Log file to read.
        lines (int): Window size (tail/from_line) or per-call cap (ranges aggregate).
        pattern (re.Pattern[str] | None): Optional line filter (matches raw text).
        offset_from_tail (int): Lines/matches to skip from the newest end (tail mode).
        starting_reading_line (int | None): 1-based start line (from_line mode).
        ranges (Sequence[str] | None): Range specs (ranges mode).

    Returns:
        tuple[LogQueryResult | None, bool, str | None]: Result, file-existed flag, and
        validation error message when positioning args conflict or ranges are invalid.

    Examples:
        Tail (default) — last ``lines`` physical lines::

            LOG_QUERY_ARGUMENT_FORMS["tail_default"]  # {}

        Tail + offset — skip newest N, then take ``lines`` (pagination)::

            LOG_QUERY_ARGUMENT_FORMS["tail_offset_deep"]
            # {"offset_from_tail": 300, "lines": 50}

        From-line — forward from 1-based ``starting_reading_line``::

            LOG_QUERY_ARGUMENT_FORMS["from_line"]
            # {"starting_reading_line": 100, "lines": 50}

        Ranges — explicit inclusive intervals::

            LOG_QUERY_ARGUMENT_FORMS["ranges_multi"]
            # {"ranges": ["100:120", "500-520"], "lines": 500}

        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> log = td / "gateway.log"
        >>> body = "\\n".join(f"line{i}" for i in range(1, 11)) + "\\n"
        >>> _ = log.write_text(body, encoding="utf-8")
        >>> tail, ok, err = query_log_lines(log, lines=2)
        >>> err is None
        True
        >>> ok
        True
        >>> tail is not None
        True
        >>> tail.mode
        'tail'
        >>> tail.line_numbers
        [9, 10]
        >>> off, ok2, err2 = query_log_lines(log, lines=2, offset_from_tail=2)
        >>> err2 is None
        True
        >>> off is not None
        True
        >>> off.line_numbers
        [7, 8]
        >>> fwd, ok3, err3 = query_log_lines(log, lines=2, starting_reading_line=3)
        >>> fwd is not None
        True
        >>> fwd.mode
        'from_line'
        >>> fwd.line_numbers
        [3, 4]
        >>> rng, ok4, err4 = query_log_lines(log, lines=500, ranges=["2-3", "9:10"])
        >>> rng is not None
        True
        >>> rng.mode
        'ranges'
        >>> rng.line_numbers
        [2, 3, 9, 10]
    """
    if not log_path.is_file():
        return None, False, None

    limit = _clamp_line_limit(lines)
    offset = max(0, int(offset_from_tail))
    has_ranges = ranges is not None and len(ranges) > 0
    has_start = starting_reading_line is not None
    has_offset = offset > 0

    mode_count = int(has_ranges) + int(has_start) + int(has_offset)
    if mode_count > 1:
        return (
            None,
            True,
            "log_query: use only one of 'ranges', 'starting_reading_line', or "
            "'offset_from_tail' > 0 per call",
        )

    physical, total = _read_file_lines(log_path)

    if has_ranges:
        assert ranges is not None  # nosec B101 — narrowed by has_ranges guard above
        spans, parse_err = parse_log_ranges(ranges)
        if parse_err is not None:
            return None, True, parse_err
        return _query_ranges(physical, total, spans, limit=limit, pattern=pattern), True, None

    if has_start:
        start = int(starting_reading_line)  # type: ignore[arg-type]
        if start < 1:
            return None, True, "log_query: 'starting_reading_line' must be >= 1"
        return (
            _query_from_line(physical, total, start_line=start, limit=limit, pattern=pattern),
            True,
            None,
        )

    return (
        _query_tail(physical, total, limit=limit, pattern=pattern, offset_from_tail=offset),
        True,
        None,
    )


def _query_tail(
    physical: list[str],
    total: int,
    *,
    limit: int,
    pattern: re.Pattern[str] | None,
    offset_from_tail: int,
) -> LogQueryResult:
    """Return a tail window (optionally filtered, with offset from newest).

    Args:
        physical (list[str]): All file lines.
        total (int): Line count.
        limit (int): Maximum lines to return.
        pattern (re.Pattern[str] | None): Optional filter.
        offset_from_tail (int): Newest lines/matches to skip.

    Returns:
        LogQueryResult: Redacted slice.

    Examples:
        >>> physical = [f"L{i}" for i in range(1, 6)]
        >>> res = _query_tail(physical, 5, limit=2, pattern=None, offset_from_tail=1)
        >>> res.line_numbers
        [3, 4]
    """
    if pattern is None:
        end_idx = total - offset_from_tail if offset_from_tail > 0 else total
        start_idx = max(0, end_idx - limit)
        selected = list(enumerate(physical[start_idx:end_idx], start=start_idx + 1))
    else:
        matches: list[tuple[int, str]] = []
        for line_no, line in enumerate(physical, start=1):
            if _line_matches(pattern, line):
                matches.append((line_no, line))
        end_idx = len(matches) - offset_from_tail if offset_from_tail > 0 else len(matches)
        start_idx = max(0, end_idx - limit)
        selected = matches[start_idx:end_idx]

    line_numbers = [no for no, _ in selected]
    redacted = [redact_log_line(line) for _, line in selected]
    return LogQueryResult(
        lines=redacted,
        line_numbers=line_numbers,
        mode="tail",
        total_file_lines=total,
    )


def _query_from_line(
    physical: list[str],
    total: int,
    *,
    start_line: int,
    limit: int,
    pattern: re.Pattern[str] | None,
) -> LogQueryResult:
    """Return up to ``limit`` lines from ``start_line`` forward (1-based).

    Args:
        physical (list[str]): All file lines.
        total (int): Line count.
        start_line (int): First line to consider.
        limit (int): Maximum lines to return.
        pattern (re.Pattern[str] | None): Optional filter.

    Returns:
        LogQueryResult: Redacted slice.

    Examples:
        >>> physical = ["a", "b", "c", "d"]
        >>> res = _query_from_line(physical, 4, start_line=2, limit=2, pattern=None)
        >>> res.line_numbers
        [2, 3]
    """
    selected: list[tuple[int, str]] = []
    if pattern is None:
        end_line = start_line + limit - 1
        for line_no, line in enumerate(physical, start=1):
            if line_no < start_line:
                continue
            if line_no > end_line:
                break
            selected.append((line_no, line))
    else:
        # Match-set paging: collect matches from start_line forward, then take
        # up to ``limit`` matches (not a file-line window of size ``limit``).
        for line_no, line in enumerate(physical, start=1):
            if line_no < start_line:
                continue
            if _line_matches(pattern, line):
                selected.append((line_no, line))
                if len(selected) >= limit:
                    break
    line_numbers = [no for no, _ in selected]
    redacted = [redact_log_line(line) for _, line in selected]
    return LogQueryResult(
        lines=redacted,
        line_numbers=line_numbers,
        mode="from_line",
        total_file_lines=total,
    )


def _query_ranges(
    physical: list[str],
    total: int,
    spans: list[LogLineSpan],
    *,
    limit: int,
    pattern: re.Pattern[str] | None,
) -> LogQueryResult:
    """Return lines from explicit inclusive 1-based intervals.

    Args:
        physical (list[str]): All file lines.
        total (int): Line count.
        spans (list[LogLineSpan]): Intervals to read.
        limit (int): Maximum total lines returned across all spans.
        pattern (re.Pattern[str] | None): Optional filter.

    Returns:
        LogQueryResult: Redacted slice (truncated to ``limit`` when needed).

    Examples:
        >>> physical = [f"L{i}" for i in range(1, 11)]
        >>> spans = [LogLineSpan(2, 3), LogLineSpan(9, 10)]
        >>> res = _query_ranges(physical, 10, spans, limit=500, pattern=None)
        >>> res.line_numbers
        [2, 3, 9, 10]
    """
    selected: list[tuple[int, str]] = []
    for span in spans:
        for line_no, line in enumerate(physical, start=1):
            if line_no < span.start:
                continue
            if line_no > span.end:
                break
            if _line_matches(pattern, line):
                selected.append((line_no, line))
            if len(selected) >= limit:
                break
        if len(selected) >= limit:
            break

    trimmed = selected[:limit]
    line_numbers = [no for no, _ in trimmed]
    redacted = [redact_log_line(line) for _, line in trimmed]
    return LogQueryResult(
        lines=redacted,
        line_numbers=line_numbers,
        mode="ranges",
        total_file_lines=total,
    )


def tail_log_lines(
    log_path: Path,
    *,
    lines: int,
    pattern: re.Pattern[str] | None = None,
) -> tuple[list[str], bool]:
    """Tail ``log_path`` and optionally filter by regex (backward-compatible alias).

    Args:
        log_path (Path): Log file to read.
        lines (int): Maximum lines to return from the tail or match set.
        pattern (re.Pattern[str] | None): Optional line filter.

    Returns:
        tuple[list[str], bool]: Redacted lines and whether the file existed.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> log = td / "gateway.log"
        >>> _ = log.write_text("ok line\\ntoken=secret123\\n", encoding="utf-8")
        >>> out, existed = tail_log_lines(log, lines=10, pattern=None)
        >>> existed and "secret123" not in "\\n".join(out)
        True
    """
    result, existed, err = query_log_lines(log_path, lines=lines, pattern=pattern)
    if not existed or err is not None or result is None:
        return [], existed
    return result.lines, True


def _parse_log_line_utc(line: str) -> datetime | None:
    """Parse the leading ISO timestamp of a log line into aware UTC.

    Log lines start with ``YYYY-MM-DD HH:MM:SS.ffffff+HH:MM | LEVEL | …``; the
    timestamp is taken as the text before the first ``" | "``. Lines without a
    parseable leading timestamp (continuations, banners) return ``None``.

    Args:
        line (str): Raw log line.

    Returns:
        datetime | None: UTC-normalised timestamp, or ``None``.

    Examples:
        >>> _parse_log_line_utc("2026-07-03 08:00:00+02:00 | INFO | x").isoformat()
        '2026-07-03T06:00:00+00:00'
        >>> _parse_log_line_utc("  ...traceback...") is None
        True
    """
    head = line.split(" | ", 1)[0].strip()
    if not head:
        return None
    try:
        ts = datetime.fromisoformat(head)
    except ValueError:
        return None
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)


def _log_family_stem(file_name: str) -> str:
    """Return the rotation family stem for a base log filename.

    ``gateway.log`` and ``gateway-20260702T222759Z.log`` share stem ``gateway``.

    Args:
        file_name (str): Base or rotated log filename.

    Returns:
        str: Family stem (text before the first ``.`` or ``-``).

    Examples:
        >>> _log_family_stem("gateway.log")
        'gateway'
        >>> _log_family_stem("proxy-20260101T000000Z.log")
        'proxy'
    """
    return file_name.split(".", 1)[0].split("-", 1)[0]


def _candidate_log_files_for_range(
    workspace_path: Path, base_file: str, start_utc: datetime | None
) -> list[Path]:
    """Return rotation-family log paths that may hold lines at/after ``start_utc``.

    Files whose last-modified time precedes ``start_utc`` stopped being written
    before the window and are skipped; the rest are returned oldest-first (by
    mtime) so a merged read stays chronological. Out-of-window tail lines are
    dropped later by the per-line time filter.

    Args:
        workspace_path (Path): Workspace content root.
        base_file (str): Requested log filename (default family anchor).
        start_utc (datetime | None): Lower bound; ``None`` keeps every family file.

    Returns:
        list[Path]: Candidate log paths, oldest-first, capped for safety.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> _ = (td / "logs").mkdir()
        >>> _ = (td / "logs" / "gateway.log").write_text("x", encoding="utf-8")
        >>> [p.name for p in _candidate_log_files_for_range(td, "gateway.log", None)]
        ['gateway.log']
    """
    logs_dir = workspace_path / _LOG_DIR_NAME
    if not logs_dir.is_dir():
        return []
    stem = _log_family_stem(base_file)
    start_epoch = start_utc.timestamp() if start_utc is not None else None
    candidates: list[tuple[float, Path]] = []
    for path in logs_dir.iterdir():
        if not path.is_file() or path.suffix != ".log" or not path.name.startswith(stem):
            continue
        mtime = path.stat().st_mtime
        if start_epoch is not None and mtime < start_epoch:
            continue
        candidates.append((mtime, path))
    candidates.sort(key=lambda item: item[0])
    return [path for _, path in candidates[-_MAX_DATE_MODE_FILES:]]


def _query_logs_by_time(
    workspace_path: Path,
    base_file: str,
    *,
    start_iso: str | None,
    end_iso: str | None,
    pattern: re.Pattern[str] | None,
    lines: int,
    offset_from_tail: int,
) -> tuple[list[str], list[str]]:
    """Merge-read the rotation family and keep redacted in-window lines (tail).

    Args:
        workspace_path (Path): Workspace content root.
        base_file (str): Requested log filename (anchors the rotation family).
        start_iso (str | None): Inclusive lower bound (naive-UTC ISO).
        end_iso (str | None): Exclusive upper bound (naive-UTC ISO).
        pattern (re.Pattern[str] | None): Optional regex filter.
        lines (int): Tail window size after filtering.
        offset_from_tail (int): Skip this many newest matches before the window.

    Returns:
        tuple[list[str], list[str]]: ``(redacted_lines, files_read)`` where
        ``files_read`` are the bare filenames that contributed.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> _ = (td / "logs").mkdir()
        >>> _ = (td / "logs" / "gateway.log").write_text(
        ...     "2026-07-02 12:00:00+00:00 | INFO | x | y | hi\\n", encoding="utf-8"
        ... )
        >>> lines, files = _query_logs_by_time(
        ...     td, "gateway.log", start_iso="2026-07-02T00:00:00",
        ...     end_iso="2026-07-03T00:00:00", pattern=None, lines=10, offset_from_tail=0
        ... )
        >>> files
        ['gateway.log']
    """
    start_dt = datetime.fromisoformat(start_iso).replace(tzinfo=UTC) if start_iso else None
    end_dt = datetime.fromisoformat(end_iso).replace(tzinfo=UTC) if end_iso else None
    matched: list[str] = []
    files_read: list[str] = []
    for path in _candidate_log_files_for_range(workspace_path, base_file, start_dt):
        file_lines, _ = _read_file_lines(path)
        kept = False
        for raw in file_lines:
            ts = _parse_log_line_utc(raw)
            if ts is None:
                continue
            if start_dt is not None and ts < start_dt:
                continue
            if end_dt is not None and ts >= end_dt:
                continue
            if not _line_matches(pattern, raw):
                continue
            matched.append(redact_log_line(raw))
            kept = True
        if kept:
            files_read.append(path.name)
    if offset_from_tail > 0:
        matched = (
            matched[: len(matched) - offset_from_tail] if offset_from_tail < len(matched) else []
        )
    return matched[-lines:], files_read


def _run_log_date_mode(
    ctx: ToolContext,
    *,
    file: str,
    when: str | None,
    since: str | None,
    until: str | None,
    compiled: re.Pattern[str] | None,
    pattern: str | None,
    lines: int,
    offset_from_tail: int,
) -> str:
    """Read the rotation family and return redacted lines within a date window.

    Args:
        ctx (ToolContext): Invocation context.
        file (str): Requested log filename (rotation-family anchor).
        when (str | None): Relative range token.
        since (str | None): Explicit lower bound.
        until (str | None): Explicit upper bound.
        compiled (re.Pattern[str] | None): Compiled ``pattern`` filter.
        pattern (str | None): Raw pattern (echoed in the envelope).
        lines (int): Tail window size after filtering.
        offset_from_tail (int): Skip newest matches before the window.

    Returns:
        str: §3.1 JSON envelope with ``lines``, ``files``, ``since``/``until``.

    Examples:
        >>> import inspect
        >>> "date" in inspect.getsource(_run_log_date_mode)
        True
    """
    conn = open_sevn_sqlite(ctx.workspace_path / ".sevn")
    try:
        tz = session_operator_timezone(conn, ctx.session_id)
    finally:
        conn.close()
    try:
        start_iso, end_iso = resolve_time_range(when=when, since=since, until=until, tz=tz)
    except ValueError as exc:
        return enveloped_failure(
            str(exc), code=ToolResultCode.VALIDATION_ERROR, data={"file": file}
        )
    window = _clamp_line_limit(lines)
    matched, files_read = _query_logs_by_time(
        ctx.workspace_path,
        file,
        start_iso=start_iso,
        end_iso=end_iso,
        pattern=compiled,
        lines=window,
        offset_from_tail=max(0, offset_from_tail),
    )
    # Byte-bound the inline payload (trim oldest) so a date read never spills.
    auto_bounded = False
    while matched and len("\n".join(matched).encode("utf-8")) > LOG_QUERY_INLINE_MAX_BYTES:
        matched = matched[1:]
        auto_bounded = True
    result: dict[str, Any] = {
        "mode": "date",
        "file": file,
        "files": files_read,
        "lines": matched,
        "returned_lines": len(matched),
        "since": start_iso,
        "until": end_iso,
        "pattern": pattern,
    }
    if not files_read:
        result["note"] = "no log files in this date range"
        result["available"] = list_available_log_files(ctx.workspace_path)
    if auto_bounded:
        result["auto_bounded"] = True
        result["summary_notice"] = (
            "Result auto-bounded to stay inline: showing the most recent in-range lines. "
            "Narrow with `pattern` or a tighter date range to see older detail."
        )
    return enveloped_success(result)


@sevn_tool(
    name="log_query",
    category="ops",
    description=(
        "Read, tail, or regex-filter a workspace log under logs/ (redacted; default gateway.log). "
        "Prefer this over `read` for logs — results are bounded inline (auto-summarized when large). "
        "Call with plain keyword args, e.g. `out = await log_query(pattern='ERROR|WARN', lines=100)`; "
        'read the matched lines from `out["data"]["lines"]` (a list of strings) — do NOT iterate '
        "`out` itself. Use one positioning mode per call: tail (default), `offset_from_tail` to page "
        "back, `starting_reading_line` to read forward, or `ranges`. Never wrap the call in a JSON "
        "string or a nested {'code': ...}; pass the arguments directly."
    ),
    long_description_file="tools/log_query.md",
    parameters={
        "type": "object",
        "properties": {
            "file": {
                "type": "string",
                "description": (
                    "Bare filename only (e.g. 'gateway.log'). Paths like 'logs/gateway.log' "
                    "are accepted and normalized. Must not contain '..' or path separators "
                    "after normalization. Defaults to 'gateway.log'. Use 'proxy.log' for proxy "
                    "logs or a rotated name like 'gateway-20260525T143417Z.log'."
                ),
                "default": DEFAULT_LOG_FILE,
            },
            "lines": {
                # Accept a numeric string too (CodeMode models pass lines='100'); coerced in-tool.
                "type": ["integer", "string"],
                "description": (
                    "Line window size: tail/from_line count (default 50, max 500) or "
                    "total cap when using ranges. Example: lines=100."
                ),
                "minimum": 1,
                "maximum": MAX_LOG_QUERY_LINES,
            },
            "pattern": {
                "type": "string",
                "description": (
                    "Optional regex on raw lines before selection. Example: "
                    'pattern="msg=abc123", lines=200.'
                ),
            },
            "offset_from_tail": {
                "type": ["integer", "string"],
                "description": (
                    "Tail mode only: skip the newest lines/matches, then return `lines` older "
                    "entries. Example page 2: offset_from_tail=50, lines=50; "
                    "deeper: offset_from_tail=300, lines=50."
                ),
                "minimum": 0,
                "default": 0,
            },
            "starting_reading_line": {
                "type": ["integer", "string"],
                "description": (
                    "From-line mode (1-based). Example: starting_reading_line=100, lines=50."
                ),
                "minimum": 1,
            },
            "ranges": {
                "type": ["array", "string"],
                "items": {"type": "string"},
                "description": (
                    "Ranges mode: inclusive 1-based intervals as strings 'start-end' or "
                    "'start:end' (NOT dicts). Example: ranges=[\"10-50\"] or "
                    'ranges=["100:120", "500-520"], lines=500. A bare string '
                    '("10-50") or a comma-separated string ("10-50, 100-120") is also accepted. '
                    "For tail reads pass no positioning args (optionally lines=100) — not "
                    "negative offsets."
                ),
            },
            "summarize": {
                # Accept 'true'/'false' strings too (CodeMode models); coerced in-tool.
                "type": ["boolean", "string"],
                "description": (
                    "When True, return a compact tail summary (last "
                    f"{SUMMARY_INLINE_MAX_LINES} lines plus level counts) instead of "
                    "spilling large payloads. Example: lines=200, summarize=True."
                ),
                "default": False,
            },
            "when": {
                "type": "string",
                "description": (
                    "Date mode: read across the log's rotation family (e.g. all gateway*.log) "
                    "and keep only lines in this range, resolved server-side. One of: today, "
                    "yesterday, last_7_days, last_30_days, this_week, last_week, this_month, "
                    "last_month. Do not compute the date yourself. Positioning args "
                    "(ranges/starting_reading_line) are ignored in date mode."
                ),
            },
            "since": {
                "type": "string",
                "description": "Date mode lower bound (inclusive), YYYY-MM-DD or ISO-8601.",
            },
            "until": {
                "type": "string",
                "description": "Date mode upper bound (a bare YYYY-MM-DD includes that whole day).",
            },
        },
    },
    abortable=True,
)
async def log_query_tool(
    ctx: ToolContext,
    file: str = DEFAULT_LOG_FILE,
    lines: int = DEFAULT_LOG_QUERY_LINES,
    pattern: str | None = None,
    offset_from_tail: int = 0,
    starting_reading_line: int | None = None,
    ranges: list[Any] | None = None,
    summarize: bool = False,
    when: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> str:
    """Return redacted log lines from ``<workspace>/logs/<file>``.

    Args:
        ctx (ToolContext): Invocation context with ``workspace_path``.
        file (str): Log filename under ``<workspace>/logs/`` (default ``gateway.log``).
        lines (int): Window or cap size (default 50).
        pattern (str | None): Optional regex filter.
        offset_from_tail (int): Tail-mode pagination skip from newest end.
        starting_reading_line (int | None): 1-based start for forward read mode.
        ranges (list[Any] | None): Inclusive line intervals for ranges mode.
        summarize (bool): When ``True``, return a compact tail summary instead of a
            large inline payload (F13 ergonomics).
        when (str | None): Date mode — relative range (``"yesterday"``…) resolved
            server-side; reads across the log's rotation family.
        since (str | None): Date mode lower bound (``YYYY-MM-DD`` or ISO).
        until (str | None): Date mode upper bound (bare date includes the whole day).

    Returns:
        str: §3.1 JSON envelope string.

    Examples:
        Argument shapes live in ``LOG_QUERY_ARGUMENT_FORMS`` (see ``tools/log_query.md``)::

            LOG_QUERY_ARGUMENT_FORMS["tail_default"]
            LOG_QUERY_ARGUMENT_FORMS["tail_offset_deep"]
            LOG_QUERY_ARGUMENT_FORMS["from_line"]
            LOG_QUERY_ARGUMENT_FORMS["ranges_multi"]
            LOG_QUERY_ARGUMENT_FORMS["file_proxy"]

        >>> import inspect
        >>> inspect.iscoroutinefunction(log_query_tool)
        True
        >>> len(LOG_QUERY_ARGUMENT_FORMS) >= 10
        True
    """
    file = _normalize_log_filename(file)
    # Coerce string-typed kwargs the model sends under CodeMode (e.g. lines='100',
    # offset_from_tail='300', summarize='true') before they reach arithmetic/branching,
    # so a numeric-string call succeeds instead of raising and vanishing in the sandbox.
    coerced_lines, lines_err = _coerce_int_arg(lines, field="lines")
    coerced_offset, offset_err = _coerce_int_arg(offset_from_tail, field="offset_from_tail")
    coerced_start, start_err = _coerce_int_arg(starting_reading_line, field="starting_reading_line")
    coerced_summarize, summarize_err = _coerce_bool_arg(summarize, field="summarize")
    for coercion_err in (lines_err, offset_err, start_err, summarize_err):
        if coercion_err is not None:
            return enveloped_failure(
                coercion_err,
                code=ToolResultCode.VALIDATION_ERROR,
                data={"file": file},
            )
    lines = coerced_lines if coerced_lines is not None else DEFAULT_LOG_QUERY_LINES
    offset_from_tail = coerced_offset if coerced_offset is not None else 0
    starting_reading_line = coerced_start
    summarize = coerced_summarize if coerced_summarize is not None else False
    compiled: re.Pattern[str] | None = None
    if pattern is not None and pattern.strip():
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            return enveloped_failure(
                f"invalid regex pattern: {exc}",
                code=ToolResultCode.VALIDATION_ERROR,
            )
    if (when and when.strip()) or (since and since.strip()) or (until and until.strip()):
        return _run_log_date_mode(
            ctx,
            file=file,
            when=when,
            since=since,
            until=until,
            compiled=compiled,
            pattern=pattern,
            lines=lines,
            offset_from_tail=offset_from_tail,
        )
    try:
        log_path = resolve_log_path(ctx.workspace_path, file)
    except ValueError as exc:
        return enveloped_failure(
            str(exc),
            code=ToolResultCode.VALIDATION_ERROR,
            data={
                "file": file,
                "available": list_available_log_files(ctx.workspace_path),
            },
        )
    coerced_ranges, tail_lines_override, tail_offset_override, range_err = coerce_log_range_args(
        ranges,
    )
    if range_err is not None:
        return enveloped_failure(
            range_err,
            code=ToolResultCode.VALIDATION_ERROR,
            data={"file": file},
        )
    effective_lines = _clamp_line_limit(
        tail_lines_override if tail_lines_override is not None else lines
    )
    effective_offset = (
        tail_offset_override if tail_offset_override is not None else offset_from_tail
    )
    effective_start = starting_reading_line
    effective_ranges = coerced_ranges
    if tail_lines_override is not None and effective_ranges is None:
        effective_start = None
    result, existed, positioning_err = query_log_lines(
        log_path,
        lines=effective_lines,
        pattern=compiled,
        offset_from_tail=effective_offset,
        starting_reading_line=effective_start,
        ranges=effective_ranges,
    )
    if positioning_err is not None:
        return enveloped_failure(
            positioning_err,
            code=ToolResultCode.VALIDATION_ERROR,
            data={"file": file},
        )
    if not existed or result is None:
        relative = log_path.relative_to(ctx.workspace_path)
        return enveloped_failure(
            f"log file not found: {relative}",
            code=ToolResultCode.VALIDATION_ERROR,
            data={
                "path": str(relative),
                "file": file,
                "available": list_available_log_files(ctx.workspace_path),
            },
        )
    rel_path = str(log_path.relative_to(ctx.workspace_path))
    # Auto-bound (no pattern): a full inline read of up to MAX_LOG_QUERY_LINES long lines can
    # exceed the 32 KB spill threshold, which previously produced a non-JSON spill descriptor
    # the model couldn't parse. Fall back to the bounded tail summary so unfiltered reads stay
    # usable (`specs/11-tools-registry.md` §10.13).
    # With a pattern (D11): return matching lines (paged under the inline byte budget) instead
    # of collapsing to ``tail_summary`` — the model asked for matches and needs them.
    has_pattern = compiled is not None
    full_lines_bytes = len("\n".join(result.lines).encode("utf-8"))
    auto_bounded = (
        not summarize and not has_pattern and full_lines_bytes > LOG_QUERY_INLINE_MAX_BYTES
    )
    if summarize or auto_bounded:
        summary = summarize_log_result(result, requested_lines=lines)
        summary["path"] = rel_path
        summary["file"] = file
        summary["pattern"] = pattern
        summary["offset_from_tail"] = effective_offset
        summary["starting_reading_line"] = starting_reading_line
        summary["ranges"] = ranges
        if auto_bounded:
            summary["auto_bounded"] = True
            summary["summary_notice"] = (
                f"Result auto-bounded to stay inline: read {summary['sampled_lines']} line(s), "
                f"showing the last {summary['returned_lines']}. Narrow with `pattern`, request "
                "fewer `lines`, or page deeper with `offset_from_tail` to see specific detail."
            )
        return enveloped_success(summary)
    lines_out = result.lines
    numbers_out = result.line_numbers
    has_more = False
    next_offset: int | None = None
    if has_pattern:
        # Match-set cursor: offset_from_tail counts matching lines, not file lines.
        # Fit keeps the newest matches under the inline budget; page older matches
        # by advancing that match offset. Also signal when the query hit ``lines``.
        page_cap = max(effective_lines, SUMMARY_INLINE_MAX_LINES + 1)
        if full_lines_bytes > LOG_QUERY_INLINE_MAX_BYTES:
            lines_out, numbers_out = _fit_inline_lines(
                result.lines,
                result.line_numbers,
                max_lines=page_cap,
                max_bytes=LOG_QUERY_INLINE_MAX_BYTES,
            )
        shown = len(lines_out)
        truncated_fit = shown < len(result.lines)
        hit_line_cap = len(result.lines) >= effective_lines
        if truncated_fit or hit_line_cap:
            has_more = True
            # Skip the newest ``shown`` matches already returned (fit keeps the tail).
            next_offset = effective_offset + shown
    payload: dict[str, Any] = {
        "path": rel_path,
        "file": file,
        "lines": lines_out,
        "line_numbers": numbers_out,
        "count": len(lines_out),
        "returned_lines": len(lines_out),
        "mode": result.mode,
        "total_file_lines": result.total_file_lines,
        "pattern": pattern,
        "offset_from_tail": effective_offset,
        "starting_reading_line": starting_reading_line,
        "ranges": ranges,
    }
    if has_more and next_offset is not None:
        payload["has_more"] = True
        payload["next_offset_from_tail"] = next_offset
        payload["summary_notice"] = (
            f"Paged matching lines: showing {len(lines_out)} match(es) inline "
            f"(match-set offset {effective_offset}). Call again with "
            f"`offset_from_tail={next_offset}` to page older matches."
        )
    return enveloped_success(payload)


def register_log_query_tool(executor: ToolExecutor) -> None:
    """Register the always-on ``log_query`` tool.

    Args:
        executor (ToolExecutor): Registry under construction.

    Returns:
        None

    Examples:
        >>> from sevn.tools.base import ToolExecutor
        >>> from sevn.tools.log_query import register_log_query_tool
        >>> exe = ToolExecutor()
        >>> register_log_query_tool(exe)
        >>> "log_query" in {d.name for d in exe.definitions()}
        True
    """
    executor.register(tool_from_decorated(log_query_tool))


__all__ = [
    "DEFAULT_LOG_FILE",
    "DEFAULT_LOG_QUERY_LINES",
    "LOG_QUERY_ARGUMENT_FORMS",
    "MAX_LOG_QUERY_LINES",
    "SUMMARY_INLINE_MAX_LINES",
    "LogLineSpan",
    "LogQueryResult",
    "coerce_log_range_args",
    "list_available_log_files",
    "log_query_tool",
    "parse_log_ranges",
    "query_log_lines",
    "register_log_query_tool",
    "resolve_log_path",
    "resolve_sevn_log_path",
    "summarize_log_result",
    "tail_log_lines",
]
