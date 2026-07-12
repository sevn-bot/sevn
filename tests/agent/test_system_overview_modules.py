from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sevn.agent.providers import resolve_model
from sevn.agent.providers.transport import AnthropicTransport
from sevn.agent.templates.registry import load_template_registry, registry_version
from sevn.agent.tracing.sink import (
    JSONLFileSink,
    NullTraceSink,
    TraceEvent,
    current_sink,
    trace_sink_scope,
)
from sevn.plugins import Block, Continue, HookContext, PluginHookBase, Replace


def test_resolve_model_returns_bound_transport() -> None:
    mid, transport = resolve_model(model_id="mid-1", transport_name="anthropic")
    assert mid == "mid-1"
    assert transport.name == "anthropic"


def test_resolve_model_rejects_unknown_transport() -> None:
    with pytest.raises(ValueError, match="unknown transport_name"):
        resolve_model(model_id="m", transport_name="nope")


@pytest.mark.asyncio
async def test_trace_sink_scope_sets_current_sink() -> None:
    assert current_sink() is None
    sink = NullTraceSink()
    with trace_sink_scope(sink):
        assert current_sink() is sink
    assert current_sink() is None


@pytest.mark.asyncio
async def test_jsonl_sink_writes_event(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    sink = JSONLFileSink(path)
    event = TraceEvent(
        kind="tool.call",
        span_id="s1",
        parent_span_id=None,
        session_id="se",
        turn_id="tu",
        tier="B",
        ts_start_ns=3,
        ts_end_ns=4,
        status="ok",
        attrs={"tool": "echo"},
    )
    await sink.emit(event)
    text = path.read_text(encoding="utf-8").strip()
    assert "tool.call" in text
    assert '"span_id":"s1"' in text or '"span_id": "s1"' in text  # compact json has no spaces


@pytest.mark.asyncio
async def test_jsonl_sink_emit_swallows_write_errors(tmp_path: Path) -> None:
    path = tmp_path / "blocked.jsonl"
    sink = JSONLFileSink(path)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("write failed")

    with patch.object(Path, "open", boom):
        await sink.emit(
            TraceEvent(
                kind="k",
                span_id="s",
                parent_span_id=None,
                session_id="se",
                turn_id="t",
                tier=None,
                ts_start_ns=1,
                ts_end_ns=None,
                status="pending",
            ),
        )


class _TableHook(PluginHookBase):
    """Hook used only for table-driven outcome tests (not registered in gateway)."""

    async def pre_tool_call(
        self,
        tool_name: str,
        args: dict[str, object],
        ctx: HookContext,
    ) -> Continue | Block | Replace:
        if tool_name == "blocked":
            return Block(reason="denied")
        if tool_name == "rewrite":
            return Replace(new_args={"x": 1})
        return await super().pre_tool_call(tool_name, args, ctx)


@pytest.mark.parametrize(
    ("tool", "args", "expected_type", "expected_payload"),
    [
        ("blocked", {}, Block, "denied"),
        ("rewrite", {"old": True}, Replace, None),
        ("ok", {}, Continue, None),
    ],
)
@pytest.mark.asyncio
async def test_plugin_hook_pre_tool_call_outcomes(
    tool: str,
    args: dict[str, object],
    expected_type: type,
    expected_payload: str | None,
) -> None:
    """Table-driven ``Block`` / ``Replace`` / ``Continue`` without executor wiring."""
    hook = _TableHook("row")
    ctx = HookContext(
        workspace_id="w",
        session_id="s",
        turn_id="t",
        tier="B",
        correlation_id="c",
    )
    out = await hook.pre_tool_call(tool, args, ctx)
    assert isinstance(out, expected_type)
    if expected_type is Block:
        assert isinstance(out, Block)
        assert out.reason == expected_payload
    elif expected_type is Replace:
        assert isinstance(out, Replace)
        assert out.new_args == {"x": 1}


@pytest.mark.asyncio
async def test_plugin_hook_base_defaults() -> None:
    hook = PluginHookBase("trivial")
    ctx = HookContext(
        workspace_id="w",
        session_id="s",
        turn_id="t",
        tier="triager",
        correlation_id="c",
    )
    assert isinstance(await hook.pre_tool_call("tool", {}, ctx), Continue)
    assert await hook.transform_tool_result("tool", {"a": 1}, ctx) == {"a": 1}
    assert await hook.transform_terminal_output("hello", ctx) == "hello"
    assert hook.register_command() == []
    assert await hook.dispatch_tool("tool", [], ctx) is None


def test_template_registry_version_stable(tmp_path: Path) -> None:
    root = tmp_path / "tpl"
    root.mkdir()
    (root / "a.md").write_text("hello", encoding="utf-8")
    (root / "b.md").write_text("---\nid: custom\n---\nbody", encoding="utf-8")
    entries = load_template_registry(root)
    assert [e.template_id for e in entries] == ["a.md", "custom"]
    assert registry_version(entries) == registry_version(entries)


@pytest.mark.asyncio
async def test_stub_transport_complete_raises() -> None:
    with pytest.raises(NotImplementedError):
        await AnthropicTransport().complete({})


@pytest.mark.asyncio
async def test_stub_transport_stream_raises() -> None:
    agen = AnthropicTransport().stream({})
    with pytest.raises(NotImplementedError):
        await anext(agen)
