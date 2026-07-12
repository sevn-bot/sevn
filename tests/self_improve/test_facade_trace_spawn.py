"""``_schedule_trace_emit`` uses :func:`spawn_logged` for fire-and-forget traces."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.self_improve.facade import _schedule_trace_emit
from sevn.self_improve.trace_events import emit_self_improve_trace


def test_schedule_trace_emit_no_loop_delegates_to_spawn_logged() -> None:
    coro = emit_self_improve_trace(NullTraceSink(), job_id="j", kind="self_improve.job_start")
    with patch("sevn.self_improve.facade.spawn_logged", return_value=None) as mock_spawn:
        assert _schedule_trace_emit(coro) is None
    mock_spawn.assert_called_once()
    assert mock_spawn.call_args.kwargs["label"] == "self_improve_trace_emit"


@pytest.mark.asyncio
async def test_schedule_trace_emit_with_loop_delegates_to_spawn_logged() -> None:
    coro = emit_self_improve_trace(NullTraceSink(), job_id="j", kind="self_improve.job_start")
    with patch("sevn.self_improve.facade.spawn_logged") as mock_spawn:
        mock_spawn.return_value = None
        assert _schedule_trace_emit(coro) is None
    mock_spawn.assert_called_once_with(coro, label="self_improve_trace_emit")
