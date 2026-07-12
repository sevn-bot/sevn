"""Tests for CodeMode bare-native-call → ``run_code`` rewrite (Layer 1/2/3).

Covers `rewrite_codemode_native_tool_calls` in
`src/sevn/agent/adapters/tier_b_model.py`: a MiniMax-class model that emits a
top-level call to a CodeMode-sandboxed tool (no native handler) has the call
rewritten into an equivalent single-statement ``run_code`` invocation, so it
dispatches through the sandbox instead of vanishing as an orphan
(`specs/14-executor-tier-b.md` §5.1, §10.20).
"""

from __future__ import annotations

from pydantic_ai.messages import TextPart, ToolCallPart

from sevn.agent.adapters.tier_b_model import rewrite_codemode_native_tool_calls

SANDBOXED = frozenset({"get_page_content", "serp", "web_fetch", "web_search"})


def test_sandboxed_native_call_rewritten_to_run_code() -> None:
    parts, rewritten = rewrite_codemode_native_tool_calls(
        [ToolCallPart(tool_name="get_page_content", args={"url": "https://x"}, tool_call_id="c1")],
        sandboxed_tool_names=SANDBOXED,
    )
    assert rewritten == ["get_page_content"]
    assert len(parts) == 1
    only = parts[0]
    assert isinstance(only, ToolCallPart)
    assert only.tool_name == "run_code"
    # tool_call_id is preserved so the dispatched result maps back to the model's call.
    assert only.tool_call_id == "c1"
    assert only.args == {"code": "result = await get_page_content(url='https://x')\nresult"}


def test_native_meta_tool_left_unchanged() -> None:
    # load_skill is a native CodeMode tool — it has a handler, so it must NOT be rewritten.
    original = ToolCallPart(tool_name="load_skill", args={"name": "pdf"}, tool_call_id="m1")
    parts, rewritten = rewrite_codemode_native_tool_calls(
        [original],
        sandboxed_tool_names=SANDBOXED,
    )
    assert rewritten == []
    assert parts == [original]


def test_empty_sandboxed_set_is_noop() -> None:
    # CodeMode off → no sandboxed names → rewrite must be a pure pass-through.
    given = [ToolCallPart(tool_name="get_page_content", args={"url": "x"}, tool_call_id="c1")]
    parts, rewritten = rewrite_codemode_native_tool_calls(
        given,
        sandboxed_tool_names=frozenset(),
    )
    assert rewritten == []
    assert parts is given


def test_text_parts_pass_through_and_multiple_calls_rewritten() -> None:
    parts, rewritten = rewrite_codemode_native_tool_calls(
        [
            TextPart(content="on it"),
            ToolCallPart(tool_name="serp", args={"query": "btc", "count": 3}, tool_call_id="a"),
            ToolCallPart(tool_name="web_fetch", args={"url": "https://y"}, tool_call_id="b"),
        ],
        sandboxed_tool_names=SANDBOXED,
    )
    assert rewritten == ["serp", "web_fetch"]
    assert isinstance(parts[0], TextPart)
    assert isinstance(parts[1], ToolCallPart)
    assert parts[1].tool_name == "run_code"
    assert parts[1].tool_call_id == "a"
    assert parts[1].args == {"code": "result = await serp(query='btc', count=3)\nresult"}
    assert isinstance(parts[2], ToolCallPart)
    assert parts[2].tool_name == "run_code"
    assert parts[2].tool_call_id == "b"


def test_json_string_args_are_decoded() -> None:
    parts, rewritten = rewrite_codemode_native_tool_calls(
        [ToolCallPart(tool_name="serp", args='{"query": "hi"}', tool_call_id="j")],
        sandboxed_tool_names=SANDBOXED,
    )
    assert rewritten == ["serp"]
    assert isinstance(parts[0], ToolCallPart)
    assert parts[0].args == {"code": "result = await serp(query='hi')\nresult"}


def test_no_args_emits_bare_call() -> None:
    parts, _ = rewrite_codemode_native_tool_calls(
        [ToolCallPart(tool_name="get_page_content", args=None, tool_call_id="n")],
        sandboxed_tool_names=SANDBOXED,
    )
    assert isinstance(parts[0], ToolCallPart)
    assert parts[0].args == {"code": "result = await get_page_content()\nresult"}


def test_native_drop_safety_error_never_strip() -> None:
    """Regression: sandbox-eligible tool called natively → tool error via run_code, NOT silent strip.

    The "error, never strip" invariant (D5 / specs/14 §5.1 §10.20): when a MiniMax-class
    model on any wire (Anthropic or OpenAI chat-completions) emits a bare ToolCallPart for a
    sandboxed-only tool, the call MUST be rewritten to ``run_code`` (preserving tool_call_id)
    so pydantic-ai dispatches it through the sandbox. It must NEVER be silently removed —
    removal causes the model to fabricate results or loop to max_retries.
    """
    original_id = "openai-wire-call-42"
    parts, rewritten = rewrite_codemode_native_tool_calls(
        [
            ToolCallPart(
                tool_name="serp",
                args={"query": "test search"},
                tool_call_id=original_id,
            ),
        ],
        sandboxed_tool_names=SANDBOXED,
    )
    # NEVER stripped — exactly one part output for one part input
    assert len(parts) == 1
    assert rewritten == ["serp"]
    rewritten_part = parts[0]
    assert isinstance(rewritten_part, ToolCallPart)
    # Rewritten to run_code — will dispatch through sandbox
    assert rewritten_part.tool_name == "run_code"
    # tool_call_id preserved — pydantic-ai maps the result back to the model's call
    assert rewritten_part.tool_call_id == original_id
    # Code invokes the original tool inside the sandbox
    assert "await serp(" in rewritten_part.args["code"]


def test_run_code_json_wrapped_payload_is_unwrapped() -> None:
    """A ``code='{"code": ...}'`` double-wrapped payload is peeled to the inner source.

    Reproduces the MiniMax malformation that burned CodeMode's retry budget to
    ``Tool 'run_code' exceeded max retries`` (transcript 2026-06-23).
    """
    from sevn.agent.adapters.tier_b_model import normalize_codemode_run_code_payloads

    wrapped = '{"code": "result = await log_query(lines=80)\\nresult"}'
    parts, repaired = normalize_codemode_run_code_payloads(
        [ToolCallPart(tool_name="run_code", args={"code": wrapped}, tool_call_id="c1")],
    )
    assert repaired == 1
    assert parts[0].tool_name == "run_code"
    assert parts[0].tool_call_id == "c1"
    assert parts[0].args["code"] == "result = await log_query(lines=80)\nresult"


def test_run_code_plain_payload_is_untouched() -> None:
    """A normal ``run_code`` payload (raw Python) is left exactly as-is."""
    from sevn.agent.adapters.tier_b_model import normalize_codemode_run_code_payloads

    code = "result = await serp(query='world cup')\nresult"
    parts, repaired = normalize_codemode_run_code_payloads(
        [ToolCallPart(tool_name="run_code", args={"code": code}, tool_call_id="c2")],
    )
    assert repaired == 0
    assert parts[0].args["code"] == code


def test_non_run_code_parts_pass_through() -> None:
    """Text parts and other tool calls are not affected by the run_code normalizer."""
    from sevn.agent.adapters.tier_b_model import normalize_codemode_run_code_payloads

    parts, repaired = normalize_codemode_run_code_payloads(
        [
            TextPart(content="hi"),
            ToolCallPart(tool_name="list_registry", args={}, tool_call_id="c3"),
        ],
    )
    assert repaired == 0
    assert len(parts) == 2
