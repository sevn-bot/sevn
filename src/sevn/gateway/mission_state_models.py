"""Mission Control dataclasses and trace-normalization helpers.

Module: sevn.gateway.mission_state_models
Depends: sevn.agent.triager.models

Exports:
    AgentActivity — one activity-feed row.
    Alert — triggered alert record.
    AlertRule — threshold rule definition.
    ChannelHealth — channel adapter health snapshot.
    NotificationTarget — alert notification destination.
    ProviderHealth — LLM provider health snapshot.
    SessionMissionStats — per-session counters from gateway traces.
    event_timestamp — convert ``TraceEvent`` wall time to epoch seconds.
    is_channel_trace_kind — predicate for channel lifecycle kinds.
    is_mission_telemetry_kind — predicate for provider/channel telemetry kinds.
    normalize_complexity — map trace complexity attrs to tier labels.

Also exposes ``GATEWAY_TRACE_KINDS``, ``MISSION_TELEMETRY_TRACE_KINDS``, and
``CHANNEL_TRACE_PREFIXES`` for trace-kind routing.
Examples:
    >>> "A" in {t.value for t in __import__("sevn.agent.triager.models", fromlist=["COMPLEXITY_TIERS"]).COMPLEXITY_TIERS}
    True
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from sevn.agent.triager.models import COMPLEXITY_TIERS

if TYPE_CHECKING:
    from sevn.agent.tracing.sink import TraceEvent

GATEWAY_TRACE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "gateway.boot",
        "gateway.triage.completed",
        "gateway.executor.b_completed",
        "gateway.triage.disregard",
    },
)

MISSION_TELEMETRY_TRACE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "provider.call",
        "subagent_spawned",
        "subagent_finished",
        "subagent_killed",
    },
)

CHANNEL_TRACE_PREFIXES: Final[tuple[str, ...]] = (
    "channel.telegram.",
    "channel.webchat.",
)


def is_channel_trace_kind(kind: str) -> bool:
    """Return whether ``kind`` is a channel lifecycle or health trace.

    Args:
        kind (str): Trace event kind.

    Returns:
        bool: True when ``kind`` starts with a known channel prefix.

    Examples:
        >>> is_channel_trace_kind("channel.telegram.start")
        True
        >>> is_channel_trace_kind("gateway.boot")
        False
    """
    return kind.startswith(CHANNEL_TRACE_PREFIXES)


def is_mission_telemetry_kind(kind: str) -> bool:
    """Return whether ``kind`` should update mission-state provider/channel maps.

    Args:
        kind (str): Trace event kind.

    Returns:
        bool: True for ``provider.call``, sub-agent lifecycle kinds, or channel kinds.

    Examples:
        >>> is_mission_telemetry_kind("provider.call")
        True
        >>> is_mission_telemetry_kind("subagent_spawned")
        True
        >>> is_mission_telemetry_kind("tool.invoke")
        False
    """
    return kind in MISSION_TELEMETRY_TRACE_KINDS or is_channel_trace_kind(kind)


_COMPLEXITY_LABELS: Final[tuple[str, ...]] = tuple(t.value for t in COMPLEXITY_TIERS)
ERROR_STATUSES: Final[frozenset[str]] = frozenset({"failed", "error"})
ESCALATION_STATUSES: Final[frozenset[str]] = frozenset({"escalated"})


@dataclass
class ProviderHealth:
    """Health status of an LLM provider."""

    name: str
    available: bool = True
    last_check: float = 0.0
    latency_ms: float = 0.0
    error_count: int = 0
    total_requests: int = 0
    total_tokens: int = 0


@dataclass
class ChannelHealth:
    """Health status of a channel adapter."""

    name: str
    connected: bool = False
    connection_state: str = "disconnected"
    last_message_at: float = 0.0
    last_error_at: float = 0.0
    last_error: str = ""
    message_count: int = 0
    error_count: int = 0
    reconnect_count: int = 0
    adapter_type: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentActivity:
    """A recorded agent activity event."""

    timestamp: float
    event_type: str
    session_id: str = ""
    detail: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0


@dataclass
class AlertRule:
    """An alert rule that fires when a threshold is crossed."""

    name: str
    metric: str
    threshold: float
    window_seconds: float = 300.0
    severity: str = "warning"
    enabled: bool = True
    silenced_until: float = 0.0


@dataclass
class Alert:
    """A triggered alert."""

    rule_name: str
    severity: str
    message: str
    timestamp: float
    acknowledged: bool = False
    source: str = ""


@dataclass
class NotificationTarget:
    """A target for alert notifications."""

    name: str
    target_type: str
    url: str = ""
    enabled: bool = True


@dataclass
class SessionMissionStats:
    """Per-session counters derived from gateway trace spans."""

    session_id: str
    turn_count: int = 0
    escalations: int = 0
    errors: int = 0
    disregards: int = 0
    last_complexity: str | None = None
    last_activity_at: float = 0.0
    subagents_running_by_level_role: dict[str, int] = field(default_factory=dict)
    """Active sub-agent counts keyed by ``"<level>:<role>"`` (W5)."""
    subagents_total_by_status: dict[str, int] = field(default_factory=dict)
    """Terminal sub-agent counts keyed by status (``done``/``failed``/``killed``) for this session."""


def event_timestamp(event: TraceEvent) -> float:
    """Convert ``TraceEvent`` wall time from ``ts_end_ns`` / ``ts_start_ns``.

    Args:
        event (TraceEvent): Gateway or harness trace row.
    Returns:
        float: Unix epoch seconds (fractional).
    Examples:
        >>> from sevn.agent.tracing.sink import TraceEvent
        >>> ev = TraceEvent(
        ...     kind="k",
        ...     span_id="s",
        ...     parent_span_id=None,
        ...     session_id="se",
        ...     turn_id="t",
        ...     tier=None,
        ...     ts_start_ns=1_500_000_000,
        ...     ts_end_ns=2_500_000_000,
        ...     status="ok",
        ... )
        >>> event_timestamp(ev) == 2.5
        True
    """
    ts_ns = event.ts_end_ns if event.ts_end_ns is not None else event.ts_start_ns
    return ts_ns / 1_000_000_000


def normalize_complexity(raw: object) -> str | None:
    """Map trace ``attrs['complexity']`` to a tier label ``A``-``D``.

    Args:
        raw (object): Attribute value from ``gateway.triage.completed``.
    Returns:
        str | None: Normalized tier label, or ``None`` when unknown.
    Examples:
        >>> normalize_complexity("B")
        'B'
        >>> normalize_complexity("ComplexityTier.C")
        'C'
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text in _COMPLEXITY_LABELS:
        return text
    if "." in text:
        suffix = text.rsplit(".", 1)[-1]
        if suffix in _COMPLEXITY_LABELS:
            return suffix
    return None


__all__ = [
    "CHANNEL_TRACE_PREFIXES",
    "ERROR_STATUSES",
    "ESCALATION_STATUSES",
    "GATEWAY_TRACE_KINDS",
    "MISSION_TELEMETRY_TRACE_KINDS",
    "AgentActivity",
    "Alert",
    "AlertRule",
    "ChannelHealth",
    "NotificationTarget",
    "ProviderHealth",
    "SessionMissionStats",
    "event_timestamp",
    "is_channel_trace_kind",
    "is_mission_telemetry_kind",
    "normalize_complexity",
]
