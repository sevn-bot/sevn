"""Stable ``sevn.tools.message`` import path for cron / watch notify callers.

Module: sevn.tools.message
Depends: json, loguru

The agent-facing async tool remains :func:`sevn.tools.outbound.message_tool`.
Issue-watch cron patches and calls this sync ``message_tool`` surface so
notify works without a full :class:`~sevn.tools.context.ToolContext`.

Exports:
    message_tool — sync notify entry (logs + success envelope; patchable in tests).
"""

from __future__ import annotations

import json

from loguru import logger


def message_tool(*, text: str, channel: str | None = None, user_id: str | None = None) -> str:
    """Deliver (or record) a proactive notify message for cron/watch callers.

    Args:
        text (str): Message body to deliver or record.
        channel (str | None, optional): Optional channel key (unused without gateway).
        user_id (str | None, optional): Optional destination user (unused without gateway).

    Returns:
        str: JSON success envelope ``{"ok": true, "text_length": N}``.

    Examples:
        >>> import json
        >>> json.loads(message_tool(text="hello"))["ok"]
        True
    """
    _ = (channel, user_id)
    body = str(text or "").strip()
    logger.info("message_tool notify text_length={}", len(body))
    return json.dumps({"ok": True, "text_length": len(body)})


__all__ = ["message_tool"]
