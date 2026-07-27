"""Two-step confirm keyboards for destructive /config menu actions (D6, D15).

Module: sevn.gateway.menu.confirm_gates
Depends: typing

Exports:
    build_confirm_gate_keyboard — Confirm/Cancel rows modelled on tunnel-on shape.
    confirm_gate_message — caption text for a confirm prompt.
"""

from __future__ import annotations

from typing import Any


def build_confirm_gate_keyboard(gate_id: str) -> list[list[dict[str, Any]]]:
    """Build Confirm/Cancel rows for one confirm-gated action family.

    Uses the same two-button layout as :func:`build_tunnel_on_confirm_keyboard`
    but with family-specific ``callback_data`` suffixes (``:confirm`` / ``:cancel``).

    Args:
        gate_id (str): Action stem after ``act:`` (e.g. ``secrets:rm``).

    Returns:
        list[list[dict[str, Any]]]: Inline keyboard rows (no nav chrome).

    Examples:
        >>> rows = build_confirm_gate_keyboard("secrets:rm")
        >>> rows[0][0]["callback_data"]
        'act:secrets:rm:confirm'
        >>> rows[0][1]["callback_data"]
        'act:secrets:rm:cancel'
    """
    return [
        [
            {
                "text": "✅ Confirm",
                "callback_data": f"act:{gate_id}:confirm",
            },
            {
                "text": "Cancel",
                "callback_data": f"act:{gate_id}:cancel",
            },
        ],
    ]


def confirm_gate_message(*, title: str, detail: str) -> str:
    """Return caption text for a generic two-step confirm screen.

    Args:
        title (str): Short action title shown in the caption header.
        detail (str): One or two sentences explaining the irreversible effect.

    Returns:
        str: Telegram HTML caption for the confirm screen.

    Examples:
        >>> "Remove secret" in confirm_gate_message(title="Remove secret", detail="Deletes alias.")
        True
    """
    return f"{title}\n\n{detail}\nTap Confirm to proceed."


__all__ = ["build_confirm_gate_keyboard", "confirm_gate_message"]
