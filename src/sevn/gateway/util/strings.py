"""English-only gateway user-visible copy (`specs/17-gateway.md` §10.6, PRD 01).

Module: sevn.gateway.util.strings

Exports:
    blocked_inbound_user_message — pick user-facing copy from scanner verdict metadata.
"""

from __future__ import annotations

from typing import Any, Final

from sevn.security.llm_guard_scanner import BlockReason

BLOCKED_INBOUND_USER_MESSAGE: Final[str] = (
    "That message was blocked by the safety filter. Try rephrasing without harmful content."
)
SCANNER_UNAVAILABLE_USER_MESSAGE: Final[str] = (
    "Could not process your message: the egress proxy is not running or not reachable. "
    "Run `sevn proxy start` and try again."
)
VOICE_INBOUND_REJECTED_TOO_LARGE: Final[str] = (
    "This voice attachment exceeds the workspace size limit."
)
VOICE_INBOUND_REJECTED_TOO_LONG: Final[str] = (
    "This voice attachment exceeds the workspace duration limit."
)
VOICE_DISABLED_USER_MESSAGE: Final[str] = (
    "Voice is disabled for this workspace. Enable voice in /config or set voice.enabled in sevn.json."
)
STEER_NOT_AVAILABLE_V1: Final[str] = (
    "/steer is not available in this version (only cancel queue mode is supported)."
)
STEER_ACK_V1: Final[str] = "Got it — I'll steer at the next safe boundary."
STEER_USAGE_V1: Final[str] = "Usage: /steer <text>"
STEER_NOT_OWNER_V1: Final[str] = "Only the workspace owner can use /steer."
STEER_BUFFER_FULL_V1: Final[str] = "Steer buffer is full; try again after the current injection."
CALLBACK_GENERIC_TOAST_ACK: Final[str] = "OK."
CALLBACK_AUTH_BLOCKED_TOAST: Final[str] = "You are not allowed to use this action."
QA_REGEN_QUEUED_V1: Final[str] = "Regenerating…"
QA_MARKED_HELPFUL_V1: Final[str] = "Marked helpful"
QA_LOGGED_FEEDBACK_V1: Final[str] = "Logged feedback"
QA_CLEARED_VOTE_V1: Final[str] = "Vote cleared"
QA_FEEDBACK_RECORDED_V1: Final[str] = QA_LOGGED_FEEDBACK_V1


def blocked_inbound_user_message(
    *,
    reasons: tuple[BlockReason, ...],
    details: dict[str, Any] | None = None,
) -> str:
    """Return channel-facing copy for a blocked inbound message.

    Args:
        reasons (tuple[BlockReason, ...]): Scanner block reasons.
        details (dict[str, Any] | None): Optional scanner detail bag.

    Returns:
        str: Safety-filter notice or infrastructure error copy.

    Examples:
        >>> blocked_inbound_user_message(reasons=(BlockReason.toxicity,))
        'That message was blocked by the safety filter. Try rephrasing without harmful content.'
        >>> blocked_inbound_user_message(reasons=(BlockReason.scanner_unavailable,))
        'Could not process your message: the egress proxy is not running or not reachable. Run `sevn proxy start` and try again.'
    """
    _ = details
    if BlockReason.scanner_unavailable in reasons:
        return SCANNER_UNAVAILABLE_USER_MESSAGE
    return BLOCKED_INBOUND_USER_MESSAGE
