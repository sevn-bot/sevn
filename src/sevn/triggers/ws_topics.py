"""Dashboard WebSocket topic naming for trigger runs (`specs/30-non-interactive-triggers.md` §11).

Module: sevn.triggers.ws_topics
Depends: (none)

Exports:
    trigger_run_ws_topic — build ``run.{run_id}`` topic strings.
"""

from __future__ import annotations

RUN_WS_TOPIC_PREFIX: str = "run."


def trigger_run_ws_topic(run_id: str) -> str:
    """Return the dashboard WebSocket topic for one non-interactive run.

    Clients subscribe on ``GET /ws/dashboard`` with topic filter ``run.{run_id}``
    (`specs/24-dashboard.md` §2.3; v1 picks WebSocket over SSE).

    Args:
        run_id (str): ``run_id`` / ``correlation_id`` from ``POST /api/v1/run``.

    Returns:
        str: Topic name such as ``run.550e8400-e29b-41d4-a716-446655440000``.

    Examples:
        >>> trigger_run_ws_topic("abc-123")
        'run.abc-123'
    """
    rid = str(run_id).strip()
    if rid.startswith(RUN_WS_TOPIC_PREFIX):
        return rid
    return f"{RUN_WS_TOPIC_PREFIX}{rid}"


__all__ = ["RUN_WS_TOPIC_PREFIX", "trigger_run_ws_topic"]
