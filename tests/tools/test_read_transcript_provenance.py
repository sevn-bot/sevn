"""read_transcript provenance fields (tools_attempted, successful_tools, sources, turn_id)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sevn.agent.provider_history_keys import SUCCESSFUL_TOOLS_KEY
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.transcript import read_transcript_tool


@pytest.fixture
def transcript_workspace(tmp_path: Path) -> tuple[Path, str]:
    """Workspace with session JSONL containing provider_turn_messages extras."""
    root = tmp_path / "ws"
    sessions = root / "sessions" / "webchat" / "users" / "u1"
    sessions.mkdir(parents=True)
    session_id = "a" * 32
    jsonl_name = f"{session_id}.jsonl"
    jsonl_path = sessions / jsonl_name
    provider_messages = [
        {"role": "user", "content": "Wemby stats in finals?"},
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "t0", "name": "web_search", "input": {}},
                {"type": "tool_use", "id": "t1", "name": "serp", "input": {}},
                {"type": "tool_use", "id": "t2", "name": "get_page_content", "input": {}},
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "t0",
                    "content": '{"ok": false, "error": "no brave key"}',
                },
                {
                    "type": "tool_result",
                    "tool_use_id": "t1",
                    "content": '{"ok": true, "data": {"query": "wemby"}}',
                },
                {
                    "type": "tool_result",
                    "tool_use_id": "t2",
                    "content": '{"ok": true, "data": {"url": "https://www.nba.com/finals"}}',
                },
            ],
        },
        {"role": "assistant", "content": "Game 4: Knicks 107, Spurs 106."},
    ]
    records = [
        {
            "id": 1,
            "ts": "2026-06-11T14:00:00",
            "role": "user",
            "kind": "message",
            "content": "Wemby stats in finals?",
            "turn_id": "turn-audit-target",
        },
        {
            "id": 2,
            "ts": "2026-06-11T14:01:00",
            "role": "assistant",
            "kind": "message",
            "content": "Game 4: Knicks 107, Spurs 106.",
            "turn_id": "turn-audit-target",
            "extras": {"provider_turn_messages": provider_messages},
        },
    ]
    jsonl_path.write_text(
        "\n".join(json.dumps(row) for row in records) + "\n",
        encoding="utf-8",
    )
    index = {
        "sessions": {
            session_id: {"jsonl": f"webchat/users/u1/{jsonl_name}"},
        },
    }
    (root / "sessions" / "_index.json").write_text(json.dumps(index), encoding="utf-8")
    (root / ".sevn").mkdir()
    return root, session_id


@pytest.fixture
def ctx(transcript_workspace: tuple[Path, str]) -> ToolContext:
    workspace, session_id = transcript_workspace
    return ToolContext(
        session_id=session_id,
        workspace_path=workspace,
        workspace_id="prov-wid",
        registry_version=1,
        permissions=AllowAllPermissionPolicy(),
    )


@pytest.mark.asyncio
async def test_read_transcript_splits_attempted_and_successful_tools(
    ctx: ToolContext,
) -> None:
    raw = await read_transcript_tool(ctx, role="assistant", limit=5, full=True)
    data = json.loads(raw)
    assert data["ok"] is True
    turns = data["data"]["turns"]
    assert len(turns) == 1
    row = turns[0]
    assert row["turn_id"] == "turn-audit-target"
    assert row["tools_attempted"] == ["web_search", "serp", "get_page_content"]
    assert row["successful_tools"] == ["serp", "get_page_content"]
    assert "web_search" not in row["successful_tools"]
    assert "https://www.nba.com/finals" in row["sources"]


@pytest.mark.asyncio
async def test_read_transcript_prefers_persisted_successful_tools(
    ctx: ToolContext,
    transcript_workspace: tuple[Path, str],
) -> None:
    workspace, session_id = transcript_workspace
    jsonl_rel = f"webchat/users/u1/{session_id}.jsonl"
    jsonl_path = workspace / "sessions" / jsonl_rel
    lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[1])
    row["extras"][SUCCESSFUL_TOOLS_KEY] = ["serp"]
    lines[1] = json.dumps(row)
    jsonl_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    raw = await read_transcript_tool(ctx, role="assistant", limit=5, full=True)
    data = json.loads(raw)
    row = data["data"]["turns"][0]
    assert row["successful_tools"] == ["serp"]


@pytest.fixture
def dated_transcript(tmp_path: Path) -> tuple[Path, str]:
    """Workspace whose session JSONL spans two UTC days (local-offset ts)."""
    root = tmp_path / "ws"
    sessions = root / "sessions" / "webchat" / "users" / "u1"
    sessions.mkdir(parents=True)
    session_id = "b" * 32
    jsonl_name = f"{session_id}.jsonl"
    records = [
        {
            "id": 1,
            "ts": "2026-07-02T12:00:00+00:00",
            "role": "user",
            "kind": "message",
            "content": "yesterday-turn",
        },
        {
            "id": 2,
            "ts": "2026-07-03T09:00:00+00:00",
            "role": "user",
            "kind": "message",
            "content": "today-turn",
        },
    ]
    (sessions / jsonl_name).write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )
    index = {"sessions": {session_id: {"jsonl": f"webchat/users/u1/{jsonl_name}"}}}
    (root / "sessions" / "_index.json").write_text(json.dumps(index), encoding="utf-8")
    (root / ".sevn").mkdir()
    return root, session_id


@pytest.mark.asyncio
async def test_read_transcript_since_until_filters_turns(
    dated_transcript: tuple[Path, str],
) -> None:
    workspace, session_id = dated_transcript
    ctx = ToolContext(
        session_id=session_id,
        workspace_path=workspace,
        workspace_id="wid",
        registry_version=1,
        permissions=AllowAllPermissionPolicy(),
    )
    raw = await read_transcript_tool(ctx, since="2026-07-02", until="2026-07-02")
    data = json.loads(raw)["data"]
    assert [t["content"] for t in data["turns"]] == ["yesterday-turn"]
    assert data["since"] == "2026-07-02T00:00:00"


@pytest.mark.asyncio
async def test_read_transcript_bad_when_is_validation_error(
    dated_transcript: tuple[Path, str],
) -> None:
    workspace, session_id = dated_transcript
    ctx = ToolContext(
        session_id=session_id,
        workspace_path=workspace,
        workspace_id="wid",
        registry_version=1,
        permissions=AllowAllPermissionPolicy(),
    )
    raw = await read_transcript_tool(ctx, when="someday")
    envelope = json.loads(raw)
    assert envelope["ok"] is False
    assert "unknown relative range" in envelope["error"]
