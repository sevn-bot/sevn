"""Bundled ``sessions_management`` skill script subprocess tests."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from sevn.storage.migrate import apply_migrations
from sevn.storage.paths import sevn_db_path

_SKILL_ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "sevn"
    / "data"
    / "bundled_skills"
    / "core"
    / "sessions_management"
)
_SCRIPTS = _SKILL_ROOT / "scripts"


@pytest.fixture
def sessions_workspace(tmp_path: Path) -> tuple[Path, str, str]:
    """Temp workspace with parent session, message, and child subagent."""
    dot_sevn = tmp_path / ".sevn"
    dot_sevn.mkdir(parents=True)
    conn = sqlite3.connect(str(sevn_db_path(dot_sevn)))
    apply_migrations(conn)
    now = "2026-05-12T00:00:00"
    parent_id = "a" * 32
    conn.execute(
        """
        INSERT INTO gateway_sessions (
            session_id, scope_key, channel, user_id, created_at, updated_at
        ) VALUES (?, 'web:owner', 'web', 'owner', ?, ?)
        """,
        (parent_id, now, now),
    )
    conn.execute(
        """
        INSERT INTO gateway_messages (
            session_id, role, kind, content, visible_to_llm, status, created_at
        ) VALUES (?, 'user', 'message', 'Plan the deployment rollout', 1, 'sent', ?)
        """,
        (parent_id, now),
    )
    child_id = "b" * 32
    meta = json.dumps(
        {"parent_session_id": parent_id, "session_type": "sub"},
        separators=(",", ":"),
    )
    conn.execute(
        """
        INSERT INTO gateway_sessions (
            session_id, scope_key, channel, user_id, created_at, updated_at, metadata_json
        ) VALUES (?, ?, 'internal', 'subagent-child', ?, ?, ?)
        """,
        (child_id, f"subagent:{child_id}", now, now, meta),
    )
    conn.commit()
    conn.close()
    return tmp_path, parent_id, child_id


def _run_script(
    script_name: str,
    workspace: Path,
    cli_args: list[str] | None = None,
    *,
    session_id: str | None = None,
) -> dict[str, object]:
    script = _SCRIPTS / script_name
    env = os.environ.copy()
    env["SEVN_WORKSPACE"] = str(workspace)
    if session_id:
        env["SEVN_SESSION_ID"] = session_id
    proc = subprocess.run(
        [sys.executable, str(script), *(cli_args or [])],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    payload = json.loads(proc.stdout.strip())
    assert payload.get("ok") is True
    return payload


def test_list_script_returns_parent_and_child(
    sessions_workspace: tuple[Path, str, str],
) -> None:
    workspace, parent_id, child_id = sessions_workspace
    payload = _run_script("list.py", workspace, session_id=parent_id)
    data = payload["data"]
    assert isinstance(data, dict)
    sessions = data.get("sessions")
    assert isinstance(sessions, list)
    ids = {str(row["session_id"]) for row in sessions}
    assert parent_id in ids
    assert child_id in ids


def test_history_script_fetches_messages(
    sessions_workspace: tuple[Path, str, str],
) -> None:
    workspace, parent_id, _child_id = sessions_workspace
    payload = _run_script(
        "history.py",
        workspace,
        cli_args=["--session-id", parent_id],
        session_id=parent_id,
    )
    data = payload["data"]
    assert isinstance(data, dict)
    messages = data.get("messages")
    assert isinstance(messages, list)
    assert len(messages) == 1
    assert "deployment" in str(messages[0].get("content", "")).lower()


def test_history_search_across_sessions(
    sessions_workspace: tuple[Path, str, str],
) -> None:
    workspace, parent_id, _child_id = sessions_workspace
    payload = _run_script(
        "history.py",
        workspace,
        cli_args=["--query", "deployment"],
        session_id=parent_id,
    )
    data = payload["data"]
    assert isinstance(data, dict)
    hits = data.get("hits")
    assert isinstance(hits, list)
    assert len(hits) >= 1


def test_send_script_appends_message(
    sessions_workspace: tuple[Path, str, str],
) -> None:
    workspace, parent_id, _child_id = sessions_workspace
    payload = _run_script(
        "send.py",
        workspace,
        cli_args=["--session-id", parent_id, "--text", "Follow up on staging"],
        session_id=parent_id,
    )
    data = payload["data"]
    assert isinstance(data, dict)
    assert data.get("message_id", 0) > 0
    history = _run_script(
        "history.py",
        workspace,
        cli_args=["--session-id", parent_id],
        session_id=parent_id,
    )
    bodies = [str(m.get("content", "")) for m in history["data"]["messages"]]
    assert any("staging" in b.lower() for b in bodies)


def test_spawn_script_creates_subagent(
    sessions_workspace: tuple[Path, str, str],
) -> None:
    workspace, parent_id, _child_id = sessions_workspace
    payload = _run_script(
        "spawn.py",
        workspace,
        cli_args=[
            "--parent-session-id",
            parent_id,
            "--system-prompt",
            "You are a research subagent.",
        ],
        session_id=parent_id,
    )
    data = payload["data"]
    assert isinstance(data, dict)
    new_id = str(data.get("session_id", ""))
    assert new_id
    assert data.get("parent_session_id") == parent_id
    listed = _run_script("list.py", workspace, session_id=parent_id)
    ids = {str(row["session_id"]) for row in listed["data"]["sessions"]}
    assert new_id in ids


def test_yield_and_status_scripts(
    sessions_workspace: tuple[Path, str, str],
) -> None:
    workspace, parent_id, child_id = sessions_workspace
    yielded = _run_script(
        "yield.py",
        workspace,
        cli_args=["--session-id", parent_id, "--reason", "handoff complete"],
        session_id=parent_id,
    )
    token = str(yielded["data"].get("yield_token", ""))
    assert token.startswith("YIELD:")
    status = _run_script(
        "status.py",
        workspace,
        cli_args=["--session-id", parent_id],
        session_id=parent_id,
    )
    snap = status["data"]
    assert isinstance(snap, dict)
    assert snap.get("yield") is not None
    assert child_id in snap.get("child_session_ids", [])


def test_legacy_sessions_alias(
    sessions_workspace: tuple[Path, str, str],
) -> None:
    workspace, parent_id, _child_id = sessions_workspace
    listed = _run_script(
        "sessions.py",
        workspace,
        cli_args=["--action", "list"],
        session_id=parent_id,
    )
    assert listed["data"]["count"] >= 2
    got = _run_script(
        "sessions.py",
        workspace,
        cli_args=["--action", "get", "--session-id", parent_id],
        session_id=parent_id,
    )
    assert len(got["data"]["messages"]) >= 1
