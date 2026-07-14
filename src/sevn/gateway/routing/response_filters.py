"""Gateway response filtering helpers.

Module: sevn.gateway.routing.response_filters
Depends: typing

Exports:
    is_intentional_silence_response — detect intentional silence text.
    is_intentional_silence_agent_result — silence only on successful turns.
"""

from __future__ import annotations

from typing import Any

# Canonical model-emitted control token for intentional silence.
SILENT_REPLY_TOKEN = "NO_REPLY"  # nosec B105

# Exact whole-response markers that mean "the agent intentionally chose not to
# reply". Keep this list small and explicit; arbitrary empty output remains an
# error/empty-response path, not silence.
LIVE_GATEWAY_SILENT_MARKERS = frozenset(
    {
        "[SILENT]",
        "SILENT",
        "NO_REPLY",
        "NO REPLY",
    }
)


def _canonical_silence_candidate(text: str) -> str:
    """Normalize silence candidate text for marker comparison.

    Args:
        text (str): Raw assistant text.

    Returns:
        str: Uppercased, whitespace-collapsed form.

    Examples:
        >>> _canonical_silence_candidate("  no_reply  ")
        'NO_REPLY'
    """
    return " ".join(text.strip().upper().split())


def is_intentional_silence_response(response: Any) -> bool:
    """Return True only when ``response`` is exactly a silence marker.

    Substantive prose that merely mentions ``NO_REPLY`` or ``[SILENT]`` must be
    delivered normally. A blank response is also not silence; blank output is
    handled by the empty-response failure path.

    Args:
        response (Any): Outbound assistant text candidate.

    Returns:
        bool: ``True`` when delivery should be suppressed.

    Examples:
        >>> is_intentional_silence_response("[SILENT]")
        True
        >>> is_intentional_silence_response("Please use NO_REPLY next time")
        False
    """
    if not isinstance(response, str):
        return False
    stripped = response.strip()
    if not stripped:
        return False
    if len(stripped) > 64:
        return False
    return _canonical_silence_candidate(stripped) in LIVE_GATEWAY_SILENT_MARKERS


def is_intentional_silence_agent_result(agent_result: dict[str, Any] | None, response: Any) -> bool:
    """Silence markers suppress delivery only for successful agent turns.

    Args:
        agent_result (dict | None): Turn outcome metadata from the agent loop.
        response (Any): Outbound assistant text candidate.

    Returns:
        bool: ``True`` when outbound delivery should be skipped.

    Examples:
        >>> is_intentional_silence_agent_result({"failed": False}, "NO_REPLY")
        True
        >>> is_intentional_silence_agent_result({"failed": True}, "NO_REPLY")
        False
    """
    if not isinstance(agent_result, dict):
        return False
    if agent_result.get("failed"):
        return False
    return is_intentional_silence_response(response)


__all__ = [
    "LIVE_GATEWAY_SILENT_MARKERS",
    "SILENT_REPLY_TOKEN",
    "is_intentional_silence_agent_result",
    "is_intentional_silence_response",
]
