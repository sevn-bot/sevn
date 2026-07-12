"""Notify-only dispatch must not emit ``provider.call`` (`specs/30-non-interactive-triggers.md` §9)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sevn.agent.tracing.sink import TraceEvent, TraceSink
from sevn.config.workspace_config import WorkspaceConfig
from sevn.triggers.dispatcher import dispatch_notify_only
from sevn.triggers.request import DispatchRequest, ResultChannel


class _ListSink:
    """Collect trace events for assertions."""

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def emit(self, event: TraceEvent) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        return

    async def close(self) -> None:
        return


@pytest.mark.asyncio
async def test_notify_only_trace_has_no_provider_call(tmp_path: Path) -> None:
    ws = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    sink = _ListSink()
    trace: TraceSink = sink  # type: ignore[assignment]
    req = DispatchRequest(
        prompt="hello",
        delivery_mode="notify_only",
        result_channel=ResultChannel(kind="LOG"),
        correlation_id="cid-1",
        notify_template="Ping: {{ prompt }}",
        trigger_meta={"transport": "unit"},
    )
    await dispatch_notify_only(
        req,
        workspace=ws,
        content_root=tmp_path,
        trace=trace,
        hooks=None,
    )
    kinds = {e.kind for e in sink.events}
    assert "trigger.notify_only" in kinds
    assert "provider.call" not in kinds
    assert "sandbox.boot" not in kinds
