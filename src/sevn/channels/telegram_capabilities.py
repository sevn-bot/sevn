"""Bot API 10.1 rich-message capability probe (R1, D2).

Module: sevn.channels.telegram_capabilities
Depends: enum, typing, collections.abc

Exports:
    RichCapability — cached capability verdict for rich send path.
    bot_api_error_description — shared error-description extractor for Bot API bodies.
    detect_rich_support — guarded boot/reconnect probe via ``getMe`` + 10.1 method surface.
    is_method_not_found_response — classify unknown-method Bot API failures.
    is_rich_payload_rejected — classify ``rich message …`` payload-rejection failures.

Examples:
    >>> from sevn.channels.telegram_capabilities import RichCapability
    >>> RichCapability.NOT_CAPABLE.value
    'not_capable'
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any

ApiCall = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]

_RICH_PROBE_METHOD = "sendRichMessage"
_MIN_RICH_MESSAGE: dict[str, Any] = {"markdown": "probe"}
"""Minimal valid ``InputRichMessage`` wire payload for the capability probe.

An ``InputRichMessage`` is ``{"markdown": …}`` / ``{"html": …}`` (Bot API 10.1) —
never a ``blocks`` tree, which the server rejects as ``rich message must be
non-empty``. See :func:`sevn.channels.telegram_rich.build_input_rich_message_markdown`.
"""
_GETME_RICH_FLAG_KEYS = ("supports_rich_messages", "can_send_rich_messages")


class RichCapability(StrEnum):
    """Rich-message support verdict from a guarded Bot API probe (D2)."""

    NOT_CAPABLE = "not_capable"
    CAPABLE = "capable"
    UNKNOWN = "unknown"


def bot_api_error_description(data: dict[str, Any]) -> str | None:
    """Return the lowercased ``description`` of a failed Bot API response.

    Shared prologue for Bot API error classifiers (finding-19): yields ``None``
    for non-dict bodies and successful (``ok`` truthy) responses so callers can
    early-exit, otherwise the lowercased ``description`` string.

    Args:
        data (dict[str, Any]): Parsed Bot API response body.

    Returns:
        str | None: Lowercased error description, or ``None`` when not an error.

    Examples:
        >>> bot_api_error_description({"ok": False, "description": "Not Found"})
        'not found'
        >>> bot_api_error_description({"ok": True}) is None
        True
    """
    if not isinstance(data, dict) or data.get("ok"):
        return None
    return str(data.get("description") or "").lower()


def is_method_not_found_response(data: dict[str, Any]) -> bool:
    """Return whether a Bot API JSON body indicates an unknown HTTP method.

    Args:
        data (dict[str, Any]): Parsed Bot API response body.

    Returns:
        bool: ``True`` when the server does not expose the requested method.

    Examples:
        >>> is_method_not_found_response({"ok": False, "error_code": 404, "description": "Not Found"})
        True
        >>> is_method_not_found_response({"ok": False, "description": "Bad Request: chat not found"})
        False
    """
    desc = bot_api_error_description(data)
    if desc is None:
        return False
    if data.get("error_code") == 404 or "unknown method" in desc:
        return True
    return "not found" in desc and "method" in desc


def is_rich_payload_rejected(data: dict[str, Any]) -> bool:
    """Return whether the server rejected the probe's ``rich_message`` content.

    A ``rich message must be non-empty`` (or similar ``rich message …``) 400 means
    the method exists but our payload was not understood as rich content — a schema
    mismatch, not proof of support. Treating it as CAPABLE makes every reply 400,
    so the probe degrades to NOT_CAPABLE instead.

    Args:
        data (dict[str, Any]): Parsed Bot API response body.

    Returns:
        bool: ``True`` when the error is about the rich message content itself.

    Examples:
        >>> is_rich_payload_rejected(
        ...     {"ok": False, "description": "Bad Request: rich message must be non-empty"}
        ... )
        True
        >>> is_rich_payload_rejected({"ok": False, "description": "Bad Request: chat not found"})
        False
    """
    desc = bot_api_error_description(data)
    if desc is None:
        return False
    return "rich message" in desc


def _parse_getme_rich_flag(result: dict[str, Any]) -> RichCapability | None:
    """Return a fast-path verdict when ``getMe`` exposes an explicit rich flag.

    Args:
        result (dict[str, Any]): ``getMe`` ``result`` object.

    Returns:
        RichCapability | None: Verdict when a known flag is present, else ``None``.

    Examples:
        >>> _parse_getme_rich_flag({"supports_rich_messages": True})
        <RichCapability.CAPABLE: 'capable'>
        >>> _parse_getme_rich_flag({"id": 1}) is None
        True
    """
    for key in _GETME_RICH_FLAG_KEYS:
        val = result.get(key)
        if val is True:
            return RichCapability.CAPABLE
        if val is False:
            return RichCapability.NOT_CAPABLE
    return None


async def detect_rich_support(api_call: ApiCall) -> RichCapability:
    """Probe Bot API 10.1 rich-message support via ``getMe`` and a guarded method check (D2).

    Unknown or old API surfaces degrade to :attr:`RichCapability.NOT_CAPABLE` so the
    legacy ``to_telegram()`` path remains authoritative until capability is proven.

    Args:
        api_call (ApiCall): Async ``(method, params) -> response_json`` dispatcher.

    Returns:
        RichCapability: ``CAPABLE`` when ``sendRichMessage`` exists; otherwise ``NOT_CAPABLE``.

    Examples:
        >>> import asyncio
        >>> async def _capable_api(method: str, params: dict[str, object]) -> dict[str, object]:
        ...     if method == "getMe":
        ...         return {"ok": True, "result": {"id": 1, "is_bot": True, "first_name": "b"}}
        ...     return {"ok": False, "description": "Bad Request: chat not found"}
        >>> asyncio.run(detect_rich_support(_capable_api))
        <RichCapability.CAPABLE: 'capable'>
    """
    try:
        me = await api_call("getMe", {})
    except Exception:
        return RichCapability.NOT_CAPABLE
    if not isinstance(me, dict) or not me.get("ok"):
        return RichCapability.NOT_CAPABLE
    result = me.get("result")
    if not isinstance(result, dict):
        return RichCapability.NOT_CAPABLE

    fast = _parse_getme_rich_flag(result)
    if fast is not None:
        return fast

    try:
        probe = await api_call(
            _RICH_PROBE_METHOD,
            {"chat_id": 0, "rich_message": _MIN_RICH_MESSAGE},
        )
    except Exception:
        return RichCapability.NOT_CAPABLE
    if not isinstance(probe, dict):
        return RichCapability.NOT_CAPABLE
    if probe.get("ok"):
        return RichCapability.CAPABLE
    if is_method_not_found_response(probe):
        return RichCapability.NOT_CAPABLE
    if is_rich_payload_rejected(probe):
        return RichCapability.NOT_CAPABLE
    return RichCapability.CAPABLE
