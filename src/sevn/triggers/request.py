"""Dispatch envelopes for non-interactive runs (`specs/30-non-interactive-triggers.md` §3.1).

Module: sevn.triggers.request
Depends: pydantic

Exports:
    ResultChannel — destination for trigger outcomes.
    DispatchRequest — unified ingress payload.
    RunHandle — agent-pass bookkeeping handle.
    NotifyHandle — notify-only bookkeeping handle.

Examples:
    >>> from sevn.triggers.request import DispatchRequest, ResultChannel
    >>> DispatchRequest.__name__
    'DispatchRequest'
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RoutingMode = Literal["fixed", "auto_route"]
DeliveryMode = Literal["agent_pass", "notify_only"]
ResultChannelKind = Literal["LOG", "TELEGRAM_TOPIC", "WEBUI_NOTIFICATION", "BACK_TO_SOURCE"]


class ResultChannel(BaseModel):
    """Where trigger output lands (`specs/30-non-interactive-triggers.md` §4.6)."""

    model_config = ConfigDict(extra="forbid")

    kind: ResultChannelKind
    telegram_topic_id: int | None = None
    back_to_source: str | None = None


class DispatchRequest(BaseModel):
    """Logical request shared by webhook / cron / HTTP API paths."""

    model_config = ConfigDict(extra="forbid")

    prompt: str
    routing_mode: RoutingMode = "fixed"
    delivery_mode: DeliveryMode = "agent_pass"
    permission_template_ref: str = "default"
    allow_tier_cd: bool = False
    result_channel: ResultChannel
    correlation_id: str
    payload: dict[str, object] | None = None
    trigger_meta: dict[str, object] = Field(default_factory=dict)
    notify_template: str | None = None


@dataclass(frozen=True)
class RunHandle:
    """Bookkeeping for ``dispatch_run`` (run id may mirror ``correlation_id``)."""

    run_id: str
    correlation_id: str


@dataclass(frozen=True)
class NotifyHandle:
    """Bookkeeping for ``dispatch_notify_only``."""

    correlation_id: str
