"""RED suite for ``read_transcript`` crash regression (D10; green after W4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.transcript import read_transcript_tool

_XFAIL_W4 = pytest.mark.xfail(
    reason="green after W4: read_transcript int.get crash (D10)",
    strict=False,
)


def _tool_heavy_provider_messages(*, tool_count: int = 12) -> list[dict[str, object]]:
    """Build provider_turn_messages dense enough to exercise provenance compaction."""
    tool_uses = [
        {"type": "tool_use", "id": f"t{i}", "name": f"tool_{i}", "input": {"n": i}}
        for i in range(tool_count)
    ]
    tool_results = []
    for i in range(tool_count):
        # Mix envelope shapes — bare JSON ints reproduce `'int' object has no attribute 'get'`
        # in `_tool_result_succeeded` (D10 live crash).
        if i % 4 == 0:
            content: object = "42"
        elif i % 4 == 1:
            content = json.dumps({"ok": True, "data": {"i": i, "url": f"https://ex.test/{i}"}})
        elif i % 4 == 2:
            content = "null"
        else:
            content = json.dumps([{"ok": True}])
        tool_results.append(
            {
                "type": "tool_result",
                "tool_use_id": f"t{i}",
                "content": content,
            }
        )
    return [
        {"role": "user", "content": "audit tools used recently"},
        {"role": "assistant", "content": tool_uses},
        {"role": "user", "content": tool_results},
        {"role": "assistant", "content": "done"},
    ]


@pytest.fixture
def tool_heavy_workspace(tmp_path: Path) -> tuple[Path, str]:
    """Workspace JSONL with many tool-heavy turns (repro for limit=6 crash)."""
    root = tmp_path / "ws"
    sessions = root / "sessions" / "telegram" / "chats" / "8484033337" / "general"
    sessions.mkdir(parents=True)
    session_id = "c" * 32
    jsonl_path = sessions / f"{session_id}.jsonl"
    records: list[dict[str, object]] = []
    for n in range(1, 25):
        records.append(
            {
                "id": n * 2 - 1,
                "ts": f"2026-07-14T{20 + (n % 3):02d}:{n % 60:02d}:00",
                "role": "user",
                "kind": "message",
                "content": f"ask {n}",
                "turn_id": f"turn-{n}",
            }
        )
        # Mix dict extras with shapes that previously crashed on `.get` over ints.
        extras: dict[str, object] = {
            "provider_turn_messages": _tool_heavy_provider_messages(tool_count=8 + (n % 5)),
            # Regression bait: nested ints that naive `.get` chains mishandle.
            "token_usage": 128,
            "nest": {"count": 3, "flags": [1, 2, {"ok": True}]},
        }
        records.append(
            {
                "id": n * 2,
                "ts": f"2026-07-14T{20 + (n % 3):02d}:{n % 60:02d}:30",
                "role": "assistant",
                "kind": "message",
                "content": f"reply {n}",
                "turn_id": f"turn-{n}",
                "extras": extras,
            }
        )
    jsonl_path.write_text(
        "\n".join(json.dumps(row) for row in records) + "\n",
        encoding="utf-8",
    )
    index = {
        "sessions": {
            session_id: {
                "jsonl": f"telegram/chats/8484033337/general/{session_id}.jsonl",
            },
        },
    }
    (root / "sessions" / "_index.json").write_text(json.dumps(index), encoding="utf-8")
    (root / ".sevn").mkdir()
    return root, session_id


@pytest.fixture
def ctx(tool_heavy_workspace: tuple[Path, str]) -> ToolContext:
    workspace, session_id = tool_heavy_workspace
    return ToolContext(
        session_id=session_id,
        workspace_path=workspace,
        workspace_id="transcript-d10",
        registry_version=1,
        permissions=AllowAllPermissionPolicy(),
    )


@_XFAIL_W4
@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [5, 6, 20])
async def test_d10_read_transcript_tool_heavy_limits_never_int_get(
    ctx: ToolContext, limit: int
) -> None:
    """D10: tool-heavy transcripts must not raise ``'int' object has no attribute 'get'``.

    The live session crashed on ``limit=6`` while ``5``/``20`` passed — cover that range.
    """
    raw = await read_transcript_tool(ctx, role="assistant", limit=limit, full=True)
    data = json.loads(raw)
    assert data["ok"] is True, data
    assert "int' object has no attribute 'get" not in str(data.get("error", ""))
    turns = data["data"]["turns"]
    assert isinstance(turns, list)
    assert len(turns) <= limit
