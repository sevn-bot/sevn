"""Prometheus text exposition for the gateway (`specs/17-gateway.md`, `specs/24-dashboard.md`).

Exports:
    render_gateway_metrics — ``text/plain; version=0.0.4`` body for ``GET /metrics``.
"""

from __future__ import annotations


def _format_label_value(value: str) -> str:
    """Escape one Prometheus label value.

    Args:
        value (str): Raw label text.

    Returns:
        str: Escaped label value safe for exposition text.

    Examples:
        >>> _format_label_value("tier_b")
        'tier_b'
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')


def render_gateway_metrics(
    *,
    active_sessions: int = 0,
    active_runs: int = 0,
    subagents_running: dict[tuple[int, str], int] | None = None,
    subagents_total: dict[str, int] | None = None,
) -> str:
    """Return Prometheus exposition text for gateway health counters.

    Args:
        active_sessions (int, optional): Open gateway sessions. Defaults to 0.
        active_runs (int, optional): In-flight runs. Defaults to 0.
        subagents_running (dict[tuple[int, str], int] | None): Active sub-agent
            counts keyed by ``(level, role)`` (W5.3).
        subagents_total (dict[str, int] | None): Cumulative terminal sub-agent
            counts keyed by status (``done``/``failed``/``killed``).

    Returns:
        str: Prometheus text format suitable for ``PlainTextResponse``.

    Examples:
        >>> "sevn_gateway_up" in render_gateway_metrics()
        True
        >>> "sevn_active_sessions" in render_gateway_metrics(active_sessions=2)
        True
        >>> "sevn_subagents_running" in render_gateway_metrics(
        ...     subagents_running={(1, "tier_b"): 2},
        ... )
        True
    """
    lines = [
        "# HELP sevn_gateway_up Gateway process is serving HTTP",
        "# TYPE sevn_gateway_up gauge",
        "sevn_gateway_up 1",
        "# HELP sevn_active_sessions Count of open gateway sessions",
        "# TYPE sevn_active_sessions gauge",
        f"sevn_active_sessions {max(0, active_sessions)}",
        "# HELP sevn_active_runs Count of in-flight agent runs",
        "# TYPE sevn_active_runs gauge",
        f"sevn_active_runs {max(0, active_runs)}",
        "# HELP sevn_subagents_running Active sub-agent runs by level and role",
        "# TYPE sevn_subagents_running gauge",
    ]
    running = subagents_running or {}
    if running:
        for (level, role), count in sorted(running.items()):
            level_s = _format_label_value(str(level))
            role_s = _format_label_value(role)
            lines.append(
                f'sevn_subagents_running{{level="{level_s}",role="{role_s}"}} {max(0, count)}',
            )
    else:
        lines.append('sevn_subagents_running{level="0",role="none"} 0')
    lines.extend(
        [
            "# HELP sevn_subagents_total Cumulative terminal sub-agent runs by status",
            "# TYPE sevn_subagents_total counter",
        ],
    )
    totals = subagents_total or {}
    for status in ("done", "failed", "killed"):
        count = max(0, int(totals.get(status, 0)))
        status_s = _format_label_value(status)
        lines.append(f'sevn_subagents_total{{status="{status_s}"}} {count}')
    return "\n".join(lines) + "\n"
