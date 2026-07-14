"""Tests for ``sevn turn-bundle export`` offline backfill (W2)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sevn.cli.app import app
from sevn.gateway.turn.turn_bundle import (
    export_turn_bundles,
    list_turn_export_candidates,
    load_turn_bundle_index,
    parse_since_timestamp,
    write_turn_bundle,
)
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout

TURN_A = "telegram:user=1:session=abc:msg=aaaa"
TURN_B = "telegram:user=1:session=abc:msg=bbbb"
SESSION_ID = "sess-1"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _seed_workspace(tmp_path: Path) -> tuple[sqlite3.Connection, WorkspaceLayout]:
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
    layout = WorkspaceLayout(sevn_json_path=sevn_json, content_root=tmp_path)
    layout.dot_sevn.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(layout.dot_sevn / "sevn.db")
    apply_migrations(conn)
    conn.execute(
        """
        INSERT INTO gateway_sessions (
            session_id, scope_key, channel, user_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            SESSION_ID,
            "telegram:1",
            "telegram",
            "1",
            "2026-06-15T00:00:00+00:00",
            "2026-06-16T00:00:00+00:00",
        ),
    )
    conn.execute(
        """
        INSERT INTO gateway_messages (
            session_id, turn_id, role, kind, content, status, created_at
        ) VALUES (?, ?, 'user', 'message', ?, 'sent', ?)
        """,
        (SESSION_ID, TURN_A, "older", "2026-06-15T10:00:00+00:00"),
    )
    conn.execute(
        """
        INSERT INTO gateway_messages (
            session_id, turn_id, role, kind, content, status, created_at
        ) VALUES (?, ?, 'user', 'message', ?, 'sent', ?)
        """,
        (SESSION_ID, TURN_B, "newer", "2026-06-16T10:00:00+00:00"),
    )
    conn.commit()
    return conn, layout


def test_parse_since_timestamp_date_only() -> None:
    assert parse_since_timestamp("2026-06-16") == "2026-06-16T00:00:00+00:00"


def test_list_turn_export_candidates_by_session(tmp_path: Path) -> None:
    conn, _layout = _seed_workspace(tmp_path)
    candidates = list_turn_export_candidates(conn, session_id=SESSION_ID)
    assert {c.turn_id for c in candidates} == {TURN_A, TURN_B}
    conn.close()


def test_list_turn_export_candidates_since_filter(tmp_path: Path) -> None:
    conn, _layout = _seed_workspace(tmp_path)
    candidates = list_turn_export_candidates(conn, since="2026-06-16")
    assert [c.turn_id for c in candidates] == [TURN_B]
    conn.close()


def test_export_turn_by_turn_id(tmp_path: Path) -> None:
    conn, layout = _seed_workspace(tmp_path)
    written = export_turn_bundles(
        conn,
        None,
        content_root=layout.content_root,
        turn_id=TURN_A,
    )
    assert len(written) == 1
    assert written[0].day_slug == "150626"
    assert written[0].bundle_path.is_file()
    assert written[0].bundles_dir == layout.turn_bundles_dir / "150626"
    index = load_turn_bundle_index(written[0].index_path)
    assert index["turns"][0]["turn_id"] == TURN_A
    conn.close()


def test_export_reexport_preserves_processed_flag(tmp_path: Path) -> None:
    conn, layout = _seed_workspace(tmp_path)
    paths = write_turn_bundle(
        conn,
        None,
        content_root=layout.content_root,
        session_id=SESSION_ID,
        turn_id=TURN_A,
        terminal_status="ok",
    )
    index = load_turn_bundle_index(paths.index_path)
    index["turns"][0]["processed"] = True
    paths.index_path.write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    export_turn_bundles(
        conn,
        None,
        content_root=layout.content_root,
        turn_id=TURN_A,
    )
    index = load_turn_bundle_index(paths.index_path)
    assert index["turns"][0]["processed"] is True
    conn.close()


def test_turn_bundle_export_cli_by_session(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["turn-bundle", "export", "--session", SESSION_ID])
    assert result.exit_code == 0
    assert TURN_A in result.stdout
    assert TURN_B in result.stdout


def test_turn_bundle_export_cli_requires_selector(runner: CliRunner, tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps({"schema_version": 1, "content_root": str(tmp_path), "gateway": {"token": "t"}}),
        encoding="utf-8",
    )
    with runner.isolated_filesystem(temp_dir=tmp_path):
        sevn_json.write_text(
            json.dumps(
                {"schema_version": 1, "content_root": str(tmp_path), "gateway": {"token": "t"}},
            ),
            encoding="utf-8",
        )
        result = runner.invoke(app, ["turn-bundle", "export"])
    assert result.exit_code == 2
    assert "at least one" in result.stderr.lower()
