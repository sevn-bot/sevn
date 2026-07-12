"""Structured DEBUG event helpers for triager and tier-B execution paths.

These helpers are thin one-liners so call sites stay readable. They emit a
single ``loguru`` log line at DEBUG level with a stable ``event`` field plus
arbitrary key/value attributes. The gateway service log defaults to DEBUG, so
operator turns surface in ``workspace/logs/gateway.log`` for offline debugging.

Module: sevn.logging.structured
Depends: loguru

Exports:
    debug_event — emit a single DEBUG line with ``event=<name>`` + kwargs.
    preview — truncate a string for safe inclusion in a log line.
"""

from __future__ import annotations

from typing import Any

from loguru import logger


def preview(text: str | None, *, limit: int = 200) -> str:
    """Return a single-line, length-bounded preview of ``text`` for logs.

    Args:
        text (str | None): Source text. ``None`` is treated as empty.
        limit (int): Max characters to keep.

    Returns:
        str: ``text`` collapsed onto one line, truncated to ``limit`` chars
            with a trailing ``…`` when truncated.

    Examples:
        >>> preview("hello\\nworld", limit=20)
        'hello world'
        >>> preview("x" * 250)[-1]
        '…'
        >>> preview(None)
        ''
    """
    if not text:
        return ""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    return flat[: max(0, limit - 1)] + "…"


def debug_event(event: str, **fields: Any) -> None:
    """Emit one structured DEBUG log line.

    Args:
        event (str): Event name (e.g. ``"triager.input"``).
        fields (Any): Arbitrary key/value attributes rendered as ``key=value``
            pairs after ``event=...``.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(debug_event)
        True
    """
    parts = [f"event={event}"]
    for k, v in fields.items():
        parts.append(f"{k}={v!r}")
    logger.debug(" ".join(parts))


__all__ = ["debug_event", "preview"]
