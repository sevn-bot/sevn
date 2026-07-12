"""Tests for ``sevn.tools.log_query`` — default file, rotations, path-traversal guard.

These cover the Cluster 2 fixes (transcript-review items #3, #11, #12): default reads
``logs/gateway.log``, accepts ``proxy.log`` and rotated files, rejects path traversal, and
surfaces a clear failure envelope (with the list of available logs) when the file does not
exist.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sevn.config.defaults import TOOL_LARGE_RESULT_THRESHOLD_BYTES
from sevn.tools.base import ToolCall
from sevn.tools.context import ToolContext
from sevn.tools.log_query import (
    DEFAULT_LOG_FILE,
    LOG_QUERY_MAX_LINE_CHARS,
    SUMMARY_INLINE_MAX_LINES,
    LogQueryResult,
    _normalize_log_filename,
    coerce_log_range_args,
    list_available_log_files,
    parse_log_ranges,
    query_log_lines,
    resolve_log_path,
    summarize_log_result,
)
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import build_session_registry


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Build a workspace with gateway.log + proxy.log + a rotated gateway log."""
    root = tmp_path / "ws"
    root.mkdir()
    logs = root / "logs"
    logs.mkdir()
    _ = (logs / "gateway.log").write_text(
        "INFO boot ok\nWARN slow request\nERROR token=hunter2\n",
        encoding="utf-8",
    )
    _ = (logs / "proxy.log").write_text(
        "proxy started\nproxy 200 ok\n",
        encoding="utf-8",
    )
    _ = (logs / "gateway-20260525T143417Z.log").write_text(
        "rotated entry one\nrotated entry two\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture
def ctx(workspace: Path) -> ToolContext:
    return ToolContext(
        session_id="log-sess",
        workspace_path=workspace,
        workspace_id="log-wid",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )


def test_resolve_log_path_defaults_to_gateway_log(tmp_path: Path) -> None:
    """Default file argument resolves to ``<ws>/logs/gateway.log``."""
    assert resolve_log_path(tmp_path).name == DEFAULT_LOG_FILE == "gateway.log"
    assert resolve_log_path(tmp_path) == tmp_path / "logs" / "gateway.log"


def test_resolve_log_path_rejects_traversal(tmp_path: Path) -> None:
    """Any value with ``/``, ``\\``, or ``..`` is refused before touching disk."""
    for bad in ("../secret", "logs/x", "a\\b", ".."):
        with pytest.raises(ValueError, match="log_query"):
            resolve_log_path(tmp_path, bad)
    with pytest.raises(ValueError, match="non-empty"):
        resolve_log_path(tmp_path, "")


def test_normalize_log_filename_strips_logs_prefix() -> None:
    """Model paths like ``logs/gateway.log`` normalize to bare filenames."""
    assert _normalize_log_filename("logs/gateway.log") == "gateway.log"
    assert _normalize_log_filename("./logs/proxy.log") == "proxy.log"
    assert _normalize_log_filename("  ./gateway.log  ") == "gateway.log"


def test_normalize_log_filename_preserves_traversal_markers() -> None:
    """Traversal attempts stay intact for ``resolve_log_path`` to reject."""
    assert _normalize_log_filename("../gateway.log") == "../gateway.log"
    assert _normalize_log_filename("logs/../../etc/passwd") == "../../etc/passwd"


@pytest.mark.asyncio
async def test_log_query_normalized_logs_path_reads_gateway_log(ctx: ToolContext) -> None:
    """``logs/gateway.log`` succeeds the same as bare ``gateway.log``."""
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        ctx,
        ToolCall(name="log_query", arguments={"file": "logs/gateway.log"}),
    )
    env = json.loads(raw)
    assert env["ok"] is True
    assert env["data"]["count"] == 3


@pytest.mark.asyncio
async def test_log_query_normalized_dot_logs_path_reads_proxy_log(ctx: ToolContext) -> None:
    """``./logs/proxy.log`` succeeds the same as bare ``proxy.log``."""
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        ctx,
        ToolCall(name="log_query", arguments={"file": "./logs/proxy.log"}),
    )
    env = json.loads(raw)
    assert env["ok"] is True
    assert env["data"]["file"] == "proxy.log"
    joined = "\n".join(env["data"]["lines"])
    assert "proxy started" in joined


