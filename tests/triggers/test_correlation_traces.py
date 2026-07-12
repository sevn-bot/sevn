"""Trace anchor: ``correlation_id`` links ``trigger.receive`` → agent dispatch."""

from __future__ import annotations

from pathlib import Path

import pytest

from sevn.agent.tracing.sink import TraceEvent, TraceSink
from sevn.config.workspace_config import WorkspaceConfig
from sevn.triggers.dispatcher import dispatch_run
from sevn.triggers.request import DispatchRequest, ResultChannel


class _ListSink:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def emit(self, event: TraceEvent) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        return

    async def close(self) -> None:
        return


@pytest.mark.asyncio
async def test_dispatch_run_correlation_in_receive_and_agent_skipped(tmp_path: Path) -> None:
    ws = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    sink = _ListSink()
    trace: TraceSink = sink  # type: ignore[assignment]
    cid = "corr-anchor-1"
    req = DispatchRequest(
        prompt="do thing",
        result_channel=ResultChannel(kind="LOG"),
        correlation_id=cid,
        trigger_meta={"transport": "unit"},
    )
    await dispatch_run(req, workspace=ws, content_root=tmp_path, trace=trace, hooks=None)
    recv = [e for e in sink.events if e.kind == "trigger.receive"]
    skipped = [e for e in sink.events if e.kind == "trigger.agent_skipped"]
    assert len(recv) == 1
    assert len(skipped) == 1
    assert recv[0].attrs.get("correlation_id") == cid
    assert skipped[0].attrs.get("correlation_id") == cid
    assert skipped[0].parent_span_id == next(
        e.span_id for e in sink.events if e.kind == "trigger.dispatch"
    )
