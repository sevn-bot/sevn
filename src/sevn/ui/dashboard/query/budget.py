"""Budget rollups and subscription-window readers for Mission Control.

Module: sevn.ui.dashboard.query.budget
Depends: json, sqlite3, time

Exports:
    budget_summary_from_traces — rollups + regime aggregates + projections/alerts.
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

_NS_PER_DAY = 86_400 * 1_000_000_000
_DEFAULT_ALERT_THRESHOLD = 0.2


def _attrs_dict(raw: str) -> dict[str, object]:
    """Parse ``attrs_json`` defensively.

    Args:
        raw (str): Serialized JSON from ``trace_events``.

    Returns:
        dict[str, object]: Parsed mapping or empty dict.

    Examples:
        >>> _attrs_dict('{"regime": "PER_TOKEN"}')
        {'regime': 'PER_TOKEN'}
    """

    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _attr_str(attrs: dict[str, object], *keys: str) -> str | None:
    """Return the first present string attribute.

    Args:
        attrs (dict[str, object]): Trace attrs.
        keys (str): Candidate keys in priority order.

    Returns:
        str | None: First non-empty string value.

    Examples:
        >>> _attr_str({"model.id": "m1"}, "model.id", "model_id")
        'm1'
    """

    for key in keys:
        value = attrs.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _attr_number(attrs: dict[str, object], *keys: str) -> float | int | None:
    """Return the first numeric attribute.

    Args:
        attrs (dict[str, object]): Trace attrs.
        keys (str): Candidate keys in priority order.

    Returns:
        float | int | None: First numeric value.

    Examples:
        >>> _attr_number({"cost.tokens_in": 12}, "cost.tokens_in")
        12
    """

    for key in keys:
        value = attrs.get(key)
        if isinstance(value, (int, float)):
            return value
    return None


def _compute_projections(
    provider_rows: list[tuple[str, int]],
) -> dict[str, object]:
    """Derive burn-rate projections from recent ``provider.call`` rows.

    Args:
        provider_rows (list[tuple[str, int]]): ``(attrs_json, ts_start_ns)`` pairs.

    Returns:
        dict[str, object]: ``burn_rate`` and ``projected`` fields for the dashboard.

    Examples:
        >>> _compute_projections([])["burn_rate"]["calls_per_day"]
        0.0
    """

    if not provider_rows:
        return {
            "burn_rate": {
                "calls_per_day": 0.0,
                "tokens_in_per_day": 0.0,
                "tokens_out_per_day": 0.0,
            },
            "projected": {
                "monthly_calls": 0,
                "monthly_tokens_in": 0,
                "monthly_tokens_out": 0,
            },
        }

    now_ns = time.time_ns()
    week_ns = 7 * _NS_PER_DAY
    week_rows = [(raw, ts) for raw, ts in provider_rows if ts >= now_ns - week_ns]
    sample = week_rows if week_rows else provider_rows
    if not sample:
        sample = provider_rows

    oldest_ts = min(ts for _raw, ts in sample)
    span_ns = max(now_ns - oldest_ts, _NS_PER_DAY)
    span_days = span_ns / _NS_PER_DAY

    calls = len(sample)
    tokens_in = 0
    tokens_out = 0
    for raw_attrs, _ts in sample:
        attrs = _attrs_dict(raw_attrs)
        tin = _attr_number(attrs, "cost.tokens_in", "tokens_in")
        tout = _attr_number(attrs, "cost.tokens_out", "tokens_out")
        if tin is not None:
            tokens_in += int(tin)
        if tout is not None:
            tokens_out += int(tout)

    calls_per_day = calls / span_days
    tokens_in_per_day = tokens_in / span_days
    tokens_out_per_day = tokens_out / span_days
    return {
        "burn_rate": {
            "calls_per_day": round(calls_per_day, 2),
            "tokens_in_per_day": round(tokens_in_per_day, 1),
            "tokens_out_per_day": round(tokens_out_per_day, 1),
            "sample_days": round(span_days, 2),
        },
        "projected": {
            "monthly_calls": round(calls_per_day * 30),
            "monthly_tokens_in": round(tokens_in_per_day * 30),
            "monthly_tokens_out": round(tokens_out_per_day * 30),
        },
    }


def _budget_alerts(
    subscription_windows: list[dict[str, Any]],
    *,
    threshold: float = _DEFAULT_ALERT_THRESHOLD,
) -> list[dict[str, object]]:
    """Build threshold alerts for low subscription-window remaining percent.

    Args:
        subscription_windows (list[dict[str, Any]]): Window rows from summary assembly.
        threshold (float): Alert when remaining fraction is at or below this value.

    Returns:
        list[dict[str, object]]: Alert payloads for SPA and hub surfacing.

    Examples:
        >>> _budget_alerts([{"model_id": "m", "window_remaining": 0.1}])
        [{'severity': 'warning', 'model_id': 'm', 'message': 'Subscription window low (10% remaining)', 'window_remaining': 0.1}]
    """

    alerts: list[dict[str, object]] = []
    for entry in subscription_windows:
        remaining = entry.get("window_remaining")
        if remaining is None:
            continue
        try:
            frac = float(remaining)
        except (TypeError, ValueError):
            continue
        if frac > threshold:
            continue
        model_id = str(entry.get("model_id") or "unknown")
        pct = round(frac * 100)
        alerts.append(
            {
                "severity": "warning" if frac > 0.05 else "critical",
                "model_id": model_id,
                "message": f"Subscription window low ({pct}% remaining)",
                "window_remaining": frac,
            },
        )
    return alerts


def budget_summary_from_traces(conn: sqlite3.Connection) -> dict[str, object]:
    """Aggregate budget posture from trace rollups and recent ``provider.call`` rows.

    Args:
        conn (sqlite3.Connection): Open ``traces.db`` connection.

    Returns:
        dict[str, object]: Hourly rollups, per-regime totals, subscription windows.

    Examples:
        >>> import sqlite3
        >>> from sevn.agent.tracing.traces_migrate import apply_traces_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_traces_migrations(conn)
        >>> summary = budget_summary_from_traces(conn)
        >>> summary["by_regime"] == []
        True
        >>> conn.close()
    """

    rollup_rows = conn.execute(
        """
        SELECT hour_bucket_ns, kind, event_count, error_count
        FROM trace_rollups_hourly
        ORDER BY hour_bucket_ns DESC
        LIMIT 168
        """,
    ).fetchall()
    hourly_rollups = [
        {
            "hour_bucket_ns": row[0],
            "kind": row[1],
            "event_count": row[2],
            "error_count": row[3],
        }
        for row in rollup_rows
    ]

    provider_rows = conn.execute(
        """
        SELECT attrs_json, ts_start_ns
        FROM trace_events
        WHERE kind = 'provider.call'
        ORDER BY ts_start_ns DESC
        LIMIT 5000
        """,
    ).fetchall()

    by_regime: dict[str, dict[str, Any]] = {}
    subscription_windows: dict[str, dict[str, Any]] = {}

    for raw_attrs, ts_start_ns in provider_rows:
        attrs = _attrs_dict(raw_attrs)
        regime = _attr_str(attrs, "regime", "budget.regime") or "UNKNOWN"
        bucket = by_regime.setdefault(
            regime,
            {"regime": regime, "call_count": 0, "tokens_in": 0, "tokens_out": 0},
        )
        bucket["call_count"] = int(bucket["call_count"]) + 1
        tokens_in = _attr_number(attrs, "cost.tokens_in", "tokens_in")
        tokens_out = _attr_number(attrs, "cost.tokens_out", "tokens_out")
        if tokens_in is not None:
            bucket["tokens_in"] = int(bucket["tokens_in"]) + int(tokens_in)
        if tokens_out is not None:
            bucket["tokens_out"] = int(bucket["tokens_out"]) + int(tokens_out)

        if regime != "SUBSCRIPTION":
            continue
        model_id = _attr_str(attrs, "model.id", "model_id")
        if not model_id:
            continue
        window_remaining = _attr_number(
            attrs,
            "subscription_window_remaining",
            "subscription_window_remaining_percent",
            "budget.subscription_window_remaining",
        )
        window_id = _attr_str(attrs, "subscription_window_id", "budget.subscription_window_id")
        entry = subscription_windows.setdefault(
            model_id,
            {
                "model_id": model_id,
                "regime": regime,
                "subscription_window_id": window_id,
                "window_remaining": None,
                "last_ts_start_ns": ts_start_ns,
            },
        )
        if window_remaining is not None:
            entry["window_remaining"] = window_remaining
        last_ts = entry["last_ts_start_ns"]
        if isinstance(last_ts, int) and ts_start_ns >= last_ts:
            entry["last_ts_start_ns"] = ts_start_ns
            if window_id:
                entry["subscription_window_id"] = window_id

    windows_list = list(subscription_windows.values())
    projections = _compute_projections(list(provider_rows))
    alerts = _budget_alerts(windows_list)

    return {
        "hourly_rollups": hourly_rollups,
        "by_regime": list(by_regime.values()),
        "subscription_windows": windows_list,
        "projections": projections,
        "alerts": alerts,
        "alert_threshold": _DEFAULT_ALERT_THRESHOLD,
    }
