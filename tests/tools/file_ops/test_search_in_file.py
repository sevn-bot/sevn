"""``search_in_file`` tool tests (`plan/tools-skills-full-inventory-wave-plan.md` Wave 3)."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from sevn.tools.base import ToolCall, ToolExecutor
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.file_ops.search import (
    MAX_MATCH_LINE_CHARS,
    MAX_SEARCH_MATCHES,
    _build_rg_argv,
    _parse_rg_match_line,
    _run_python_search_sync,
    _run_ripgrep,
)
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import build_session_registry


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Fixture tree with repeated searchable content."""
    root = tmp_path / "ws"
    root.mkdir()
    src = root / "src"
    src.mkdir()
    (src / "alpha.py").write_text("def alpha():\n    return 'alpha needle'\n", encoding="utf-8")
    (src / "beta.py").write_text("# beta comment\nVALUE = 1\n", encoding="utf-8")
    nested = src / "pkg"
    nested.mkdir()
    (nested / "util.py").write_text("needle in util\n", encoding="utf-8")
    (root / "notes.txt").write_text("plain needle line\n", encoding="utf-8")
    return root


@pytest.fixture
def ctx(workspace: Path) -> ToolContext:
    return ToolContext(
        session_id="search-sess",
        workspace_path=workspace,
        workspace_id="search-wid",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )


@pytest.fixture
def executor() -> ToolExecutor:
    exe, _tool_set = build_session_registry(registry_version=1)
    return exe


def _fake_matches(count: int, *, prefix: str = "src/alpha.py") -> list[dict[str, object]]:
    return [
        {"path": prefix, "line": index + 1, "text": f"needle line {index}"}
        for index in range(count)
    ]