@pytest.mark.asyncio
async def test_log_query_traversal_after_normalize_still_rejected(ctx: ToolContext) -> None:
    """Traversal via ``logs/../../`` prefix still returns VALIDATION_ERROR."""
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        ctx,
        ToolCall(name="log_query", arguments={"file": "logs/../../etc/passwd"}),
    )
    env = json.loads(raw)
    assert env["ok"] is False
    assert env["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_log_query_parent_traversal_still_rejected(ctx: ToolContext) -> None:
    """``../gateway.log`` remains a validation error after normalization."""
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        ctx,
        ToolCall(name="log_query", arguments={"file": "../gateway.log"}),
    )
    env = json.loads(raw)
    assert env["ok"] is False
    assert env["code"] == "VALIDATION_ERROR"


def test_list_available_log_files(workspace: Path) -> None:
    """The lister returns every ``*.log`` filename, sorted."""
    names = list_available_log_files(workspace)
    assert "gateway.log" in names
    assert "proxy.log" in names
    assert "gateway-20260525T143417Z.log" in names
    assert names == sorted(names)


def test_list_available_log_files_missing_dir(tmp_path: Path) -> None:
    """Missing ``logs/`` returns an empty list, not an exception."""
    assert list_available_log_files(tmp_path) == []


@pytest.mark.asyncio
async def test_log_query_default_reads_gateway_log(ctx: ToolContext) -> None:
    """No-arg call tails ``gateway.log`` and redacts secrets."""
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(ctx, ToolCall(name="log_query", arguments={}))
    env = json.loads(raw)
    assert env["ok"] is True
    assert env["data"]["file"] == "gateway.log"
    assert env["data"]["count"] == 3
    joined = "\n".join(env["data"]["lines"])
    assert "hunter2" not in joined  # redaction still applies
    assert "boot ok" in joined


@pytest.mark.asyncio
async def test_log_query_reads_proxy_log(ctx: ToolContext) -> None:
    """Passing ``file='proxy.log'`` reads the proxy log instead."""
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        ctx,
        ToolCall(name="log_query", arguments={"file": "proxy.log"}),
    )
    env = json.loads(raw)
    assert env["ok"] is True
    assert env["data"]["file"] == "proxy.log"
    joined = "\n".join(env["data"]["lines"])
    assert "proxy started" in joined


@pytest.mark.asyncio
async def test_log_query_reads_rotated_file(ctx: ToolContext) -> None:
    """Rotated filenames work too."""
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        ctx,
        ToolCall(
            name="log_query",
            arguments={"file": "gateway-20260525T143417Z.log"},
        ),
    )
    env = json.loads(raw)
    assert env["ok"] is True
    assert env["data"]["count"] == 2


@pytest.mark.asyncio
async def test_log_query_path_traversal_returns_validation_error(ctx: ToolContext) -> None:
    """Traversal attempts return a VALIDATION_ERROR envelope with the available list."""
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        ctx,
        ToolCall(name="log_query", arguments={"file": "../etc/passwd"}),
    )
    env = json.loads(raw)
    assert env["ok"] is False
    assert env["code"] == "VALIDATION_ERROR"
    assert "gateway.log" in env["data"]["available"]


@pytest.mark.asyncio
async def test_log_query_missing_file_lists_available(ctx: ToolContext) -> None:
    """Missing-file failure includes the available log filenames so the agent can pick one."""
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        ctx,
        ToolCall(name="log_query", arguments={"file": "nope.log"}),
    )
    env = json.loads(raw)
    assert env["ok"] is False
    assert env["code"] == "VALIDATION_ERROR"
    assert env["data"]["file"] == "nope.log"
    assert "gateway.log" in env["data"]["available"]


def test_parse_log_ranges_accepts_dash_and_colon() -> None:
    """Range specs parse as inclusive 1-based spans."""
    spans, err = parse_log_ranges(["10-50", "100:120"])
    assert err is None
    assert spans[0].start == 10
    assert spans[0].end == 50
    assert spans[1].start == 100
    assert spans[1].end == 120


@pytest.fixture
def numbered_log(workspace: Path) -> Path:
    """``gateway.log`` with ten numbered lines for pagination tests."""
    log = workspace / "logs" / "gateway.log"
    _ = log.write_text("\n".join(f"line{i}" for i in range(1, 11)) + "\n", encoding="utf-8")
    return log


def test_query_log_lines_offset_from_tail(numbered_log: Path) -> None:
    """``offset_from_tail`` skips the newest lines before returning the window."""
    result, existed, err = query_log_lines(
        numbered_log,
        lines=2,
        offset_from_tail=2,
    )
    assert err is None
    assert existed
    assert result is not None
    assert result.mode == "tail"
    assert result.line_numbers == [7, 8]
    assert result.lines == ["line7", "line8"]


