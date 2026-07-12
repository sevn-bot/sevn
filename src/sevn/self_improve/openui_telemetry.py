"""Promote OpenUI render errors into self-improve feedback buckets (`specs/29`, `specs/33`).

Exports:
    record_openui_render_error — increment in-memory bucket counters for a workspace.
    snapshot_openui_buckets — copy current counters for sampler/telemetry export.
"""

from __future__ import annotations

from collections import defaultdict
from threading import Lock

_lock = Lock()
_buckets: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))


def record_openui_render_error(*, workspace_id: str, reason: str) -> None:
    """Increment the render-error bucket for ``reason``.

    Args:
        workspace_id (str): Logical workspace scope.
        reason (str): Short error class label from the OpenUI bridge.

    Returns:
        None: Always.

    Examples:
        >>> record_openui_render_error(workspace_id="ws", reason="tunnel_down")
        >>> "tunnel_down" in snapshot_openui_buckets("ws")
        True
    """
    key = reason.strip() or "unknown"
    with _lock:
        _buckets[workspace_id][key] += 1


def snapshot_openui_buckets(workspace_id: str) -> dict[str, int]:
    """Return a copy of OpenUI error counters for one workspace.

    Args:
        workspace_id (str): Logical workspace scope.

    Returns:
        dict[str, int]: Reason → count.

    Examples:
        >>> snap = snapshot_openui_buckets("ws-demo")
        >>> isinstance(snap, dict)
        True
    """
    with _lock:
        return dict(_buckets.get(workspace_id, {}))


__all__ = ["record_openui_render_error", "snapshot_openui_buckets"]
