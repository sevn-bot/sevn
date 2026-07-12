"""chat_completions tool-pairing hygiene (`specs/14-executor-tier-b.md`).

On the MiniMax OpenAI wire two pairing failures make upstream reject the request with
``invalid params … (2013)``:

* **Orphan return** — a tool return whose ``tool_call_id`` has no matching preceding
  ``ToolCallPart`` (``tool result's tool id not found``).
* **Dangling call** — an assistant ``ToolCallPart`` with no matching following
  ``ToolReturnPart`` (``tool call and result not match``).

The Anthropic path already repairs both directions; the chat_completions path does too.
"""

from __future__ import annotations

import itertools

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from sevn.agent.adapters.tier_b_model import (
    coalesce_adjacent_openai_messages,
    finalize_openai_chat_messages,
    repair_openai_tool_pairing,
)


def test_finalize_drops_trailing_assistant_echo() -> None:
    """A trailing assistant row without tool_calls (failed-pass echo) is dropped — 2013 fix."""
    out = finalize_openai_chat_messages(
        [
            {"role": "user", "content": "yesterday's scores?"},
            {"role": "assistant", "content": "Sorry — something went wrong."},
        ],
    )
    assert out == [{"role": "user", "content": "yesterday's scores?"}]


def test_finalize_keeps_trailing_assistant_with_tool_calls() -> None:
    """A trailing assistant WITH tool_calls is left for repair_openai_tool_pairing."""
    rows = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "tool_calls": [{"id": "a", "function": {"name": "read"}}]},
    ]
    assert finalize_openai_chat_messages(rows) == rows


def test_finalize_drops_orphan_tool_result() -> None:
    """A tool result whose id matches no assistant tool_call is dropped (2013 pairing fix)."""
    out = finalize_openai_chat_messages(
        [
            {"role": "assistant", "tool_calls": [{"id": "a", "function": {"name": "x"}}]},
            {"role": "tool", "tool_call_id": "a", "content": "ok"},
            {"role": "tool", "tool_call_id": "ghost", "content": "orphan"},
            {"role": "user", "content": "next"},
        ],
    )
    assert [m["role"] for m in out] == ["assistant", "tool", "user"]
    assert all(m.get("tool_call_id") != "ghost" for m in out)


def test_coalesce_merges_consecutive_user_rows() -> None:
    """Consecutive user rows (message + owner steer) merge — MiniMax 2013 otherwise."""
    merged = coalesce_adjacent_openai_messages(
        [
            {"role": "user", "content": "what won yesterday?"},
            {"role": "user", "content": "[Owner steer] search first"},
        ],
    )
    assert merged == [
        {"role": "user", "content": "what won yesterday?\n[Owner steer] search first"},
    ]


def test_coalesce_merges_consecutive_assistant_rows_with_tool_calls() -> None:
    """Adjacent assistant rows merge content and concatenate tool_calls."""
    merged = coalesce_adjacent_openai_messages(
        [
            {
                "role": "assistant",
                "tool_calls": [{"id": "a", "function": {"name": "read", "arguments": "{}"}}],
            },
            {"role": "assistant", "content": "answer"},
        ],
    )
    assert merged == [
        {
            "role": "assistant",
            "content": "answer",
            "tool_calls": [{"id": "a", "function": {"name": "read", "arguments": "{}"}}],
        },
    ]


def test_coalesce_leaves_tool_rows_unmerged() -> None:
    """Each ``tool`` row keeps its own tool_call_id (OpenAI requires one per call)."""
    rows = [
        {"role": "tool", "tool_call_id": "a", "content": "1"},
        {"role": "tool", "tool_call_id": "b", "content": "2"},
    ]
    assert coalesce_adjacent_openai_messages(rows) == rows


def test_coalesce_repairs_failure_role_sequence() -> None:
    """transcript-review-2026-06-22: the exact 2013 role sequence has no adjacent same-role rows after coalesce."""
    # roles from the rejected request: system, assistant, user, assistant, ..., user, user, assistant
    roles = [
        "assistant",
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
        "user",  # <-- the consecutive pair that triggered 2013
        "assistant",
    ]
    rows = [{"role": r, "content": f"{r}{i}"} for i, r in enumerate(roles)]
    merged = coalesce_adjacent_openai_messages(rows)
    assert not any(
        a["role"] == b["role"] and a["role"] in ("user", "assistant")
        for a, b in itertools.pairwise(merged)
    )