def test_query_log_lines_starting_reading_line(numbered_log: Path) -> None:
    """``starting_reading_line`` reads forward from a 1-based line index."""
    result, existed, err = query_log_lines(
        numbered_log,
        lines=3,
        starting_reading_line=3,
    )
    assert err is None
    assert existed
    assert result is not None
    assert result.mode == "from_line"
    assert result.line_numbers == [3, 4, 5]


def test_query_log_lines_ranges(numbered_log: Path) -> None:
    """``ranges`` returns explicit inclusive intervals in file order."""
    result, existed, err = query_log_lines(
        numbered_log,
        lines=500,
        ranges=["2-3", "9:10"],
    )
    assert err is None
    assert existed
    assert result is not None
    assert result.mode == "ranges"
    assert result.line_numbers == [2, 3, 9, 10]


def test_query_log_lines_rejects_conflicting_modes(numbered_log: Path) -> None:
    """Only one positioning mode is allowed per call."""
    _, existed, err = query_log_lines(
        numbered_log,
        lines=2,
        offset_from_tail=1,
        starting_reading_line=1,
    )
    assert existed
    assert err is not None


@pytest.mark.asyncio
async def test_log_query_offset_from_tail_dispatch(ctx: ToolContext, numbered_log: Path) -> None:
    """Dispatch exposes offset pagination in the success envelope."""
    _ = numbered_log
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        ctx,
        ToolCall(
            name="log_query",
            arguments={"lines": 1, "offset_from_tail": 1},
        ),
    )
    env = json.loads(raw)
    assert env["ok"] is True
    assert env["data"]["mode"] == "tail"
    assert env["data"]["line_numbers"] == [9]
    assert env["data"]["lines"] == ["line9"]


@pytest.mark.asyncio
async def test_log_query_ranges_dispatch(ctx: ToolContext, numbered_log: Path) -> None:
    """Dispatch accepts ``ranges`` and returns line_numbers."""
    _ = numbered_log
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        ctx,
        ToolCall(name="log_query", arguments={"ranges": ["1-2"], "lines": 10}),
    )
    env = json.loads(raw)
    assert env["ok"] is True
    assert env["data"]["mode"] == "ranges"
    assert env["data"]["line_numbers"] == [1, 2]


@pytest.mark.asyncio
async def test_log_query_coerces_string_int_kwargs(ctx: ToolContext, numbered_log: Path) -> None:
    """CodeMode string-typed numeric kwargs (``lines='1'``, ``offset_from_tail='1'``) succeed.

    MiniMax-class models pass typed kwargs as strings inside ``run_code``; coercion turns
    a would-be TypeError (silently dropped in the sandbox) into a normal success envelope.
    """
    _ = numbered_log
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        ctx,
        ToolCall(
            name="log_query",
            arguments={"lines": "1", "offset_from_tail": "1"},
        ),
    )
    env = json.loads(raw)
    assert env["ok"] is True
    assert env["data"]["mode"] == "tail"
    assert env["data"]["line_numbers"] == [9]
    assert env["data"]["lines"] == ["line9"]


@pytest.mark.asyncio
async def test_log_query_coerces_string_bool_false(ctx: ToolContext, workspace: Path) -> None:
    """``summarize='false'`` must stay falsey (a bare truthiness check would flip it on)."""
    log = workspace / "logs" / "gateway.log"
    body = "\n".join(f"INFO line{i}" for i in range(1, 21)) + "\n"
    _ = log.write_text(body, encoding="utf-8")
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        ctx,
        ToolCall(name="log_query", arguments={"lines": "20", "summarize": "false"}),
    )
    env = json.loads(raw)
    assert env["ok"] is True
    assert env["data"]["mode"] == "tail"


@pytest.mark.asyncio
async def test_log_query_non_numeric_kwarg_returns_validation_error(
    ctx: ToolContext,
) -> None:
    """A non-numeric ``lines`` returns a readable ``ok=false`` envelope, not a raised error."""
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        ctx,
        ToolCall(name="log_query", arguments={"lines": "lots"}),
    )
    env = json.loads(raw)
    assert env["ok"] is False
    assert "lines" in env["error"]


