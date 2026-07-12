"""``sevn logs`` unified command tests (W5)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path

import pytest
from click.testing import CliRunner as ClickCliRunner
from typer.main import get_command

from sevn.agent.tracing.traces_migrate import apply_traces_migrations
from sevn.cli.app import app
from sevn.cli.log_follow import (
    build_logs_insight_summary,
    collect_merged_log_entries,
    parse_log_level,
    run_unified_logs,
)
from sevn.cli.log_redact import redact_log_line


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
    logs = ws / "logs"
    logs.mkdir()
    dot_sevn = ws / ".sevn"
    dot_sevn.mkdir()
    return home


def _ts(offset_seconds: float) -> str:
    """Return a UTC log timestamp within the default 24h ``--since`` window."""
    stamp = datetime.now(UTC) - timedelta(hours=1) + timedelta(seconds=offset_seconds)
    return stamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + "+00:00"


def _rotated_log_name(service: str, *, offset_hours: float = 2.0) -> str:
    """Return a rotated ``gateway``/``proxy`` log filename within the 7d window."""
    stamp = datetime.now(UTC) - timedelta(hours=offset_hours)
    return f"{service}-{stamp.strftime('%Y%m%dT%H%M%S')}Z.log"


def _write_fixture_logs(home: Path) -> None:
    logs = home / "workspace" / "logs"
    logs.joinpath("gateway.log").write_text(
        "\n".join(
            [
                f"{_ts(0.0)} | INFO | - | - | gw early",
                f"{_ts(2.0)} | ERROR | - | - | timeout id=12345",
                f"{_ts(3.0)} | ERROR | - | - | timeout id=67890",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    logs.joinpath("proxy.log").write_text(
        f"{_ts(1.0)} | WARNING | - | - | proxy warn\n",
        encoding="utf-8",
    )
    logs.joinpath("cli.log").write_text(
        f"{_ts(1.5)} | INFO | [cli] | invoke sevn logs\n",
        encoding="utf-8",
    )
    logs.joinpath("agent.log").write_text(
        f"{_ts(1.25)} | DEBUG | [agent] | tier-b start\n",
        encoding="utf-8",
    )
    logs.joinpath(_rotated_log_name("gateway")).write_text("rotated\n", encoding="utf-8")


def test_collect_merged_log_entries_orders_by_timestamp(bound_home: Path) -> None:
    _write_fixture_logs(bound_home)
    logs = bound_home / "workspace" / "logs"
    paths = {
        "gateway": logs / "gateway.log",
        "proxy": logs / "proxy.log",
        "cli": logs / "cli.log",
        "agent": logs / "agent.log",
    }
    entries = collect_merged_log_entries(paths, lines=20, since="7d")
    sources = [entry.source for entry in entries]
    assert sources == ["gateway", "proxy", "agent", "cli", "gateway", "gateway"]


def test_level_and_grep_filters(bound_home: Path) -> None:
    _write_fixture_logs(bound_home)
    logs = bound_home / "workspace" / "logs"
    paths = {"gateway": logs / "gateway.log"}
    entries = collect_merged_log_entries(paths, lines=20, since="7d", level="ERROR", grep="timeout")
    assert len(entries) == 2
    assert all(entry.level == "ERROR" for entry in entries)


def test_redaction_holds_in_merged_output(bound_home: Path) -> None:
    logs = bound_home / "workspace" / "logs"
    secret = "token=supersecret1234567890abcdef"
    logs.joinpath("gateway.log").write_text(
        f"{_ts(0.0)} | ERROR | - | - | {secret}\n",
        encoding="utf-8",
    )
    entries = collect_merged_log_entries({"gateway": logs / "gateway.log"}, lines=5, since="7d")
    assert entries
    assert "supersecret" not in entries[0].display_line
    assert redact_log_line(secret) in entries[0].display_line


def test_build_insight_summary_counts(bound_home: Path) -> None:
    _write_fixture_logs(bound_home)
    logs = bound_home / "workspace" / "logs"
    paths = {
        "gateway": logs / "gateway.log",
        "proxy": logs / "proxy.log",
        "cli": logs / "cli.log",
        "agent": logs / "agent.log",
    }
    entries = collect_merged_log_entries(paths, lines=50, since="7d")
    summary = build_logs_insight_summary(
        entries,
        logs_dir=logs,
        dot_sevn=bound_home / "workspace" / ".sevn",
        since="7d",
    )
    assert summary["error_count"] == 2
    assert summary["warning_count"] == 1
    assert summary["top_error_signatures"]
    assert summary["recent_restarts"]


def test_insight_summary_reads_traces_db(bound_home: Path) -> None:
    import sqlite3
    import time

    dot_sevn = bound_home / "workspace" / ".sevn"
    db_path = dot_sevn / "traces.db"
    now_ns = time.time_ns()
    hour_ns = now_ns - (now_ns % (3_600 * 1_000_000_000))
    conn = sqlite3.connect(db_path)
    apply_traces_migrations(conn)
    conn.execute(
        """
        INSERT INTO trace_events (
            span_id, parent_span_id, session_id, turn_id, tier, kind,
            ts_start_ns, ts_end_ns, status, attrs_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "span-1",
            None,
            "sess-abcdef",
            "turn-1",
            "B",
            "tool.read",
            now_ns - 5_000_000_000,
            now_ns,
            "ERROR",
            "{}",
        ),
    )
    conn.execute(
        """
        INSERT INTO trace_rollups_hourly (
            hour_bucket_ns, kind, event_count, error_count,
            avg_duration_ns, max_duration_ns, updated_at_ns
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (hour_ns, "tool.read", 3, 2, 2_000_000_000.0, 5_000_000_000, now_ns),
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
    assert summary["top_error_kinds"][0]["kind"] == "tool.read"


def test_logs_json_shape(runner: ClickCliRunner, bound_home: Path) -> None:
    _write_fixture_logs(bound_home)
    result = runner.invoke(
        get_command(app),
        ["logs", "--json", "-n", "3", "--no-summary"],
        env={"SEVN_HOME": str(bound_home)},
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "sevn logs"
    assert "lines" in payload["data"]
    assert len(payload["data"]["lines"]) == 3


def test_logs_plain_non_tty(runner: ClickCliRunner, bound_home: Path) -> None:
    _write_fixture_logs(bound_home)
    result = runner.invoke(
        get_command(app),
        ["logs", "--source", "gateway", "-n", "5", "--no-summary"],
        env={"SEVN_HOME": str(bound_home)},
    )
    assert result.exit_code == 0
    assert "gw early" in result.stdout
    assert "\x1b[" not in result.stdout


def test_logs_insight_header_plain(runner: ClickCliRunner, bound_home: Path) -> None:
    _write_fixture_logs(bound_home)
    result = runner.invoke(
        get_command(app),
        ["logs", "--source", "gateway", "-n", "5"],
        env={"SEVN_HOME": str(bound_home), "NO_COLOR": "1"},
    )
    assert result.exit_code == 0
    assert "Insight" in result.stdout
    assert "errors" in result.stdout


def test_logs_follow_json_rejected(runner: ClickCliRunner, bound_home: Path) -> None:
    _write_fixture_logs(bound_home)
    result = runner.invoke(
        get_command(app),
        ["logs", "--json", "--follow"],
        env={"SEVN_HOME": str(bound_home)},
    )
    assert result.exit_code == 2


def test_gateway_logs_preset_delegates(runner: ClickCliRunner, bound_home: Path) -> None:
    _write_fixture_logs(bound_home)
    result = runner.invoke(
        get_command(app),
        ["gateway", "logs", "--no-follow", "-n", "5"],
        env={"SEVN_HOME": str(bound_home)},
    )
    assert result.exit_code == 0
    assert "gw early" in result.stdout


def test_parse_log_level_defaults() -> None:
    assert parse_log_level("plain") == "INFO"
    assert parse_log_level("2026-06-17 | WARNING | x") == "WARN"


def test_run_unified_logs_json_stream(bound_home: Path) -> None:
    _write_fixture_logs(bound_home)
    buf = StringIO()
    run_unified_logs(
        source="all",
        lines=2,
        follow=False,
        json_mode=True,
        include_summary=True,
        operator_home=bound_home,
        json_stream=buf,
    )
    payload = json.loads(buf.getvalue())
    assert payload["data"]["summary"]["error_count"] == 2
    assert len(payload["data"]["lines"]) == 2
