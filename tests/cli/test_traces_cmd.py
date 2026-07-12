"""``sevn traces`` span-grouped command tests (W6)."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest
from click.testing import CliRunner as ClickCliRunner
from typer.main import get_command

from sevn.agent.tracing.traces_migrate import apply_traces_migrations
from sevn.cli.app import app
from sevn.cli.log_follow import build_logs_insight_summary, render_logs_insight_summary
from sevn.cli.render.console import configure_render
from sevn.cli.traces_read import load_trace_turns, turn_to_span_tree_node


@pytest.fixture
def runner() -> ClickCliRunner:
    return ClickCliRunner()


@pytest.fixture
def bound_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    ws = home / "workspace"
    ws.mkdir(parents=True)
    (ws / "sevn.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )
    (ws / ".sevn").mkdir()
    return home


def _insert_span(
    conn: sqlite3.Connection,
    *,
    span_id: str,
    parent_span_id: str | None,
    session_id: str = "sess-trace-a",
    turn_id: str = "turn-1",
    kind: str = "b_turn",
    ts_start_ns: int,
    ts_end_ns: int | None = None,
    status: str = "ok",
    attrs: dict[str, object] | None = None,
) -> None:
    conn.execute(
        """INSERT INTO trace_events (
            span_id, parent_span_id, session_id, turn_id, tier, kind,
            ts_start_ns, ts_end_ns, status, attrs_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            span_id,
            parent_span_id,
            session_id,
            turn_id,
            "B",
            kind,
            ts_start_ns,
            ts_end_ns,
            status,
            json.dumps(attrs or {}),
        ),
    )


def _seed_trace_tree(dot_sevn: Path) -> None:
    now_ns = time.time_ns()
    conn = sqlite3.connect(dot_sevn / "traces.db")
    apply_traces_migrations(conn)
    _insert_span(
        conn,
        span_id="root",
        parent_span_id=None,
        kind="triage.start",
        ts_start_ns=now_ns - 300_000_000,
        ts_end_ns=now_ns - 100_000_000,
    )
    _insert_span(
        conn,
        span_id="child",
        parent_span_id="root",
        kind="tool.invoke",
        ts_start_ns=now_ns - 250_000_000,
        ts_end_ns=now_ns - 150_000_000,
        attrs={"tool_name": "read_file"},
    )
    _insert_span(
        conn,
        span_id="turn-2-root",
        parent_span_id=None,
        session_id="sess-trace-a",
        turn_id="turn-2",
        kind="b_turn",
        ts_start_ns=now_ns - 50_000_000,
        ts_end_ns=now_ns,
        status="ERROR",
    )
    _insert_span(
        conn,
        span_id="other-session",
        parent_span_id=None,
        session_id="sess-trace-b",
        turn_id="turn-1",
        kind="gateway.boot",
        ts_start_ns=now_ns - 10_000_000,
        ts_end_ns=now_ns - 5_000_000,
    )
    conn.commit()
    conn.close()


def test_load_trace_turns_groups_span_tree(bound_home: Path) -> None:
    dot_sevn = bound_home / "workspace" / ".sevn"
    _seed_trace_tree(dot_sevn)
    turns = load_trace_turns(dot_sevn, session_id="sess-trace-a", last=10, since="30d")
    assert len(turns) == 2
    turn_ids = {turn["turn_id"] for turn in turns}
    assert turn_ids == {"turn-1", "turn-2"}
    turn_one = next(turn for turn in turns if turn["turn_id"] == "turn-1")
    assert turn_one["spans"]
    root = turn_one["spans"][0]
    assert root["kind"] == "triage.start"
    assert root["children"][0]["kind"] == "tool.invoke"
    assert turn_one["spans"][0]["children"][0]["attrs"]["tool_name"] == "read_file"


def test_load_trace_turns_last_limits(bound_home: Path) -> None:
    dot_sevn = bound_home / "workspace" / ".sevn"
    _seed_trace_tree(dot_sevn)
    turns = load_trace_turns(dot_sevn, session_id="sess-trace-a", last=1, since="30d")
    assert len(turns) == 1
    assert turns[0]["turn_id"] == "turn-2"


def test_turn_to_span_tree_node_plain(bound_home: Path) -> None:
    dot_sevn = bound_home / "workspace" / ".sevn"
    _seed_trace_tree(dot_sevn)
    turns = load_trace_turns(dot_sevn, session_id="sess-trace-a", last=10, since="30d")
    turn_one = next(turn for turn in turns if turn["turn_id"] == "turn-1")
    node = turn_to_span_tree_node(turn_one)
    assert "tool.invoke" in node.children[0].children[0].label


def test_traces_json_shape(runner: ClickCliRunner, bound_home: Path) -> None:
    _seed_trace_tree(bound_home / "workspace" / ".sevn")
    result = runner.invoke(
        get_command(app),
        ["traces", "--json", "--session", "sess-trace-a", "--last", "2"],
        env={"SEVN_HOME": str(bound_home)},
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "sevn traces"
    assert payload["data"]["count"] == 2
    assert payload["data"]["turns"][0]["spans"]


def test_traces_session_filter(runner: ClickCliRunner, bound_home: Path) -> None:
    _seed_trace_tree(bound_home / "workspace" / ".sevn")
    result = runner.invoke(
        get_command(app),
        ["traces", "--json", "--session", "sess-trace-b"],
        env={"SEVN_HOME": str(bound_home)},
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["data"]["count"] == 1
    assert payload["data"]["turns"][0]["session_id"] == "sess-trace-b"


def test_traces_plain_fallback(runner: ClickCliRunner, bound_home: Path) -> None:
    _seed_trace_tree(bound_home / "workspace" / ".sevn")
    result = runner.invoke(
        get_command(app),
        ["traces", "--session", "sess-trace-a", "--last", "1"],
        env={"SEVN_HOME": str(bound_home), "NO_COLOR": "1"},
    )
    assert result.exit_code == 0
    assert "b_turn" in result.stdout or "tool.invoke" in result.stdout


def test_insight_summary_includes_traces_drilldown(bound_home: Path) -> None:
    from unittest.mock import patch

    dot_sevn = bound_home / "workspace" / ".sevn"
    now_ns = time.time_ns()
    conn = sqlite3.connect(dot_sevn / "traces.db")
    apply_traces_migrations(conn)
    _insert_span(
        conn,
        span_id="slow",
        parent_span_id=None,
        session_id="sess-drill-xyz",
        kind="tool.read",
        ts_start_ns=now_ns - 8_000_000_000,
        ts_end_ns=now_ns,
        status="ERROR",
    )
    conn.commit()
    conn.close()

    summary = build_logs_insight_summary(
        [],
        logs_dir=bound_home / "workspace" / "logs",
        dot_sevn=dot_sevn,
        since="30d",
    )
    assert summary["slowest_spans"]
    configure_render(json_mode=False, force_plain=True)
    lines: list[str] = []

    def _capture(msg: str, *, err: bool = False) -> None:
        lines.append(msg)

    with patch("sevn.cli.log_follow.plain_echo", side_effect=_capture):
        render_logs_insight_summary(summary)
    text = "\n".join(lines)
    assert "sevn traces --session sess-drill-xyz" in text
