"""Job queue SQLite helpers (`specs/33-self-improvement.md` §3.3).

Module: sevn.self_improve.jobs
Depends: sevn.self_improve.jobs.events, sevn.self_improve.jobs.store

Exports:
    ImproveJobEventPayload — dashboard/Telegram fan-out payload.
    abort_job_row — operator abort transition.
    enqueue_job_row — insert or dedupe queued row.
    improve_job_ws_topic — ``self_improve.job.{id}`` topic naming.
"""

from __future__ import annotations

from sevn.self_improve.jobs.events import (
    ImproveJobEventFanoutFn,
    ImproveJobEventPayload,
    improve_job_ws_topic,
    maybe_publish_job_event,
)
from sevn.self_improve.jobs.store import (
    ImproveJobRow,
    abort_job_row,
    claim_next_queued_job,
    enqueue_job_row,
    fetch_job_row,
    update_job_state,
)

__all__ = [
    "ImproveJobEventFanoutFn",
    "ImproveJobEventPayload",
    "ImproveJobRow",
    "abort_job_row",
    "claim_next_queued_job",
    "enqueue_job_row",
    "fetch_job_row",
    "improve_job_ws_topic",
    "maybe_publish_job_event",
    "update_job_state",
]
