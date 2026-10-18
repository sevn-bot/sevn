"""Sevn-owned runtime events (spike 0003 D4, spec A.2.1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type RuntimeEventKind = Literal[
    "session_bound",
    "text_delta",
    "thinking_delta",
    "tool_call_started",
    "tool_call_finished",
    "permission_request",
    "error",
    "turn_finished",
    "ignored",
]


@dataclass(frozen=True, slots=True)
class ApprovalCall:
    """One tool call the runtime paused for approval."""

    tool_call_id: str
    name: str
    args: dict[str, object]


@dataclass(slots=True)
class RuntimeEvent:
    """One mapped runtime event. Only the fields for ``kind`` are meaningful."""

    kind: RuntimeEventKind
    text: str | None = None
    name: str | None = None
    args: dict[str, object] | None = None
    ok: bool | None = None
    tool: str | None = None
    request_id: str | None = None
    usage: dict[str, object] | None = None
    code: str | None = None
    message: str | None = None
    session_ref: str | None = None
    native_type: str | None = None
    model_messages: list[object] | None = None
    approvals: tuple[ApprovalCall, ...] | None = None
