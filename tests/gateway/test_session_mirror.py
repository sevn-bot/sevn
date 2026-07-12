"""Workspace session JSONL mirror (`specs/17-gateway.md` §3.x)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.session_manager import SessionManager
from sevn.storage.migrate import apply_migrations


@pytest.mark.asyncio
async def test_mirror_appends_jsonl(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    ws = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    root = tmp_path / "workspace"
    root.mkdir()
    sm = SessionManager(conn, content_root=root, workspace=ws)
    sid = await sm.ensure_session(
        scope_key="telegram:12345:general",
        channel="telegram",
        user_id="999",
    )
    await sm.add_message(
        sid,
        role="user",
        kind="message",
        content="hello mirror",
        visible_to_llm=1,
        status="sent",
        turn_id="t-test",
    )
    jsonl = root / "sessions" / "telegram" / "chats" / "12345" / "general" / f"{sid}.jsonl"
    assert jsonl.is_file()
    line = json.loads(jsonl.read_text(encoding="utf-8").strip().splitlines()[0])
    assert line["content"] == "hello mirror"
    assert line["role"] == "user"
    index_path = root / "sessions" / "_index.json"
    assert index_path.is_file()
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert sid in index.get("sessions", {})