def test_coerce_log_range_args_negative_tail_dict() -> None:
    """Dict negative-start ranges map to tail mode (F12)."""
    string_ranges, tail_lines, tail_offset, err = coerce_log_range_args(
        [{"start": "-100", "limit": "200"}],
    )
    assert err is None
    assert string_ranges is None
    assert tail_lines == 200
    assert tail_offset == 0


@pytest.mark.asyncio
async def test_log_query_negative_tail_dict_dispatch(ctx: ToolContext, numbered_log: Path) -> None:
    """Dispatch accepts model dict tail ranges without VALIDATION_ERROR."""
    _ = numbered_log
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        ctx,
        ToolCall(
            name="log_query",
            arguments={"ranges": [{"start": "-100", "limit": "200"}]},
        ),
    )
    env = json.loads(raw)
    assert env["ok"] is True
    assert env["data"]["mode"] == "tail"
    assert env["data"]["count"] == 10


def test_summarize_log_result_caps_inline_lines() -> None:
    """Summarize mode keeps only the tail sample inline."""
    sample = LogQueryResult(
        lines=[f"INFO line{i}" for i in range(1, 51)],
        line_numbers=list(range(1, 51)),
        mode="tail",
        total_file_lines=500,
    )
    payload = summarize_log_result(sample, requested_lines=200)
    assert payload["mode"] == "tail_summary"
    assert payload["returned_lines"] == SUMMARY_INLINE_MAX_LINES
    assert payload["sampled_lines"] == 50


@pytest.mark.asyncio
async def test_log_query_summarize_dispatch(ctx: ToolContext, workspace: Path) -> None:
    """Summarize flag returns compact tail summary without full spill."""
    log = workspace / "logs" / "gateway.log"
    body = "\n".join(f"INFO line{i}" for i in range(1, 121)) + "\n"
    _ = log.write_text(body, encoding="utf-8")
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        ctx,
        ToolCall(name="log_query", arguments={"lines": 120, "summarize": True}),
    )
    env = json.loads(raw)
    assert env["ok"] is True
    assert env["data"]["mode"] == "tail_summary"
    assert env["data"]["returned_lines"] <= SUMMARY_INLINE_MAX_LINES
    assert "spill_path" not in env["data"]


@pytest.mark.asyncio
async def test_log_query_auto_bounds_large_default_read(workspace: Path) -> None:
    """A full (non-summarize) read of many long lines stays inline (no spill, valid JSON)."""
    logs = workspace / "logs"
    big = "\n".join(f"INFO line {i} " + "x" * 300 for i in range(1, 2001))
    _ = (logs / "gateway.log").write_text(big, encoding="utf-8")
    ctx = ToolContext(
        session_id="log-sess",
        workspace_path=workspace,
        workspace_id="log-wid",
        registry_version=1,
        permissions=AllowAllPermissionPolicy(),
    )
    exe, _ = build_session_registry(registry_version=1)

    raw = await exe.dispatch(ctx, ToolCall(name="log_query", arguments={"lines": 500}))

    # Envelope must stay under the spill threshold and remain valid JSON.
    assert len(raw.encode("utf-8")) < TOOL_LARGE_RESULT_THRESHOLD_BYTES
    env = json.loads(raw)
    assert env["ok"] is True
    assert env["data"]["mode"] == "tail_summary"
    assert env["data"]["auto_bounded"] is True
    assert "spill_path" not in env["data"]
    assert env["data"]["returned_lines"] <= SUMMARY_INLINE_MAX_LINES


@pytest.mark.asyncio
async def test_log_query_truncates_pathological_long_line(workspace: Path) -> None:
    """A single enormous log line is truncated, not spilled."""
    logs = workspace / "logs"
    _ = (logs / "gateway.log").write_text("INFO " + "y" * 80_000 + "\n", encoding="utf-8")
    ctx = ToolContext(
        session_id="log-sess",
        workspace_path=workspace,
        workspace_id="log-wid",
        registry_version=1,
        permissions=AllowAllPermissionPolicy(),
    )
    exe, _ = build_session_registry(registry_version=1)

    raw = await exe.dispatch(ctx, ToolCall(name="log_query", arguments={"lines": 10}))

    assert len(raw.encode("utf-8")) < TOOL_LARGE_RESULT_THRESHOLD_BYTES
    env = json.loads(raw)
    assert env["ok"] is True
    assert any("…[truncated]" in line for line in env["data"]["lines"])
    assert all(len(line) <= LOG_QUERY_MAX_LINE_CHARS + 16 for line in env["data"]["lines"])


