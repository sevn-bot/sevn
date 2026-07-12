"""Canonical user-visible copy for LLM Guard outcomes (``specs/09-security-scanner.md`` §6).

Channels and Web App surfaces should import strings from here so copy stays
reviewable in one place. Do not log or trace these literals alongside raw user
payloads.

Module: sevn.security.scanner_channel_copy

Exports:
    INBOUND_BLOCK_NOTICE — short user-visible block line for chat surfaces.
    WEBAPP_FEEDBACK_SUBMIT_BLOCKED — inline error when feedback body fails scan.

Examples:
    >>> INBOUND_BLOCK_NOTICE.startswith("Message blocked")
    True
"""

from __future__ import annotations

from typing import Final

# §6 default; localisable later — must not echo raw payload.
INBOUND_BLOCK_NOTICE: Final[str] = "Message blocked for security reasons. Tap for details."

WEBAPP_FEEDBACK_SUBMIT_BLOCKED: Final[str] = (
    "Feedback could not be sent for security reasons. Try shortening the message "
    "or contact the owner if this persists."
)

__all__ = ["INBOUND_BLOCK_NOTICE", "WEBAPP_FEEDBACK_SUBMIT_BLOCKED"]
