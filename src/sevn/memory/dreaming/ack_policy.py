"""Dreaming ``ack_required`` operator surface (`specs/31-memory-dreaming.md` §2, §11).

Module: sevn.memory.dreaming.ack_policy
Depends: (none)

Exports:
    format_ack_required_trace_attrs — trace attrs for queued pending rows.

Examples:
    >>> from sevn.memory.dreaming.ack_policy import DREAMING_ACK_V1_SURFACE
    >>> DREAMING_ACK_V1_SURFACE
    'dashboard'
"""

from __future__ import annotations

from typing import Any

# v1: Mission Control dashboard only — no Telegram ack path (`specs/24-dashboard.md`).
DREAMING_ACK_V1_SURFACE: str = "dashboard"


def format_ack_required_trace_attrs(*, queued: int) -> dict[str, Any]:
    """Build stable ``dreaming.*`` attrs for ``ack_required`` queue writes.

    Args:
        queued (int): Number of ``pending/*.json`` files written.

    Returns:
        dict[str, Any]: Trace attribute payload.

    Examples:
        >>> format_ack_required_trace_attrs(queued=2)["ack_surface"]
        'dashboard'
    """

    return {
        "ack_surface": DREAMING_ACK_V1_SURFACE,
        "queued_pending_files": queued,
    }


__all__ = ["DREAMING_ACK_V1_SURFACE", "format_ack_required_trace_attrs"]