def test_coerce_log_range_args_accepts_bare_string() -> None:
    """A bare 'N-M' string (not a list) is accepted, not iterated as characters."""
    string_ranges, tail_lines, tail_offset, err = coerce_log_range_args("10-50")
    assert err is None
    assert string_ranges == ["10-50"]
    assert tail_lines is None
    assert tail_offset is None


def test_coerce_log_range_args_accepts_comma_separated_string() -> None:
    string_ranges, _lines, _offset, err = coerce_log_range_args("10-50, 100-120")
    assert err is None
    assert string_ranges == ["10-50", "100-120"]


@pytest.mark.asyncio
async def test_log_query_bare_string_ranges_dispatch(ctx: ToolContext) -> None:
    """log_query accepts ranges passed as a bare string end-to-end."""
    logs = ctx.workspace_path / "logs"
    _ = (logs / "gateway.log").write_text(
        "\n".join(f"line {i}" for i in range(1, 31)), encoding="utf-8"
    )
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(ctx, ToolCall(name="log_query", arguments={"ranges": "5-7"}))
    env = json.loads(raw)
    assert env["ok"] is True
    joined = "\n".join(env["data"]["lines"])
    assert "line 5" in joined
    assert "line 7" in joined


@pytest.fixture
def dated_logs_ws(tmp_path: Path) -> Path:
    """Workspace whose gateway family logs carry dated, timestamped lines."""
    root = tmp_path / "ws"
    (root / ".sevn").mkdir(parents=True)
    logs = root / "logs"
    logs.mkdir()
    (logs / "gateway-20260702T235959Z.log").write_text(
        "2026-07-02 12:00:00.000+00:00 | INFO | - | mod:1 fn | yesterday-line\n"
        "2026-07-02 18:30:00.000+00:00 | WARN | - | mod:2 fn | yesterday-warn\n",
        encoding="utf-8",
    )
    (logs / "gateway.log").write_text(
        "2026-07-03 09:00:00.000+00:00 | INFO | - | mod:3 fn | today-line\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture
def dated_ctx(dated_logs_ws: Path) -> ToolContext:
    return ToolContext(
        session_id="log-sess",
        workspace_path=dated_logs_ws,
        workspace_id="log-wid",
        registry_version=1,
        permissions=AllowAllPermissionPolicy(),
    )


@pytest.mark.asyncio
async def test_log_query_since_until_filters_to_day(dated_ctx: ToolContext) -> None:
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        dated_ctx,
        ToolCall(name="log_query", arguments={"since": "2026-07-02", "until": "2026-07-02"}),
    )
    data = json.loads(raw)["data"]
    assert data["mode"] == "date"
    body = "\n".join(data["lines"])
    assert "yesterday-line" in body
    assert "yesterday-warn" in body
    assert "today-line" not in body
    assert data["since"] == "2026-07-02T00:00:00"


@pytest.mark.asyncio
async def test_log_query_date_mode_scans_rotation_family(dated_ctx: ToolContext) -> None:
    """A wide range pulls lines from both the rotated file and the live log."""
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        dated_ctx,
        ToolCall(name="log_query", arguments={"since": "2026-07-01", "until": "2026-07-03"}),
    )
    data = json.loads(raw)["data"]
    body = "\n".join(data["lines"])
    assert "yesterday-line" in body
    assert "today-line" in body
    assert len(data["files"]) == 2


@pytest.mark.asyncio
async def test_log_query_date_mode_pattern_filter(dated_ctx: ToolContext) -> None:
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        dated_ctx,
        ToolCall(
            name="log_query",
            arguments={"since": "2026-07-01", "until": "2026-07-03", "pattern": "WARN"},
        ),
    )
    data = json.loads(raw)["data"]
    assert [line for line in data["lines"] if "yesterday-warn" in line]
    assert not [line for line in data["lines"] if "today-line" in line]


@pytest.mark.asyncio
async def test_log_query_date_mode_empty_range_notes_available(dated_ctx: ToolContext) -> None:
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        dated_ctx,
        ToolCall(name="log_query", arguments={"since": "2020-01-01", "until": "2020-01-01"}),
    )
    data = json.loads(raw)["data"]
    assert data["lines"] == []
    assert "note" in data


@pytest.mark.asyncio
async def test_log_query_bad_when_is_validation_error(dated_ctx: ToolContext) -> None:
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        dated_ctx,
        ToolCall(name="log_query", arguments={"when": "someday"}),
    )
    envelope = json.loads(raw)
    assert envelope["ok"] is False
    assert "unknown relative range" in envelope["error"]
