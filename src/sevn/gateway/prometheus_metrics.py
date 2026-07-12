"""Prometheus text exposition for the gateway (`specs/17-gateway.md`, `specs/24-dashboard.md`).

Exports:
    render_gateway_metrics — ``text/plain; version=0.0.4`` body for ``GET /metrics``.
"""

from __future__ import annotations


def render_gateway_metrics(*, active_sessions: int = 0, active_runs: int = 0) -> str:
    """Return Prometheus exposition text for gateway health counters.

    Args:
        active_sessions (int, optional): Open gateway sessions. Defaults to 0.
        active_runs (int, optional): In-flight runs. Defaults to 0.

    Returns:
        str: Prometheus text format suitable for ``PlainTextResponse``.

    Examples:
        >>> "sevn_gateway_up" in render_gateway_metrics()
        True
        >>> "sevn_active_sessions" in render_gateway_metrics(active_sessions=2)
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
    ]
    return "\n".join(lines) + "\n"
