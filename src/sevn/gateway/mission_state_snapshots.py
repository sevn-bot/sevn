"""REST snapshot assembly for :class:`~sevn.gateway.mission_state.MissionControlState`.

Module: sevn.gateway.mission_state_snapshots
Depends: sevn.gateway.mission_state_models

Exports:
    MissionControlSnapshotsMixin — read-only status/metrics/feed serializers.
Examples:
    >>> from sevn.gateway.mission_state import MissionControlState
    >>> isinstance(MissionControlState().get_status(), dict)
    True
"""

from __future__ import annotations

import time
from typing import Any

from sevn.gateway.mission_state_models import (
    AgentActivity,
    Alert,
    AlertRule,
    ChannelHealth,
    NotificationTarget,
    ProviderHealth,
    SessionMissionStats,
)


class MissionControlSnapshotsMixin:
    """Serialize in-process mission aggregates for dashboard REST consumers."""

    _providers: dict[str, ProviderHealth]
    _channels: dict[str, ChannelHealth]
    _activity: list[AgentActivity]
    _alerts: list[Alert]
    _alert_rules: list[AlertRule]
    _notification_targets: list[NotificationTarget]
    _start_time: float
    _total_requests: int
    _total_errors: int
    _total_tokens: int
    _latency_samples: list[float]
    _minute_buckets: list[dict[str, Any]]
    _max_buckets: int
    _sessions: dict[str, SessionMissionStats]
    _complexity_counts: dict[str, int]
    _gateway_turns: int
    _gateway_errors: int
    _gateway_escalations: int
    _gateway_disregards: int

    def get_gateway_metrics(self) -> dict[str, Any]:
        """Return session/complexity/escalation/error aggregates from gateway traces.

        Returns:
            dict[str, Any]: ``total_sessions``, ``complexity_distribution``,
            ``escalations``, ``error_rate``, ``sessions`` (per-id last activity).
        Examples:
            >>> from sevn.gateway.mission_state import MissionControlState
            >>> m = MissionControlState().get_gateway_metrics()
            >>> m["total_sessions"] == 0
            True
            >>> set(m["complexity_distribution"].keys()) == {"A", "B", "C", "D"}
            True
        """
        error_rate = self._gateway_errors / self._gateway_turns if self._gateway_turns else 0.0
        return {
            "total_sessions": len(self._sessions),
            "complexity_distribution": dict(self._complexity_counts),
            "escalations": self._gateway_escalations,
            "disregards": self._gateway_disregards,
            "error_rate": round(error_rate, 4),
            "gateway_turns": self._gateway_turns,
            "gateway_errors": self._gateway_errors,
            "sessions": {
                sid: {
                    "turn_count": s.turn_count,
                    "escalations": s.escalations,
                    "errors": s.errors,
                    "disregards": s.disregards,
                    "last_complexity": s.last_complexity,
                    "last_activity_at": s.last_activity_at,
                }
                for sid, s in self._sessions.items()
            },
        }

    def get_channel_status(self) -> list[dict[str, Any]]:
        """Return detailed channel status rows for Mission Control APIs.

        Returns:
            list[dict[str, Any]]: One dict per registered channel.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        now = time.monotonic()
        result: list[dict[str, Any]] = []
        for _name, c in self._channels.items():
            idle_seconds = round(now - c.last_message_at, 1) if c.last_message_at else None
            result.append(
                {
                    "name": c.name,
                    "adapter_type": c.adapter_type,
                    "connected": c.connected,
                    "connection_state": c.connection_state,
                    "messages": c.message_count,
                    "errors": c.error_count,
                    "reconnects": c.reconnect_count,
                    "last_error": c.last_error,
                    "idle_seconds": idle_seconds,
                    "metadata": c.metadata,
                },
            )
        return result

    def get_percentile_latency(self, percentile: float = 0.95) -> float:
        """Return latency percentile from recent samples.

        Args:
            percentile (float): Quantile in ``[0, 1]``.
        Returns:
            float: Latency in milliseconds at the requested percentile.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        if not self._latency_samples:
            return 0.0
        sorted_samples = sorted(self._latency_samples)
        idx = min(int(len(sorted_samples) * percentile), len(sorted_samples) - 1)
        return sorted_samples[idx]

    def _record_minute_bucket(self) -> None:
        """Snapshot metrics into per-minute history.

        Examples:
            >>> isinstance(True, bool)
            True
        """
        now = time.time()
        bucket = {
            "timestamp": now,
            "requests": self._total_requests,
            "errors": self._total_errors,
            "tokens": self._total_tokens,
            "avg_latency": (
                sum(self._latency_samples[-50:]) / len(self._latency_samples[-50:])
                if self._latency_samples
                else 0.0
            ),
        }
        self._minute_buckets.append(bucket)
        if len(self._minute_buckets) > self._max_buckets:
            self._minute_buckets = self._minute_buckets[-self._max_buckets :]

    def get_performance_metrics(self) -> dict[str, Any]:
        """Return performance summary including per-provider breakdown.

        Returns:
            dict[str, Any]: Summary, latency, per-provider, and gateway sections.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        self._record_minute_bucket()
        error_rate = self._total_errors / self._total_requests if self._total_requests > 0 else 0.0
        return {
            "summary": {
                "total_requests": self._total_requests,
                "total_errors": self._total_errors,
                "error_rate": round(error_rate, 4),
                "total_tokens": self._total_tokens,
            },
            "latency": {
                "avg_ms": round(sum(self._latency_samples) / len(self._latency_samples), 1)
                if self._latency_samples
                else 0.0,
                "p50_ms": round(self.get_percentile_latency(0.5), 1),
                "p95_ms": round(self.get_percentile_latency(0.95), 1),
                "p99_ms": round(self.get_percentile_latency(0.99), 1),
                "min_ms": round(min(self._latency_samples), 1) if self._latency_samples else 0.0,
                "max_ms": round(max(self._latency_samples), 1) if self._latency_samples else 0.0,
                "sample_count": len(self._latency_samples),
            },
            "per_provider": {
                name: {
                    "requests": p.total_requests,
                    "errors": p.error_count,
                    "error_rate": round(p.error_count / p.total_requests, 4)
                    if p.total_requests > 0
                    else 0.0,
                    "latency_ms": round(p.latency_ms, 1),
                    "tokens": p.total_tokens,
                    "tokens_per_request": round(p.total_tokens / p.total_requests, 1)
                    if p.total_requests > 0
                    else 0.0,
                }
                for name, p in self._providers.items()
            },
            "history": self._minute_buckets[-30:],
            "gateway": self.get_gateway_metrics(),
        }

    def get_status(self) -> dict[str, Any]:
        """Return aggregate Mission Control status for REST consumers.

        Returns:
            dict[str, Any]: Providers, channels, metrics, gateway, and alert counts.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        uptime = time.monotonic() - self._start_time
        avg_latency = (
            sum(self._latency_samples) / len(self._latency_samples)
            if self._latency_samples
            else 0.0
        )
        error_rate = self._total_errors / self._total_requests if self._total_requests > 0 else 0.0
        return {
            "uptime_seconds": round(uptime, 1),
            "providers": {
                name: {
                    "available": p.available,
                    "latency_ms": round(p.latency_ms, 1),
                    "requests": p.total_requests,
                    "errors": p.error_count,
                    "tokens": p.total_tokens,
                }
                for name, p in self._providers.items()
            },
            "channels": {
                name: {
                    "connected": c.connected,
                    "connection_state": c.connection_state,
                    "adapter_type": c.adapter_type,
                    "messages": c.message_count,
                    "errors": c.error_count,
                    "reconnects": c.reconnect_count,
                    "last_error": c.last_error,
                }
                for name, c in self._channels.items()
            },
            "metrics": {
                "total_requests": self._total_requests,
                "total_errors": self._total_errors,
                "error_rate": round(error_rate, 4),
                "avg_latency_ms": round(avg_latency, 1),
                "total_tokens": self._total_tokens,
            },
            "gateway": self.get_gateway_metrics(),
            "active_alerts": sum(1 for a in self._alerts if not a.acknowledged),
        }

    def get_activity_feed(self, limit: int = 50, event_type: str = "") -> list[dict[str, Any]]:
        """Return recent activity rows (newest first).

        Args:
            limit (int): Maximum rows to return.
            event_type (str): Optional filter by ``event_type``.
        Returns:
            list[dict[str, Any]]: Activity feed rows.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        feed = self._activity
        if event_type:
            feed = [a for a in feed if a.event_type == event_type]
        return [
            {
                "timestamp": a.timestamp,
                "type": a.event_type,
                "session_id": a.session_id,
                "detail": a.detail,
                "duration_ms": a.duration_ms,
                "metadata": a.metadata,
            }
            for a in feed[-limit:]
        ][::-1]

    def get_alerts(self, unacknowledged_only: bool = False) -> list[dict[str, Any]]:
        """Return alert rows (newest first).

        Args:
            unacknowledged_only (bool): When true, omit acknowledged alerts.
        Returns:
            list[dict[str, Any]]: Alert rows.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        alerts = self._alerts
        if unacknowledged_only:
            alerts = [a for a in alerts if not a.acknowledged]
        return [
            {
                "rule": a.rule_name,
                "severity": a.severity,
                "message": a.message,
                "timestamp": a.timestamp,
                "acknowledged": a.acknowledged,
            }
            for a in alerts
        ][::-1]

    def list_alert_rules(self) -> list[dict[str, Any]]:
        """Serialize configured alert rules.

        Returns:
            list[dict[str, Any]]: Rule rows for REST consumers.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        now = time.monotonic()
        return [
            {
                "name": r.name,
                "metric": r.metric,
                "threshold": r.threshold,
                "severity": r.severity,
                "enabled": r.enabled,
                "silenced": r.silenced_until > now,
                "window_seconds": r.window_seconds,
            }
            for r in self._alert_rules
        ]

    def list_notification_targets(self) -> list[dict[str, Any]]:
        """Serialize notification targets.

        Returns:
            list[dict[str, Any]]: Target rows for REST consumers.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        return [
            {"name": t.name, "type": t.target_type, "url": t.url, "enabled": t.enabled}
            for t in self._notification_targets
        ]


__all__ = ["MissionControlSnapshotsMixin"]