def test_orphan_tool_return_request_is_dropped() -> None:
    hist = [
        ModelResponse(parts=[ToolCallPart(tool_name="read", args={}, tool_call_id="t1")]),
        ModelRequest(parts=[ToolReturnPart(tool_name="read", content="ok", tool_call_id="t1")]),
        ModelRequest(parts=[ToolReturnPart(tool_name="x", content="zz", tool_call_id="ghost")]),
    ]
    repaired = repair_openai_tool_pairing(hist)
    assert len(repaired) == 2
    # The surviving tool return is the one whose call id was actually emitted.
    returns = [p for m in repaired if isinstance(m, ModelRequest) for p in m.parts]
    assert all(getattr(p, "tool_call_id", None) != "ghost" for p in returns)


def test_orphan_return_dropped_but_user_prompt_kept() -> None:
    hist = [
        ModelRequest(
            parts=[
                UserPromptPart(content="hi"),
                ToolReturnPart(tool_name="x", content="zz", tool_call_id="ghost"),
            ],
        ),
    ]
    repaired = repair_openai_tool_pairing(hist)
    assert len(repaired) == 1
    parts = repaired[0].parts
    assert any(isinstance(p, UserPromptPart) for p in parts)
    assert not any(isinstance(p, ToolReturnPart) for p in parts)


def test_orphan_retry_prompt_with_tool_id_dropped() -> None:
    hist = [
        ModelRequest(parts=[RetryPromptPart(content="retry", tool_name="x", tool_call_id="ghost")]),
    ]
    assert repair_openai_tool_pairing(hist) == []


def test_valid_pairing_is_untouched() -> None:
    hist = [
        ModelRequest(parts=[UserPromptPart(content="go")]),
        ModelResponse(parts=[ToolCallPart(tool_name="read", args={}, tool_call_id="t1")]),
        ModelRequest(parts=[ToolReturnPart(tool_name="read", content="ok", tool_call_id="t1")]),
        ModelResponse(parts=[TextPart(content="done")]),
    ]
    assert repair_openai_tool_pairing(hist) == hist


def test_plain_retry_without_tool_id_preserved() -> None:
    hist = [ModelRequest(parts=[RetryPromptPart(content="bad output")])]
    assert repair_openai_tool_pairing(hist) == hist


def test_trailing_dangling_tool_call_gets_stub_return() -> None:
    hist = [
        ModelResponse(parts=[ToolCallPart(tool_name="run_code", args={}, tool_call_id="t1")]),
    ]
    repaired = repair_openai_tool_pairing(hist)
    assert len(repaired) == 2
    assert isinstance(repaired[0], ModelResponse)
    assert isinstance(repaired[1], ModelRequest)
    returns = repaired[1].parts
    assert len(returns) == 1
    part = returns[0]
    assert isinstance(part, ToolReturnPart)
    assert part.tool_call_id == "t1"
    assert part.tool_name == "run_code"
    assert part.content == "[no result recorded]"


def test_mid_history_dangling_call_stub_inserted_after_response() -> None:
    hist = [
        ModelRequest(parts=[UserPromptPart(content="go")]),
        ModelResponse(parts=[ToolCallPart(tool_name="read", args={}, tool_call_id="t1")]),
        ModelRequest(parts=[ToolReturnPart(tool_name="read", content="ok", tool_call_id="t1")]),
        ModelResponse(parts=[ToolCallPart(tool_name="write", args={}, tool_call_id="t2")]),
        ModelResponse(parts=[TextPart(content="done")]),
    ]
    repaired = repair_openai_tool_pairing(hist)
    assert len(repaired) == 6
    assert isinstance(repaired[3], ModelResponse)
    assert isinstance(repaired[4], ModelRequest)
    stub = repaired[4].parts[0]
    assert isinstance(stub, ToolReturnPart)
    assert stub.tool_call_id == "t2"
    assert stub.tool_name == "write"
    assert isinstance(repaired[5], ModelResponse)
