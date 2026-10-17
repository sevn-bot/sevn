"""Durable and ephemeral event types (spec §3.0.2)."""

from __future__ import annotations

from dataclasses import dataclass

_DURABLE = (
    "bot.updated",
    "job.queued",
    "job.started",
    "job.done",
    "turn.started",
    "turn.step",
    "turn.waiting",
    "turn.finished",
    "message.created",
    "pending.created",
    "pending.resolved",
    "memory.changed",
    "routine.run",
    "ui.surface",
    "system.ping",
)
_EPHEMERAL = ("turn.delta",)


@dataclass(frozen=True, slots=True)
class EventSpec:
    name: str
    durable: bool


EVENTS: dict[str, EventSpec] = {
    spec.name: spec
    for spec in (
        *(EventSpec(name, durable=True) for name in _DURABLE),
        *(EventSpec(name, durable=False) for name in _EPHEMERAL),
    )
}
