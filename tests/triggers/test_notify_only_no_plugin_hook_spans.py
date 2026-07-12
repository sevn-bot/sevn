"""Golden: notify_only must not emit ``plugin.hook.*`` tool intercept spans (`specs/34-plugin-hooks.md` §9)."""

from __future__ import annotations

import pytest

from sevn.agent.tracing.sink import TraceEvent, TraceSink
from sevn.config.workspace_config import parse_workspace_config
from sevn.triggers.dispatcher import dispatch_notify_only
from sevn.triggers.request import DispatchRequest, ResultChannel


class _ListSink(TraceSink):
    def __init__(self) -> None:
        self.rows: list[TraceEvent] = []

    async def emit(self, event: TraceEvent) -> None:
        self.rows.append(event)

    async def flush(self) -> None:
        return

    async def close(self) -> None:
        return


@pytest.mark.asyncio
async def test_notify_only_has_no_plugin_hook_kinds(tmp_path) -> None:
    """Tool-hook trace kinds stay off the notify_only path."""
    from sevn.plugins.hook import PluginHookBase
    from sevn.plugins.runner import PluginHookChain, RegisteredHook
    from sevn.plugins.trigger_mux import TriggerPluginHooksMux

    class Noise(PluginHookBase):
        async def transform_tool_result(self, tool_name, result, ctx):  # type: ignore[no-untyped-def]
            _ = (tool_name, result, ctx)
            return result

    h = Noise("demo.test.x")
    chain = PluginHookChain(
        (
            RegisteredHook(
                hook=h,
                plugin_id="p",
                distribution_name="d",
                entry_point_name="e",
                trust_owner=False,
            ),
        ),
    )
    mux = TriggerPluginHooksMux(chain)
    sink = _ListSink()
    ws = parse_workspace_config(
        {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
    )
    req = DispatchRequest(
        prompt="hello",
        routing_mode="fixed",
        delivery_mode="notify_only",
        permission_template_ref="default",
        allow_tier_cd=False,
        result_channel=ResultChannel(kind="LOG"),
        correlation_id="cid-1",
        trigger_meta={"transport": "api"},
        notify_template="{{ prompt }}",
    )
    await dispatch_notify_only(
        req,
        workspace=ws,
        content_root=tmp_path,
        trace=sink,
        hooks=mux,
    )
    kinds = {e.kind for e in sink.rows}
    assert not any(k.startswith("plugin.hook.") for k in kinds)
