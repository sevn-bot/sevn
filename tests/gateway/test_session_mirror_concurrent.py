"""Concurrent JSONL mirror appends (`specs/17-gateway.md` §3.1 durability)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.session.session_mirror import mirror_gateway_message


@pytest.mark.asyncio
async def test_mirror_concurrent_appends_valid_jsonl(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    ws = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    session_id = "sess-concurrent"
    scope_key = "telegram:12345:general"

    async def _append(i: int) -> None:
        await asyncio.to_thread(
            mirror_gateway_message,
            content_root=root,
            workspace=ws,
            message_id=i,
            session_id=session_id,
            scope_key=scope_key,
            channel="telegram",
            user_id="999",
            role="user",
            kind="message",
            content=f"line-{i}",
            visible_to_llm=1,
            status="sent",
            created_at="2026-05-27T12:00:00",
            extras_json=None,
            turn_id="t-concurrent",
        )

    await asyncio.gather(*(_append(i) for i in range(32)))

    jsonl = root / "sessions" / "telegram" / "chats" / "12345" / "general" / f"{session_id}.jsonl"
    assert jsonl.is_file()
    lines = jsonl.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 32
    payloads = [json.loads(line) for line in lines]
    contents = {p["content"] for p in payloads}
    assert contents == {f"line-{i}" for i in range(32)}