@pytest.fixture
def force_ripgrep_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend ``rg`` exists so tests can stub :func:`_run_ripgrep` only."""
    monkeypatch.setattr("sevn.tools.file_ops.search._find_rg_binary", lambda: "/usr/bin/rg")


@pytest.mark.asyncio
async def test_search_in_file_registered(executor: ToolExecutor) -> None:
    names = {definition.name for definition in executor.definitions()}
    assert "search_in_file" in names


@pytest.mark.asyncio
async def test_search_finds_matches(
    executor: ToolExecutor,
    ctx: ToolContext,
    monkeypatch: pytest.MonkeyPatch,
    force_ripgrep_path: None,
) -> None:
    async def _stub(**_kwargs: Any) -> tuple[list[dict[str, object]], bool, str | None]:
        return (
            [
                {"path": "src/alpha.py", "line": 2, "text": "    return 'alpha needle'"},
                {"path": "notes.txt", "line": 1, "text": "plain needle line"},
            ],
            False,
            None,
        )

    monkeypatch.setattr("sevn.tools.file_ops.search._run_ripgrep", _stub)
    raw = await executor.dispatch(
        ctx,
        ToolCall(name="search_in_file", arguments={"pattern": "needle", "path": "."}),
    )
    envelope = json.loads(raw)
    assert envelope["ok"] is True
    assert envelope["data"]["count"] == 2
    assert "alpha.py:2:" in envelope["data"]["content"]
    assert envelope["data"]["truncated"] is False


@pytest.mark.asyncio
async def test_search_match_limit_truncated(
    executor: ToolExecutor,
    ctx: ToolContext,
    monkeypatch: pytest.MonkeyPatch,
    force_ripgrep_path: None,
) -> None:
    cap = 3

    async def _stub(**_kwargs: Any) -> tuple[list[dict[str, object]], bool, str | None]:
        return _fake_matches(cap), True, None

    monkeypatch.setattr("sevn.tools.file_ops.search._run_ripgrep", _stub)
    raw = await executor.dispatch(
        ctx,
        ToolCall(
            name="search_in_file",
            arguments={"pattern": "needle", "path": "src", "include": "**/*.py"},
        ),
    )
    envelope = json.loads(raw)
    assert envelope["ok"] is True
    assert envelope["data"]["count"] == cap
    assert envelope["data"]["truncated"] is True
    assert envelope["data"]["include"] == "**/*.py"


@pytest.mark.asyncio
async def test_search_denies_llmignore(
    executor: ToolExecutor,
    ctx: ToolContext,
    workspace: Path,
) -> None:
    blocked = workspace / ".llmignore" / "blocked" / "secret.txt"
    blocked.parent.mkdir(parents=True)
    blocked.write_text("needle", encoding="utf-8")
    raw = await executor.dispatch(
        ctx,
        ToolCall(
            name="search_in_file",
            arguments={"pattern": "needle", "path": ".llmignore/blocked/secret.txt"},
        ),
    )
    envelope = json.loads(raw)
    assert envelope["ok"] is False
    assert envelope["code"] == ToolResultCode.PERMISSION_DENIED


@pytest.mark.asyncio
async def test_search_denies_escape_root(
    executor: ToolExecutor,
    ctx: ToolContext,
) -> None:
    raw = await executor.dispatch(
        ctx,
        ToolCall(name="search_in_file", arguments={"pattern": "x", "path": "../outside"}),
    )
    envelope = json.loads(raw)
    assert envelope["ok"] is False
    assert envelope["code"] == ToolResultCode.VALIDATION_ERROR


@pytest.mark.asyncio
async def test_large_search_spills_to_disk(
    executor: ToolExecutor,
    ctx: ToolContext,
    monkeypatch: pytest.MonkeyPatch,
    force_ripgrep_path: None,
) -> None:
    async def _stub(**_kwargs: Any) -> tuple[list[dict[str, object]], bool, str | None]:
        # Exceed TOOL_LARGE_RESULT_THRESHOLD_BYTES (32 KiB) so dispatch spills to disk.
        return _fake_matches(1500, prefix="src/alpha.py"), False, None

    monkeypatch.setattr("sevn.tools.file_ops.search._run_ripgrep", _stub)
    raw = await executor.dispatch(
        ctx,
        ToolCall(name="search_in_file", arguments={"pattern": "needle", "path": "."}),
    )
    envelope = json.loads(raw)
    assert envelope["ok"] is True
    data = envelope["data"]
    assert {"spill_path", "summary", "size"}.issubset(data.keys())
    assert "spill_notice" in data
    spill_path = ctx.workspace_path / data["spill_path"]
    assert spill_path.is_file()
    assert spill_path.stat().st_size > 2000


@pytest.mark.asyncio
async def test_search_empty_pattern_rejected(
    executor: ToolExecutor,
    ctx: ToolContext,
) -> None:
    raw = await executor.dispatch(
        ctx,
        ToolCall(name="search_in_file", arguments={"pattern": "   ", "path": "."}),
    )
    envelope = json.loads(raw)
    assert envelope["ok"] is False
    assert envelope["code"] == ToolResultCode.VALIDATION_ERROR


@pytest.mark.asyncio
async def test_search_python_fallback_when_rg_missing(
    executor: ToolExecutor,
    ctx: ToolContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loguru import logger as loguru_logger

    monkeypatch.setattr("sevn.tools.file_ops.search._find_rg_binary", lambda: None)
    monkeypatch.setattr("sevn.tools.file_ops.search._python_fallback_logged", False)
    captured: list[str] = []
    sink_id = loguru_logger.add(lambda rec: captured.append(str(rec)), level="WARNING")
    try:
        raw = await executor.dispatch(
            ctx,
            ToolCall(name="search_in_file", arguments={"pattern": "needle", "path": "."}),
        )
    finally:
        loguru_logger.remove(sink_id)
    envelope = json.loads(raw)
    assert envelope["ok"] is True
    assert envelope["data"]["engine"] == "python"
    assert envelope["data"]["count"] >= 1
    assert any("search_in_file_no_ripgrep_using_python_fallback" in line for line in captured)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_integration_with_rg(
    workspace: Path,
    ctx: ToolContext,
) -> None:
    if shutil.which("rg") is None:
        pytest.skip("ripgrep (rg) not installed")

    matches, truncated, error = await _run_ripgrep(
        workspace=workspace,
        pattern="needle",
        search_path=workspace,
        include_glob="**/*.py",
        max_matches=MAX_SEARCH_MATCHES,
    )
    assert error is None
    assert truncated is False
    paths = {str(row["path"]) for row in matches}
    assert "src/alpha.py" in paths
    assert "src/pkg/util.py" in paths


# --- per-match line-width cap regression (MAX_MATCH_LINE_CHARS) -----------------------
#
# `MAX_SEARCH_MATCHES` bounds the number of match rows but nothing bounded the width of
# any single row. A workspace-root search over `.jsonl` session transcripts returned 500
# rows totalling 9.48 MB of match text (longest line: 761,134 chars) => a 22.68 MB tool
# payload taking 38.5s, which blew the executor turn budget.


def _needle_line(length: int) -> str:
    """Build a matching line of exactly ``length`` chars containing ``needle``."""
    return "needle" + "x" * (length - len("needle"))


def _rg_match_payload(path: Path, line_text: str, *, line_number: int = 1) -> str:
    """Serialise one ``rg --json`` ``type=match`` stdout row."""
    return json.dumps(
        {
            "type": "match",
            "data": {
                "path": {"text": str(path)},
                "lines": {"text": f"{line_text}\n"},
                "line_number": line_number,
            },
        },
    )


def _engine_match_text(engine: str, *, line_text: str, workspace: Path, target: Path) -> str:
    """Return the ``text`` field one engine produces for ``line_text``."""
    if engine == "ripgrep":
        rows: list[dict[str, object]] = []
        _parse_rg_match_line(
            _rg_match_payload(target, line_text),
            workspace=workspace,
            matches=rows,
            max_matches=10,
        )
        return str(rows[0]["text"])

    target.write_text(f"{line_text}\n", encoding="utf-8")
    matches, _truncated, error = _run_python_search_sync(
        workspace=workspace,
        pattern="needle",
        search_path=target,
        include_glob=None,
    )
    assert error is None
    return str(matches[0]["text"])


def test_rg_json_path_clips_long_match_line(tmp_path: Path) -> None:
    """Ripgrep JSON rows are clipped and the annotation reports the ORIGINAL length."""
    target = tmp_path / "transcript.jsonl"
    target.write_text("placeholder\n", encoding="utf-8")
    raw_length = 761_134

    rows: list[dict[str, object]] = []
    capped = _parse_rg_match_line(
        _rg_match_payload(target, _needle_line(raw_length)),
        workspace=tmp_path,
        matches=rows,
        max_matches=10,
    )

    assert capped is False
    text = str(rows[0]["text"])
    assert len(text) < MAX_MATCH_LINE_CHARS + 64
    assert text.startswith(_needle_line(raw_length)[:MAX_MATCH_LINE_CHARS])
    assert f"[line truncated, {raw_length} chars]" in text


def test_python_fallback_clips_long_match_line(tmp_path: Path) -> None:
    """The Python fallback is a separate code path and must clip identically."""
    target = tmp_path / "minified.js"
    raw_length = 200_008
    target.write_text(f"{_needle_line(raw_length)}\n", encoding="utf-8")

    matches, truncated, error = _run_python_search_sync(
        workspace=tmp_path,
        pattern="needle",
        search_path=target,
        include_glob=None,
    )

    assert error is None
    assert truncated is False
    text = str(matches[0]["text"])
    assert len(text) < MAX_MATCH_LINE_CHARS + 64
    assert f"[line truncated, {raw_length} chars]" in text


def test_both_engines_produce_identical_clipped_text(tmp_path: Path) -> None:
    """Ripgrep and Python fallback must agree byte-for-byte on a clipped line."""
    line_text = _needle_line(50_000)
    rg_text = _engine_match_text(
        "ripgrep",
        line_text=line_text,
        workspace=tmp_path,
        target=tmp_path / "rg.jsonl",
    )
    python_text = _engine_match_text(
        "python",
        line_text=line_text,
        workspace=tmp_path,
        target=tmp_path / "py.jsonl",
    )
    assert rg_text == python_text


@pytest.mark.parametrize("engine", ["ripgrep", "python"])
@pytest.mark.parametrize(
    ("raw_length", "expect_clipped"),
    [
        (MAX_MATCH_LINE_CHARS - 1, False),
        (MAX_MATCH_LINE_CHARS, False),
        (MAX_MATCH_LINE_CHARS + 1, True),
    ],
)
def test_clip_boundary_is_inclusive_in_both_engines(
    tmp_path: Path,
    engine: str,
    raw_length: int,
    expect_clipped: bool,
) -> None:
    """Lines up to and including the cap pass through unchanged; cap+1 is clipped."""
    line_text = _needle_line(raw_length)
    text = _engine_match_text(
        engine,
        line_text=line_text,
        workspace=tmp_path,
        target=tmp_path / f"{engine}-boundary.txt",
    )

    if expect_clipped:
        assert text != line_text
        assert text.startswith(line_text[:MAX_MATCH_LINE_CHARS])
        assert f"[line truncated, {raw_length} chars]" in text
    else:
        assert text == line_text


def test_total_match_payload_stays_bounded(tmp_path: Path) -> None:
    """Many oversized lines cannot recreate the 22 MB payload blowup."""
    oversized_line = _needle_line(5_000)
    line_count = MAX_SEARCH_MATCHES + 100
    target = tmp_path / "session.jsonl"
    target.write_text("\n".join([oversized_line] * line_count) + "\n", encoding="utf-8")

    matches, truncated, error = _run_python_search_sync(
        workspace=tmp_path,
        pattern="needle",
        search_path=target,
        include_glob=None,
    )

    assert error is None
    assert truncated is True
    assert len(matches) == MAX_SEARCH_MATCHES
    total_bytes = sum(len(str(row["text"]).encode("utf-8")) for row in matches)
    # ~64 bytes of headroom per row for the "… [line truncated, N chars]" annotation.
    assert total_bytes <= MAX_SEARCH_MATCHES * (MAX_MATCH_LINE_CHARS + 64)
    assert total_bytes < line_count * len(oversized_line)


@pytest.mark.asyncio
async def test_rg_max_columns_is_ignored_under_json_so_clip_stays_python_side(
    tmp_path: Path,
) -> None:
    """``--max-columns`` is IGNORED under ``--json``, the mode this tool parses.

    Verified empirically with ripgrep 15.1.0: a 200,008-char line arrives at full length
    from ``rg --json`` both with and without ``--max-columns 400``. Swapping the
    Python-side clip for the ripgrep flag as an "optimization" would therefore silently
    reintroduce the multi-MB payload — this test fails if that swap is attempted.
    """
    rg_binary = shutil.which("rg")
    if rg_binary is None:
        pytest.skip("ripgrep (rg) not installed")

    raw_length = 200_008
    target = tmp_path / "huge.jsonl"
    target.write_text(f"{_needle_line(raw_length)}\n", encoding="utf-8")

    argv = _build_rg_argv(
        rg_binary=rg_binary,
        pattern="needle",
        search_path=target,
        include_glob=None,
    )
    assert "--json" in argv

    proc = await asyncio.create_subprocess_exec(
        rg_binary,
        "--max-columns",
        "400",
        *argv[1:],
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, _stderr_bytes = await proc.communicate()
    upstream_widths = [
        len(blob["data"]["lines"]["text"])
        for blob in (
            json.loads(row) for row in stdout_bytes.decode("utf-8").splitlines() if row.strip()
        )
        if blob.get("type") == "match"
    ]
    assert upstream_widths, "ripgrep produced no JSON match rows"
    assert max(upstream_widths) > MAX_MATCH_LINE_CHARS

    matches, _truncated, error = await _run_ripgrep(
        workspace=tmp_path,
        pattern="needle",
        search_path=target,
        include_glob=None,
        max_matches=MAX_SEARCH_MATCHES,
    )
    assert error is None
    assert len(str(matches[0]["text"])) < MAX_MATCH_LINE_CHARS + 64
