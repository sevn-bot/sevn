"""Tests for ``sevn turn-bundle view`` explorer (W3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sevn.cli.app import app
from sevn.gateway.turn_bundle import (
    TurnBundleIndexEntry,
    TurnBundleLogRecord,
    TurnBundleMessageRecord,
    TurnBundleMetaRecord,
    TurnBundleTraceRecord,
    bundle_paths,
    upsert_turn_bundle_index_entry,
    view_turn_bundle,
)
from sevn.workspace.layout import WorkspaceLayout

TURN_ID = "telegram:user=1:session=abc:msg=deadbeef"
SESSION_ID = "sess-1"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _layout(tmp_path: Path) -> WorkspaceLayout:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "content_root": str(tmp_path),
                "gateway": {"token": "t"},
            },
        ),
        encoding="utf-8",
    )
    return WorkspaceLayout(sevn_json_path=sevn_json, content_root=tmp_path)


def _seed_indexed_bundle(
    layout: WorkspaceLayout,
    *,
    terminal_status: str = "ok",
    has_error: bool = False,
) -> None:
    paths = bundle_paths(layout.content_root, TURN_ID, first_seen_at="2026-06-16T00:00:00+00:00")
    paths.bundles_dir.mkdir(parents=True, exist_ok=True)
    meta = TurnBundleMetaRecord(
        stream="meta",
        turn_id=TURN_ID,
        session_id=SESSION_ID,
        channel="telegram",
        terminal_status=terminal_status,
        created_at="2026-06-16T00:00:00+00:00",
    )
    records = [
        meta,
        TurnBundleMessageRecord(
            stream="message",
            ts="2026-06-16T00:00:01+00:00",
            id="1",
            role="user",
            kind="message",
            content="hello",
            status="sent",
        ),
        TurnBundleLogRecord(
            stream="log",
            ts="2026-06-16T00:00:02+00:00",
            level="INFO",
            message="all good",
            location="path:1 fn",
        ),
        TurnBundleLogRecord(
            stream="log",
            ts="2026-06-16T00:00:03+00:00",
            level="ERROR",
            message="executor_no_answer tier=B",
            location="path:2 fn",
        ),
        TurnBundleTraceRecord(
            stream="trace",
            ts="2026-06-16T00:00:04+00:00",
            span_id="span-ok",
            kind="b_turn",
            status="ok",
            ts_start_ns=1,
            attrs={},
        ),
        TurnBundleTraceRecord(
            stream="trace",
            ts="2026-06-16T00:00:05+00:00",
            span_id="span-bad",
            kind="b_turn",
            status="failed",
            ts_start_ns=2,
            attrs={},
        ),
    ]
    lines = [json.dumps(record, separators=(",", ":"), sort_keys=True) for record in records]
    paths.bundle_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    upsert_turn_bundle_index_entry(
        paths.index_path,
        TurnBundleIndexEntry(
            turn_id=TURN_ID,
            file=paths.bundle_path.name,
            session_id=SESSION_ID,
            channel="telegram",
            terminal_status=terminal_status,
            has_error=has_error,
            processed=False,
            created_at=meta["created_at"],
        ),
    )


def test_view_turn_bundle_section_meta(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    _seed_indexed_bundle(layout)
    lines = view_turn_bundle(layout.content_root, TURN_ID, section="meta")
    assert len(lines) == 1
    assert lines[0].startswith("[meta]")
    assert TURN_ID in lines[0]


def test_view_turn_bundle_section_summary(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    _seed_indexed_bundle(layout, has_error=True)
    lines = view_turn_bundle(layout.content_root, TURN_ID, section="summary")
    text = "\n".join(lines)
    assert "log_lines: 2" in text
    assert "error_log_lines: 1" in text
    assert "error_trace_lines: 1" in text
    assert "has_error: true" in text


def test_view_turn_bundle_stream_filter(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    _seed_indexed_bundle(layout)
    lines = view_turn_bundle(layout.content_root, TURN_ID, stream="log")
    assert len(lines) == 2
    assert all(line.startswith("[log]") for line in lines)


def test_view_turn_bundle_grep_filter(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    _seed_indexed_bundle(layout)
    lines = view_turn_bundle(layout.content_root, TURN_ID, grep="executor_no_answer")
    assert len(lines) == 1
    assert "executor_no_answer" in lines[0]


def test_view_turn_bundle_errors_only(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    _seed_indexed_bundle(layout)
    lines = view_turn_bundle(layout.content_root, TURN_ID, errors_only=True)
    assert len(lines) == 2
    assert any("level=ERROR" in line for line in lines)
    assert any("status=failed" in line for line in lines)


def test_view_turn_bundle_missing_turn(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    with pytest.raises(ValueError, match="No turn bundle indexed"):
        view_turn_bundle(layout.content_root, TURN_ID)


def test_turn_bundle_view_cli_meta(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = _layout(tmp_path)
    _seed_indexed_bundle(layout)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["turn-bundle", "view", TURN_ID, "--section", "meta"])
    assert result.exit_code == 0
    assert "[meta]" in result.stdout


def test_turn_bundle_view_cli_missing_turn(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _layout(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["turn-bundle", "view", TURN_ID])
    assert result.exit_code == 2
    assert "No turn bundle indexed" in result.stderr


def test_turn_bundle_view_cli_errors_only(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = _layout(tmp_path)
    _seed_indexed_bundle(layout)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["turn-bundle", "view", TURN_ID, "--errors-only"])
    assert result.exit_code == 0
    assert "level=ERROR" in result.stdout
    assert "all good" not in result.stdout
