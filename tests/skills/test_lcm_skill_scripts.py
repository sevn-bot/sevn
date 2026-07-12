"""Bundled ``lcm`` skill script subprocess tests."""

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
    / "lcm"
)
_SCRIPTS = _SKILL_ROOT / "scripts"


@pytest.fixture
def lcm_workspace(tmp_path: Path) -> tuple[Path, str, int]:
    """Temp workspace with one LCM conversation, message, and session summary."""
    dot_sevn = tmp_path / ".sevn"
    dot_sevn.mkdir(parents=True)
    conn = sqlite3.connect(str(sevn_db_path(dot_sevn)))
    apply_migrations(conn)
    now = "2026-05-12T00:00:00"
    conn.execute(
        """
        INSERT INTO lcm_conversations (
            session_key, channel, group_name, topic, created_at, updated_at
        ) VALUES ('web:s1', 'web', NULL, NULL, ?, ?)
        """,
        (now, now),
    )
    cid = int(conn.execute("SELECT id FROM lcm_conversations").fetchone()[0])
    conn.execute(
        """
        INSERT INTO lcm_messages (
            conversation_id, seq, role, content, kind, visible_to_llm, status, created_at
        ) VALUES (?, 1, 'user', 'We discussed caching strategy today', 'message', 1, 'sent', ?)
        """,
        (cid, now),
    )
    mid = int(conn.execute("SELECT id FROM lcm_messages").fetchone()[0])
    conn.execute(
        """
        INSERT INTO lcm_summaries (
            summary_id, conversation_id, content, depth, summary_kind, created_at
        ) VALUES ('sess-end-1', ?, 'Session covered caching and deployment', 0, 'session_end', ?)
        """,
        (cid, now),
    )
    conn.commit()
    conn.close()
    return tmp_path, "web:s1", mid


def _run_script(
    script_name: str,
    workspace: Path,
    *args: str,
) -> dict[str, object]:
    script = _SCRIPTS / script_name
    env = os.environ.copy()
    env["SEVN_WORKSPACE"] = str(workspace)
    proc = subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    payload = json.loads(proc.stdout.strip())
    assert payload.get("ok") is True
    return payload


def test_grep_script_finds_message(lcm_workspace: tuple[Path, str, int]) -> None:
    workspace, session_key, _mid = lcm_workspace
    payload = _run_script(
        "grep.py",
        workspace,
        "--query",
        "caching",
        "--session-key",
        session_key,
    )
    data = payload["data"]
    assert isinstance(data, dict)
    hits = data.get("hits")
    assert isinstance(hits, list)
    assert len(hits) >= 1
    assert "caching" in str(hits[0].get("excerpt", "")).lower()


def test_fetch_script_recent_tail(lcm_workspace: tuple[Path, str, int]) -> None:
    workspace, session_key, _mid = lcm_workspace
    payload = _run_script("fetch.py", workspace, "--session-key", session_key, "--limit", "5")
    data = payload["data"]
    assert isinstance(data, dict)
    messages = data.get("messages")
    assert isinstance(messages, list)
    assert len(messages) == 1
    assert "caching" in str(messages[0].get("content", "")).lower()


def test_fetch_script_single_message(lcm_workspace: tuple[Path, str, int]) -> None:
    workspace, _session_key, mid = lcm_workspace
    payload = _run_script("fetch.py", workspace, "--message-id", str(mid))
    data = payload["data"]
    assert isinstance(data, dict)
    message = data.get("message")
    assert isinstance(message, dict)
    assert message.get("message_id") == mid


def test_describe_and_expand_scripts(lcm_workspace: tuple[Path, str, int]) -> None:
    workspace, _session_key, mid = lcm_workspace
    describe = _run_script("describe.py", workspace, "--id", str(mid), "--kind", "message")
    assert describe["data"]["kind"] == "message"
    expand = _run_script("expand.py", workspace, "--summary-id", "sess-end-1")
    data = expand["data"]
    assert isinstance(data, dict)
    assert data["summary"]["summary_id"] == "sess-end-1"


def test_search_summaries_script(lcm_workspace: tuple[Path, str, int]) -> None:
    workspace, _session_key, _mid = lcm_workspace
    payload = _run_script(
        "search_summaries.py",
        workspace,
        "--query",
        "deployment",
        "--scope",
        "workspace",
    )
    data = payload["data"]
    assert isinstance(data, dict)
    hits = data.get("hits")
    assert isinstance(hits, list)
    assert len(hits) == 1


def test_list_and_meta_scripts(lcm_workspace: tuple[Path, str, int]) -> None:
    workspace, _session_key, _mid = lcm_workspace
    listed = _run_script("list_conversations.py", workspace, "--limit", "10")
    convs = listed["data"]["conversations"]
    assert len(convs) == 1
    cid = convs[0]["conversation_id"]
    meta = _run_script("conversations_meta.py", workspace, "--conversation-id", str(cid))
    rows = meta["data"]["conversations"]
    assert rows[0]["message_count"] == 1
    assert rows[0]["summary_count"] == 1


def test_expand_query_script(lcm_workspace: tuple[Path, str, int]) -> None:
    workspace, session_key, _mid = lcm_workspace
    payload = _run_script(
        "expand_query.py",
        workspace,
        "--query",
        "caching deploy",
        "--session-key",
        session_key,
    )
    data = payload["data"]
    assert isinstance(data, dict)
    assert "caching" in data.get("expanded_terms", [])
    assert len(data.get("hits", [])) >= 1


def test_status_script_reports_lcm_counts(lcm_workspace: tuple[Path, str, int]) -> None:
    workspace, _session_key, _mid = lcm_workspace
    payload = _run_script("status.py", workspace)
    data = payload["data"]
    assert isinstance(data, dict)
    assert data.get("status") == "ok"
    counts = data.get("counts")
    assert isinstance(counts, dict)
    assert counts.get("conversations") == 1
    assert counts.get("messages") == 1
