"""W17.7 — session export with redaction (#83 → W22)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sevn.cli.app import app
from tests.open_issues_sweep.batch_d.conftest import seed_bound_workspace, seed_gateway_session


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _seed_messages(conn: sqlite3.Connection) -> None:
    seed_gateway_session(conn, session_id="sess-export", channel="telegram", user_id="7")
    conn.execute(
        """
        INSERT INTO gateway_messages(
            session_id, role, kind, content, visible_to_llm, status, created_at, turn_id
        ) VALUES ('sess-export', 'user', 'message', 'hello', 1, 'sent', '2026-07-01T10:00:00+00:00', '-')
        """,
    )
    conn.execute(
        """
        INSERT INTO gateway_messages(
            session_id, role, kind, content, visible_to_llm, status, created_at, turn_id
        ) VALUES (
            'sess-export', 'assistant', 'message',
            'reply with secret sk-ant-api03-abc123xyz', 1, 'sent', '2026-07-01T10:00:01+00:00', '-'
        )
        """,
    )
    conn.commit()


def test_sessions_export_command_registered(runner: CliRunner) -> None:
    """CLI exposes ``sevn sessions export`` beside list/history."""
    result = runner.invoke(app, ["sessions", "export", "--help"])
    assert result.exit_code == 0
    assert "markdown" in result.stdout.lower() or "--format" in result.stdout


def test_sessions_export_writes_markdown_and_jsonl(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Export produces markdown and JSONL artifacts for one session."""
    conn, workspace_root = seed_bound_workspace(tmp_path)
    _seed_messages(conn)
    conn.close()
    monkeypatch.chdir(workspace_root)

    out_dir = tmp_path / "exports"
    result = runner.invoke(
        app,
        [
            "sessions",
            "export",
            "--session",
            "sess-export",
            "--format",
            "markdown,jsonl",
            "--output",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0
    md_files = list(out_dir.glob("*.md"))
    jsonl_files = list(out_dir.glob("*.jsonl"))
    assert md_files
    assert jsonl_files


def test_sessions_export_honors_channel_and_since_until_filters(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Filters: channel/profile/session and since/until window."""
    conn, workspace_root = seed_bound_workspace(tmp_path)
    seed_gateway_session(conn, session_id="sess-other", channel="webui", user_id="1")
    _seed_messages(conn)
    conn.execute(
        """
        INSERT INTO gateway_messages(
            session_id, role, kind, content, visible_to_llm, status, created_at, turn_id
        ) VALUES ('sess-other', 'user', 'message', 'exclude-me', 1, 'sent', '2026-06-01T00:00:00+00:00', '-')
        """,
    )
    conn.commit()
    conn.close()
    monkeypatch.chdir(workspace_root)

    from sevn.cli.commands.sessions import export_sessions

    payload = export_sessions(
        channel="telegram",
        session_id="sess-export",
        since="2026-07-01",
        until="2026-07-02",
        fmt="jsonl",
    )
    assert "exclude-me" not in payload
    assert "hello" in payload


def test_sessions_export_redacts_secrets_and_sensitive_tool_payloads(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Secrets, tokens, and sensitive tool payloads are stripped from export."""
    conn, workspace_root = seed_bound_workspace(tmp_path)
    _seed_messages(conn)
    conn.execute(
        """
        INSERT INTO gateway_messages(
            session_id, role, kind, content, visible_to_llm, status, created_at,
            turn_id, extras_json
        ) VALUES (
            'sess-export', 'assistant', 'message', 'tool output', 1, 'sent',
            '2026-07-01T10:00:02+00:00', '-',
            ?
        )
        """,
        (
            json.dumps(
                {
                    "tool_name": "secrets_get",
                    "payload": {"token": "ghp_supersecret", "api_key": "sk-live-bad"},
                },
            ),
        ),
    )
    conn.commit()
    conn.close()
    monkeypatch.chdir(workspace_root)

    from sevn.cli.commands.sessions import export_sessions

    exported = export_sessions(session_id="sess-export", fmt="jsonl")
    assert "sk-ant-api03-abc123xyz" not in exported
    assert "ghp_supersecret" not in exported
    assert "sk-live-bad" not in exported
    assert "[REDACTED]" in exported or "***" in exported
