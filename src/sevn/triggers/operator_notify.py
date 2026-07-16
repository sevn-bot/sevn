"""Injectable operator notify for cron / watch (real delivery, not a fake tool stub).

Module: sevn.triggers.operator_notify
Depends: asyncio, json, pathlib, loguru

Gateway boot wires :func:`wire_operator_notify` to deliver via
:meth:`ChannelRouter.route_outgoing` (owner Telegram). When unwired (tests /
offline), :func:`deliver_operator_notify` still persists a LOG artefact under
``.sevn/trigger_runs/`` so callers never get a fake ``ok`` with zero delivery.

Exports:
    set_operator_notify — install/clear the gateway delivery sink.
    wire_operator_notify — gateway lifespan helper to install Telegram sink.
    unwire_operator_notify — clear the sink on shutdown.
    deliver_operator_notify — deliver text via the sink (or LOG fallback).
    reset_operator_notify_for_tests — clear sink (unit tests only).
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from loguru import logger

OperatorNotifyFn = Callable[[str], None]

_operator_notify: OperatorNotifyFn | None = None


def set_operator_notify(fn: OperatorNotifyFn | None) -> None:
    """Install or clear the gateway operator-notify sink.

    Args:
        fn (OperatorNotifyFn | None): Sync callable that delivers ``text``, or
            ``None`` to clear (LOG-file fallback only).

    Returns:
        None

    Examples:
        >>> set_operator_notify(None)
        >>> reset_operator_notify_for_tests()
    """
    global _operator_notify
    _operator_notify = fn


def wire_operator_notify(
    *,
    gateway_router: Any,
    owner_telegram_user_id: str | None,
    loop: asyncio.AbstractEventLoop | None = None,
) -> bool:
    """Install the Telegram owner sink when an owner id is configured.

    When ``owner_telegram_user_id`` is empty, leaves the sink unwired so
    :func:`deliver_operator_notify` uses the LOG fallback (never a no-op success).

    Args:
        gateway_router (Any): Gateway :class:`ChannelRouter` with ``route_outgoing``.
        owner_telegram_user_id (str | None): Telegram user id for the owner, or ``None``.
        loop (asyncio.AbstractEventLoop | None): Running loop; defaults to
            :func:`asyncio.get_running_loop`.

    Returns:
        bool: ``True`` when a Telegram sink was installed.

    Examples:
        >>> wire_operator_notify(gateway_router=object(), owner_telegram_user_id=None)
        False
    """
    dest = (owner_telegram_user_id or "").strip()
    if not dest:
        return False
    from sevn.gateway.channel_router import OutgoingMessage

    event_loop = loop if loop is not None else asyncio.get_running_loop()

    def _operator_notify_sink(text: str) -> None:
        if not text.strip():
            return
        session_id = f"telegram:{dest}:general"

        async def _send() -> None:
            try:
                await gateway_router.route_outgoing(
                    OutgoingMessage(
                        channel="telegram",
                        user_id=dest,
                        text=text.strip(),
                        session_id=session_id,
                        metadata={"source": "operator_notify"},
                    ),
                )
            except Exception:
                logger.exception("operator_notify_route_outgoing_failed")

        event_loop.call_soon_threadsafe(lambda: asyncio.create_task(_send()))

    set_operator_notify(_operator_notify_sink)
    return True


def unwire_operator_notify() -> None:
    """Clear the gateway operator-notify sink (lifespan shutdown).

    Returns:
        None

    Examples:
        >>> unwire_operator_notify()
    """
    set_operator_notify(None)


def reset_operator_notify_for_tests() -> None:
    """Clear the operator-notify sink (unit tests only).

    Returns:
        None

    Examples:
        >>> reset_operator_notify_for_tests()
    """
    set_operator_notify(None)


def _write_log_fallback(*, text: str, content_root: Path | None) -> Path | None:
    """Persist notify text under ``.sevn/trigger_runs`` when no sink is wired.

    Args:
        text (str): Message body.
        content_root (Path | None): Workspace root, or ``None`` to skip.

    Returns:
        Path | None: Written JSON path, or ``None`` when skipped/failed.

    Examples:
        >>> _write_log_fallback(text="x", content_root=None) is None
        True
    """
    root = content_root
    if root is None:
        return None
    runs = root / ".sevn" / "trigger_runs"
    try:
        runs.mkdir(parents=True, exist_ok=True)
        path = runs / f"operator-notify-{uuid.uuid4().hex}.json"
        path.write_text(
            json.dumps(
                {
                    "kind": "operator_notify",
                    "text": text,
                    "ts_ns": time.time_ns(),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError:
        logger.exception("operator_notify_log_fallback_failed")
        return None
    return path


def deliver_operator_notify(
    *,
    text: str,
    content_root: Path | None = None,
) -> None:
    """Deliver proactive operator text via the wired sink (or LOG fallback).

    Args:
        text (str): Message body.
        content_root (Path | None, optional): Workspace root for LOG fallback
            when no sink is installed.

    Returns:
        None

    Examples:
        >>> import tempfile
        >>> deliver_operator_notify(text="hi", content_root=Path(tempfile.mkdtemp()))
    """
    body = str(text or "").strip()
    if not body:
        return
    sink = _operator_notify
    if sink is not None:
        sink(body)
        return
    written = _write_log_fallback(text=body, content_root=content_root)
    if written is not None:
        logger.info("operator_notify_log_fallback path={}", written)
    else:
        logger.warning(
            "operator_notify_unwired text_length={} (no gateway sink; no content_root)",
            len(body),
        )


__all__ = [
    "OperatorNotifyFn",
    "deliver_operator_notify",
    "reset_operator_notify_for_tests",
    "set_operator_notify",
    "unwire_operator_notify",
    "wire_operator_notify",
]
