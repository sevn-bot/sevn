"""Mission Control in-process state fed by gateway trace events (`specs/24-dashboard.md`).

Module: sevn.gateway.mission.mission_state
Depends: sevn.gateway.mission.mission_state_models, sevn.gateway.mission.mission_state_snapshots

Exports:
    MissionControlState — aggregated Mission Control state.
Examples:
    >>> isinstance(True, bool)
    True
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from loguru import logger

from sevn.agent.triager.models import COMPLEXITY_TIERS
from sevn.gateway.mission.mission_state_models import (
    ERROR_STATUSES,
    ESCALATION_STATUSES,
    GATEWAY_TRACE_KINDS,
    AgentActivity,
    Alert,
    AlertRule,
    ChannelHealth,
    NotificationTarget,
    ProviderHealth,
    SessionMissionStats,
    event_timestamp,
    is_channel_trace_kind,
    normalize_complexity,
)
from sevn.gateway.mission.mission_state_snapshots import MissionControlSnapshotsMixin
from sevn.gateway.mission.mission_trace_sink import (
    MissionControlTraceSink,
    create_mission_trace_sink,
    detach_mission_trace_sink,
    resolve_mission_control_state,
)

if TYPE_CHECKING:
    from sevn.agent.tracing.sink import TraceEvent

HIGH_LATENCY_ALERT_THRESHOLD_MS = 30_000
"""``high_latency`` alert threshold (ms); raised from 5 s to reduce log noise (D3)."""

CRITICAL_ALERT_CONSECUTIVE_BREACHES = 3
"""``channel_down`` / ``high_error_rate`` must breach this many times before paging critical (D4)."""


class MissionControlState(MissionControlSnapshotsMixin):
    """Centralized Mission Control state (providers, channels, gateway session metrics)."""

    def __init__(
        self,
        max_activity: int = 1000,
        max_alerts: int = 200,
        *,
        token_budget_alerts: bool = True,
    ) -> None:
        """Initialize Mission Control aggregates.

        Args:
            max_activity (int): Max activity-feed rows retained.
            max_alerts (int): Max alert rows retained.
            token_budget_alerts (bool): When False, omit the cumulative
                ``token_budget`` alert rule (e.g. the active provider is a
                subscription plan where per-token totals are not the limit).
        Examples:
            >>> MissionControlState().get_gateway_metrics()["total_sessions"] == 0
            True
            >>> rules = MissionControlState(token_budget_alerts=False).list_alert_rules()
            >>> any(r["name"] == "token_budget" for r in rules)
            False
        """
        self._providers: dict[str, ProviderHealth] = {}
        self._channels: dict[str, ChannelHealth] = {}
        self._activity: list[AgentActivity] = []
        self._max_activity = max_activity
        self._alerts: list[Alert] = []
        self._max_alerts = max_alerts
        self._alert_rules: list[AlertRule] = [
            AlertRule(
                "high_error_rate",
                "error_rate",
                threshold=0.1,
                severity="critical",
                consecutive_breaches=CRITICAL_ALERT_CONSECUTIVE_BREACHES,
            ),
            AlertRule(
                "high_latency",
                "latency",
                threshold=HIGH_LATENCY_ALERT_THRESHOLD_MS,
                severity="warning",
            ),
            AlertRule(
                "channel_down",
                "channel_down",
                threshold=1,
                severity="critical",
                consecutive_breaches=CRITICAL_ALERT_CONSECUTIVE_BREACHES,
            ),
            AlertRule("provider_down", "provider_down", threshold=1, severity="critical"),
        ]
        if token_budget_alerts:
            self._alert_rules.insert(
                2,
                AlertRule("token_budget", "token_usage", threshold=100_000, severity="warning"),
            )
        self._notification_targets: list[NotificationTarget] = [
            NotificationTarget("default_log", "log"),
        ]
        self._start_time = time.monotonic()
        self._total_requests = 0
        self._total_errors = 0
        self._total_tokens = 0
        self._latency_samples: list[float] = []
        self._minute_buckets: list[dict[str, Any]] = []
        self._max_buckets = 60
        self._sessions: dict[str, SessionMissionStats] = {}
        self._complexity_counts: dict[str, int] = {t.value: 0 for t in COMPLEXITY_TIERS}
        self._gateway_turns = 0
        self._gateway_errors = 0
        self._gateway_escalations = 0
        self._gateway_disregards = 0
        self._subagent_running: dict[str, int] = {}
        self._subagent_total: dict[str, int] = {"done": 0, "failed": 0, "killed": 0}
        self._turn_stage_latencies_ms: dict[str, float] = {}
        self._alert_breach_state: dict[str, tuple[int, float]] = {}
        """Per-rule consecutive breach count and window start (monotonic seconds)."""

    def _session(self, session_id: str) -> SessionMissionStats:
        """Return or create per-session mission stats.

        Args:
            session_id (str): Gateway session id.
        Returns:
            SessionMissionStats: Mutable per-session row.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        row = self._sessions.get(session_id)
        if row is None:
            row = SessionMissionStats(session_id=session_id)
            self._sessions[session_id] = row
        return row

    async def apply_trace_event(self, event: TraceEvent) -> None:
        """Update session metrics and activity feed from one gateway trace row.

        Args:
            event (TraceEvent): Row whose ``kind`` is in :data:`GATEWAY_TRACE_KINDS`.
        Examples:
            >>> import asyncio
            >>> from sevn.agent.tracing.sink import TraceEvent
            >>> st = MissionControlState()
            >>> ev = TraceEvent(
            ...     kind="gateway.triage.completed",
            ...     span_id="a",
            ...     parent_span_id=None,
            ...     session_id="s1",
            ...     turn_id="t1",
            ...     tier=None,
            ...     ts_start_ns=1_000_000_000,
            ...     ts_end_ns=2_000_000_000,
            ...     status="completed",
            ...     attrs={"complexity": "A"},
            ... )
            >>> asyncio.run(st.apply_trace_event(ev)) is None
            True
            >>> st.get_gateway_metrics()["total_sessions"] == 1
            True
        """
        if event.kind not in GATEWAY_TRACE_KINDS:
            return
        ts = event_timestamp(event)
        if event.kind == "gateway.boot":
            self.record_activity(
                AgentActivity(
                    timestamp=ts,
                    event_type="gateway",
                    session_id="",
                    detail=f"boot/{event.status or 'ok'}",
                    metadata={},
                ),
            )
            return
        session_id = event.session_id
        if not session_id:
            return
        row = self._session(session_id)
        row.last_activity_at = ts
        if event.kind == "gateway.triage.completed":
            self._gateway_turns += 1
            row.turn_count += 1
            complexity = normalize_complexity(event.attrs.get("complexity"))
            if complexity is not None:
                row.last_complexity = complexity
                self._complexity_counts[complexity] = self._complexity_counts.get(complexity, 0) + 1
            detail = f"triage/{event.status}"
            if complexity:
                detail = f"triage/{complexity}/{event.status}"
            self.record_activity(
                AgentActivity(
                    timestamp=ts,
                    event_type="triage",
                    session_id=session_id,
                    detail=detail,
                    metadata={"turn_id": event.turn_id, "complexity": complexity or ""},
                ),
            )
            return
        if event.kind == "gateway.triage.disregard":
            self._gateway_disregards += 1
            row.disregards += 1
            self.record_activity(
                AgentActivity(
                    timestamp=ts,
                    event_type="disregard",
                    session_id=session_id,
                    detail="triage/disregard",
                    metadata={"turn_id": event.turn_id},
                ),
            )
            return
        if event.kind == "gateway.executor.b_completed":
            status = (event.status or "").strip().lower()
            if status in ERROR_STATUSES:
                self._gateway_errors += 1
                row.errors += 1
                self.record_activity(
                    AgentActivity(
                        timestamp=ts,
                        event_type="error",
                        session_id=session_id,
                        detail=f"tier_b/{status}",
                        metadata={"turn_id": event.turn_id},
                    ),
                )
            elif status in ESCALATION_STATUSES:
                self._gateway_escalations += 1
                row.escalations += 1
                self.record_activity(
                    AgentActivity(
                        timestamp=ts,
                        event_type="escalation",
                        session_id=session_id,
                        detail=f"tier_b/{status}",
                        metadata={"turn_id": event.turn_id},
                    ),
                )
            else:
                self.record_activity(
                    AgentActivity(
                        timestamp=ts,
                        event_type="tier_b",
                        session_id=session_id,
                        detail=f"tier_b/{status or 'unknown'}",
                        metadata={
                            "turn_id": event.turn_id,
                            "final_count": event.attrs.get("final_count"),
                        },
                    ),
                )
            self._total_requests += 1
            self._check_alerts()
        return

    async def apply_telemetry_trace_event(self, event: TraceEvent) -> None:
        """Update provider/channel runtime maps from telemetry trace rows.

        Args:
            event (TraceEvent): ``provider.call`` or ``channel.*`` lifecycle row.

        Examples:
            >>> import asyncio
            >>> from sevn.agent.tracing.sink import TraceEvent
            >>> st = MissionControlState()
            >>> ev = TraceEvent(
            ...     kind="provider.call",
            ...     span_id="p1",
            ...     parent_span_id=None,
            ...     session_id="s1",
            ...     turn_id="t1",
            ...     tier="B",
            ...     ts_start_ns=1,
            ...     ts_end_ns=2,
            ...     status="ok",
            ...     attrs={
            ...         "model.id": "anthropic/claude-sonnet-4-6",
            ...         "cost.tokens_in": 10,
            ...         "cost.tokens_out": 5,
            ...         "latency_ms": 1.0,
            ...     },
            ... )
            >>> asyncio.run(st.apply_telemetry_trace_event(ev)) is None
            True
        """
        if event.kind == "provider.call":
            attrs = event.attrs
            model_id = str(attrs.get("model.id") or attrs.get("model_id") or "unknown")
            provider_name = model_id.split("/", 1)[0] if "/" in model_id else model_id
            raw_in = attrs.get("cost.tokens_in", attrs.get("input_tokens", 0))
            raw_out = attrs.get("cost.tokens_out", attrs.get("output_tokens", 0))
            tokens_in = int(raw_in) if isinstance(raw_in, (int, float)) else 0
            tokens_out = int(raw_out) if isinstance(raw_out, (int, float)) else 0
            raw_latency = attrs.get("latency_ms", 0.0)
            latency_ms = float(raw_latency) if isinstance(raw_latency, (int, float)) else 0.0
            if latency_ms <= 0 and event.ts_end_ns is not None:
                latency_ms = max(0.0, (event.ts_end_ns - event.ts_start_ns) / 1_000_000.0)
            status = (event.status or "").strip().lower()
            is_error = status in ERROR_STATUSES
            session_id = event.session_id or ""
            self.record_llm_request(
                session_id,
                provider_name,
                model_id,
                duration_ms=latency_ms,
                tokens=tokens_in + tokens_out,
            )
            if is_error:
                self.update_provider(provider_name, error=True)
            return
        if is_channel_trace_kind(event.kind):
            parts = event.kind.split(".")
            channel_name = parts[1] if len(parts) >= 2 else event.kind
            adapter_type = channel_name
            self.register_channel(channel_name, adapter_type=adapter_type)
            status = (event.status or "").strip().lower()
            if event.kind.endswith(".start"):
                self.update_channel(channel_name, connected=True, connection_state="connected")
            elif event.kind.endswith(".stop"):
                self.update_channel(
                    channel_name,
                    connected=False,
                    connection_state="disconnected",
                )
            elif event.kind.endswith(".poll.cycle"):
                self.update_channel(channel_name, message=True)
            elif status in ERROR_STATUSES:
                detail = str(event.attrs.get("error") or event.status or "error")
                self.update_channel(channel_name, error=True, error_detail=detail)
            return
        if event.kind in ("subagent_spawned", "subagent_finished", "subagent_killed"):
            await self._apply_subagent_telemetry(event)
        return

    async def _apply_subagent_telemetry(self, event: TraceEvent) -> None:
        """Update sub-agent running/total counters and activity feed (W5.2).

        Args:
            event (TraceEvent): ``subagent_spawned`` / ``subagent_finished`` /
                ``subagent_killed`` row.

        Examples:
            >>> import asyncio
            >>> from sevn.agent.tracing.sink import TraceEvent
            >>> st = MissionControlState()
            >>> ev = TraceEvent(
            ...     kind="subagent_spawned",
            ...     span_id="sub-a1",
            ...     parent_span_id=None,
            ...     session_id="s1",
            ...     turn_id="t1",
            ...     tier=None,
            ...     ts_start_ns=1,
            ...     ts_end_ns=2,
            ...     status="pending",
            ...     attrs={"subagent.id": "a1", "subagent.level": 1, "subagent.role": "tier_b"},
            ... )
            >>> asyncio.run(st._apply_subagent_telemetry(ev)) is None
            True
        """
        attrs = event.attrs
        raw_level = attrs.get("subagent.level")
        if isinstance(raw_level, int):
            level = raw_level
        elif isinstance(raw_level, (str, float)):
            try:
                level = int(raw_level)
            except (TypeError, ValueError):
                level = 0
        else:
            level = 0
        role = str(attrs.get("subagent.role") or "unknown")
        key = f"{level}:{role}"
        ts = event_timestamp(event)
        session_id = event.session_id or ""
        row = self._session(session_id) if session_id else None
        if event.kind == "subagent_spawned":
            self._subagent_running[key] = self._subagent_running.get(key, 0) + 1
            if row is not None:
                row.subagents_running_by_level_role[key] = (
                    row.subagents_running_by_level_role.get(key, 0) + 1
                )
                row.last_activity_at = ts
            self.record_activity(
                AgentActivity(
                    timestamp=ts,
                    event_type="subagent",
                    session_id=session_id,
                    detail=f"spawned/{level}/{role}",
                    metadata={
                        "subagent_id": attrs.get("subagent.id"),
                        "specialist": attrs.get("subagent.specialist"),
                    },
                ),
            )
            return
        status = str(attrs.get("subagent.status") or event.status or "").strip().lower()
        self._subagent_running[key] = max(0, self._subagent_running.get(key, 0) - 1)
        if status in self._subagent_total:
            self._subagent_total[status] = self._subagent_total.get(status, 0) + 1
        if row is not None:
            row.subagents_running_by_level_role[key] = max(
                0,
                row.subagents_running_by_level_role.get(key, 0) - 1,
            )
            if status:
                row.subagents_total_by_status[status] = (
                    row.subagents_total_by_status.get(status, 0) + 1
                )
            row.last_activity_at = ts
        detail_kind = "killed" if event.kind == "subagent_killed" else "finished"
        self.record_activity(
            AgentActivity(
                timestamp=ts,
                event_type="subagent",
                session_id=session_id,
                detail=f"{detail_kind}/{level}/{role}/{status}",
                metadata={
                    "subagent_id": attrs.get("subagent.id"),
                    "specialist": attrs.get("subagent.specialist"),
                },
            ),
        )

    def register_provider(self, name: str) -> None:
        """Ensure ``name`` exists in the provider health map.

        Args:
            name (str): Provider id.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        if name not in self._providers:
            self._providers[name] = ProviderHealth(name=name)

    def update_provider(
        self,
        name: str,
        *,
        available: bool | None = None,
        latency_ms: float = 0,
        tokens: int = 0,
        error: bool = False,
    ) -> None:
        """Record one provider probe or request outcome.

        Args:
            name (str): Provider id.
            available (bool | None): Optional availability flag.
            latency_ms (float): Observed latency in milliseconds.
            tokens (int): Token count for this request.
            error (bool): Whether the request failed.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        p = self._providers.get(name)
        if not p:
            p = ProviderHealth(name=name)
            self._providers[name] = p
        if available is not None:
            p.available = available
        p.last_check = time.monotonic()
        p.total_requests += 1
        self._total_requests += 1
        if latency_ms > 0:
            p.latency_ms = latency_ms
            self._latency_samples.append(latency_ms)
            if len(self._latency_samples) > 500:
                self._latency_samples = self._latency_samples[-500:]
        if tokens > 0:
            p.total_tokens += tokens
            self._total_tokens += tokens
        if error:
            p.error_count += 1
            self._total_errors += 1
        self._check_alerts()

    def record_turn_stage_latency_ms(self, stage: str, latency_ms: float) -> None:
        """Record per-stage turn latency for ``high_latency`` attribution (D3).

        Args:
            stage (str): Turn stage label (for example ``triager``, ``tool-loop``,
                ``upstream``).
            latency_ms (float): Observed stage duration in milliseconds.

        Examples:
            >>> st = MissionControlState()
            >>> st.record_turn_stage_latency_ms("upstream", 120_000.0)
            >>> st._turn_stage_latencies_ms["upstream"]
            120000.0
        """
        normalized = stage.strip()
        if not normalized:
            return
        self._turn_stage_latencies_ms[normalized] = float(latency_ms)

    def clear_turn_stage_latencies_ms(self) -> None:
        """Drop per-turn stage samples so alert attribution stays turn-scoped (D3).

        Examples:
            >>> st = MissionControlState()
            >>> st.record_turn_stage_latency_ms("upstream", 1.0)
            >>> st.clear_turn_stage_latencies_ms()
            >>> st._turn_stage_latencies_ms
            {}
        """
        self._turn_stage_latencies_ms.clear()

    def _stalling_stage_for_latency(self, latency_ms: float) -> str | None:
        """Return the stage name best matching a latency sample.

        Args:
            latency_ms (float): Latest latency sample in milliseconds.

        Returns:
            str | None: Stage label when stage timings were recorded.

        Examples:
            >>> st = MissionControlState()
            >>> st.record_turn_stage_latency_ms("upstream", 120_000.0)
            >>> st._stalling_stage_for_latency(120_000.0)
            'upstream'
        """
        if not self._turn_stage_latencies_ms:
            return None
        for stage, sample_ms in self._turn_stage_latencies_ms.items():
            if sample_ms == latency_ms:
                return stage
        return None

    def register_channel(self, name: str, adapter_type: str = "") -> None:
        """Ensure ``name`` exists in the channel health map.

        Args:
            name (str): Channel id.
            adapter_type (str): Adapter label (for example ``telegram``).
        Examples:
            >>> isinstance(True, bool)
            True
        """
        if name not in self._channels:
            self._channels[name] = ChannelHealth(name=name, adapter_type=adapter_type)

    def update_channel(
        self,
        name: str,
        *,
        connected: bool | None = None,
        connection_state: str | None = None,
        message: bool = False,
        error: bool = False,
        error_detail: str = "",
        reconnect: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record channel adapter connectivity or traffic.

        Args:
            name (str): Channel id.
            connected (bool | None): Whether the adapter is connected.
            connection_state (str | None): Explicit connection state label.
            message (bool): Increment message counter when true.
            error (bool): Record a channel error when true.
            error_detail (str): Last error text.
            reconnect (bool): Increment reconnect counter when true.
            metadata (dict[str, Any] | None): Extra metadata merged into the row.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        c = self._channels.get(name)
        if not c:
            c = ChannelHealth(name=name)
            self._channels[name] = c
        if connected is not None:
            c.connected = connected
            if connected:
                c.connection_state = "connected"
            elif c.connection_state == "connected":
                c.connection_state = "disconnected"
        if connection_state is not None:
            c.connection_state = connection_state
        if message:
            c.message_count += 1
            c.last_message_at = time.monotonic()
        if error:
            c.error_count += 1
            c.last_error_at = time.monotonic()
            c.last_error = error_detail
            if c.connection_state == "connected":
                c.connection_state = "degraded"
        if reconnect:
            c.reconnect_count += 1
            c.connection_state = "connecting"
        if metadata:
            c.metadata.update(metadata)
        self._check_alerts()

    def record_activity(self, activity: AgentActivity) -> None:
        """Append one activity-feed row (bounded by ``max_activity``).

        Args:
            activity (AgentActivity): Feed row to append.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        self._activity.append(activity)
        if len(self._activity) > self._max_activity:
            self._activity = self._activity[-self._max_activity :]

    def record_llm_request(
        self,
        session_id: str,
        provider: str,
        model: str,
        duration_ms: float = 0,
        tokens: int = 0,
    ) -> None:
        """Record an LLM request in the activity feed and provider counters.

        Args:
            session_id (str): Session id.
            provider (str): Provider name.
            model (str): Model id.
            duration_ms (float): Request duration in milliseconds.
            tokens (int): Token count.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        self.record_activity(
            AgentActivity(
                timestamp=time.time(),
                event_type="llm_request",
                session_id=session_id,
                detail=f"{provider}/{model}",
                metadata={"tokens": tokens},
                duration_ms=duration_ms,
            ),
        )
        self.update_provider(provider, latency_ms=duration_ms, tokens=tokens)

    def record_tool_call(self, session_id: str, tool: str, duration_ms: float = 0) -> None:
        """Record a tool invocation in the activity feed.

        Args:
            session_id (str): Session id.
            tool (str): Tool name.
            duration_ms (float): Duration in milliseconds.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        self.record_activity(
            AgentActivity(
                timestamp=time.time(),
                event_type="tool_call",
                session_id=session_id,
                detail=tool,
                duration_ms=duration_ms,
            ),
        )

    def record_error(self, session_id: str, error: str, source: str = "") -> None:
        """Record an error activity row and optional provider error counter.

        Args:
            session_id (str): Session id.
            error (str): Error summary.
            source (str): Provider or subsystem name.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        self.record_activity(
            AgentActivity(
                timestamp=time.time(),
                event_type="error",
                session_id=session_id,
                detail=error,
                metadata={"source": source},
            ),
        )
        if source:
            self.update_provider(source, error=True)

    def _record_alert_breach(self, rule: AlertRule, *, now_mono: float) -> int:
        """Increment consecutive breach count for ``rule`` within its debounce window.

        Args:
            rule (AlertRule): Rule being evaluated.
            now_mono (float): Monotonic clock sample.

        Returns:
            int: Consecutive breach count after this sample.
        Examples:
            >>> st = MissionControlState()
            >>> rule = st._alert_rules[0]
            >>> st._record_alert_breach(rule, now_mono=0.0)
            1
        """
        count, window_start = self._alert_breach_state.get(rule.name, (0, now_mono))
        if count == 0 or (now_mono - window_start) > rule.window_seconds:
            count = 1
            window_start = now_mono
        else:
            count += 1
        self._alert_breach_state[rule.name] = (count, window_start)
        return count

    def _clear_alert_breach(self, rule_name: str) -> None:
        """Reset consecutive breach tracking for ``rule_name``.

        Args:
            rule_name (str): Alert rule name.

        Examples:
            >>> st = MissionControlState()
            >>> st._clear_alert_breach("channel_down")
        """
        self._alert_breach_state.pop(rule_name, None)

    def _check_alerts(self) -> None:
        """Evaluate alert rules against current metrics.

        Examples:
            >>> isinstance(True, bool)
            True
        """
        now_mono = time.monotonic()
        now_wall = time.time()
        for rule in self._alert_rules:
            if not rule.enabled or rule.silenced_until > now_mono:
                continue
            value = self._get_metric(rule.metric)
            if value is None:
                continue
            if value < rule.threshold:
                self._clear_alert_breach(rule.name)
                continue
            breach_count = self._record_alert_breach(rule, now_mono=now_mono)
            if breach_count < rule.consecutive_breaches:
                continue
            recent = [
                a
                for a in self._alerts
                if a.rule_name == rule.name and now_wall - a.timestamp < rule.window_seconds
            ]
            if not recent:
                stage_suffix = ""
                if rule.name == "high_latency":
                    stage = self._stalling_stage_for_latency(value)
                    if stage:
                        stage_suffix = f" (stalling stage: {stage})"
                self._fire_alert(
                    Alert(
                        rule_name=rule.name,
                        severity=rule.severity,
                        message=(
                            f"{rule.name}: {rule.metric} = {value:.2f} "
                            f"(threshold: {rule.threshold}){stage_suffix}"
                        ),
                        timestamp=now_wall,
                    ),
                )

    def _get_metric(self, metric: str) -> float | None:
        """Resolve alert metric value.

        Args:
            metric (str): Metric name (for example ``error_rate``).
        Returns:
            float | None: Current metric value, or ``None`` when unknown.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        if metric == "error_rate":
            if self._total_requests == 0:
                return 0.0
            return self._total_errors / self._total_requests
        if metric == "latency":
            if not self._latency_samples:
                return 0.0
            return self._latency_samples[-1]
        if metric == "token_usage":
            return float(self._total_tokens)
        if metric == "channel_down":
            return float(
                sum(
                    1
                    for c in self._channels.values()
                    if c.connection_state in ("disconnected", "error")
                ),
            )
        if metric == "provider_down":
            return float(sum(1 for p in self._providers.values() if not p.available))
        return None

    def _fire_alert(self, alert: Alert) -> None:
        """Persist and log one alert.

        Args:
            alert (Alert): Triggered alert row.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        self._alerts.append(alert)
        if len(self._alerts) > self._max_alerts:
            self._alerts = self._alerts[-self._max_alerts :]
        for target in self._notification_targets:
            if not target.enabled or target.target_type != "log":
                continue
            log_fn = logger.error if alert.severity == "critical" else logger.warning
            log_fn("Alert [{}]: {}", alert.severity, alert.message)

    def acknowledge_alert(self, index: int) -> bool:
        """Mark alert at ``index`` acknowledged.

        Args:
            index (int): Alert list index.
        Returns:
            bool: True when the index was valid.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        if 0 <= index < len(self._alerts):
            self._alerts[index].acknowledged = True
            return True
        return False

    def add_alert_rule(self, rule: AlertRule) -> None:
        """Add or replace an alert rule by name.

        Args:
            rule (AlertRule): Rule definition.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        self._alert_rules = [r for r in self._alert_rules if r.name != rule.name]
        self._alert_rules.append(rule)

    def remove_alert_rule(self, name: str) -> bool:
        """Remove alert rule ``name`` when present.

        Args:
            name (str): Rule name.
        Returns:
            bool: True when a rule was removed.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        before = len(self._alert_rules)
        self._alert_rules = [r for r in self._alert_rules if r.name != name]
        return len(self._alert_rules) < before

    def silence_rule(self, name: str, duration_seconds: float) -> bool:
        """Silence rule ``name`` for ``duration_seconds``.

        Args:
            name (str): Rule name.
            duration_seconds (float): Silence duration in seconds.
        Returns:
            bool: True when the rule existed.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        for rule in self._alert_rules:
            if rule.name == name:
                rule.silenced_until = time.monotonic() + duration_seconds
                logger.info("Silenced alert rule '{}' for {}s", name, duration_seconds)
                return True
        return False

    def add_notification_target(self, target: NotificationTarget) -> None:
        """Add or replace a notification target by name.

        Args:
            target (NotificationTarget): Target row.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        self._notification_targets = [
            t for t in self._notification_targets if t.name != target.name
        ]
        self._notification_targets.append(target)

    def remove_notification_target(self, name: str) -> bool:
        """Remove notification target ``name`` when present.

        Args:
            name (str): Target name.
        Returns:
            bool: True when a target was removed.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        before = len(self._notification_targets)
        self._notification_targets = [t for t in self._notification_targets if t.name != name]
        return len(self._notification_targets) < before


__all__ = [
    "GATEWAY_TRACE_KINDS",
    "AgentActivity",
    "Alert",
    "AlertRule",
    "ChannelHealth",
    "MissionControlState",
    "MissionControlTraceSink",
    "NotificationTarget",
    "ProviderHealth",
    "SessionMissionStats",
    "create_mission_trace_sink",
    "detach_mission_trace_sink",
    "resolve_mission_control_state",
]
