"""Persist Telegram context across owner-initiated gateway/proxy restarts.

Module: sevn.gateway.runtime.gateway_restart_ack
Depends: json, pathlib, sqlite3, sevn.gateway.channel_router, sevn.gateway.session_manager

When an owner confirms restart from ``/config``, the gateway records the chat,
session, and a short conversation snapshot under ``.sevn/gateway-restart-pending.json``.
After the process comes back, :func:`deliver_pending_gateway_restart_acks` sends a
confirmation message into the same chat.

Exports:
    PendingGatewayRestart — one restart handoff row.
    pending_restart_store_path — JSON marker path under the workspace ``.sevn`` dir.
    restart_ack_delivered_path — JSON marker for a recently delivered Telegram ack.
    conversation_snapshot_for_session — last visible transcript lines.
    record_pending_gateway_restart — write one pending row before ``systemctl restart``.
    has_pending_gateway_restart — whether a handoff file is waiting for boot delivery.
    recent_restart_ack_delivered — whether a post-boot ack was sent recently for one chat.
    mark_restart_ack_delivered — record a delivered ack to ignore stale confirm callbacks.
    load_pending_gateway_restarts — read unconsumed rows.
    claim_pending_gateway_restarts — read, dedupe, and delete pending rows.
    clear_pending_gateway_restarts — delete the marker file.
    deliver_pending_gateway_restart_acks — post Telegram confirmations on boot.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

if TYPE_CHECKING:
    from sevn.gateway.channel_router import ChannelRouter

_RESTART_STORE_VERSION = 1
_ACK_DELIVERED_STORE_VERSION = 1
_MAX_SNAPSHOT_LINES = 12
_MAX_LINE_CHARS = 240
_RESTART_ACK_COOLDOWN_S = 300
_MENU_SNAPSHOT_PREFIXES = ("act:", "cfg:", "menu:", "nav:", "qa:")

RestartService = Literal["gateway", "proxy"]


@dataclass(frozen=True)
class PendingGatewayRestart:
    """One owner restart awaiting a post-boot Telegram ack."""

    requested_at: int
    service: RestartService
    channel: str
    user_id: str
    chat_id: int
    message_id: int
    topic_id: int | None
    session_id: str
    conversation_snapshot: tuple[str, ...]


def pending_restart_store_path(dot_sevn: Path) -> Path:
    """Return the JSON file path for pending restart acknowledgments.

    Args:
        dot_sevn (Path): Workspace ``.sevn`` directory.

    Returns:
        Path: Absolute path to ``gateway-restart-pending.json``.

    Examples:
        >>> pending_restart_store_path(Path("/w/.sevn")).name
        'gateway-restart-pending.json'
    """
    return dot_sevn.expanduser().resolve() / "gateway-restart-pending.json"


def restart_ack_delivered_path(dot_sevn: Path) -> Path:
    """Return the JSON file path for a recently delivered restart acknowledgment.

    Args:
        dot_sevn (Path): Workspace ``.sevn`` directory.

    Returns:
        Path: Absolute path to ``gateway-restart-ack-delivered.json``.

    Examples:
        >>> restart_ack_delivered_path(Path("/w/.sevn")).name
        'gateway-restart-ack-delivered.json'
    """
    return dot_sevn.expanduser().resolve() / "gateway-restart-ack-delivered.json"


def _message_content_is_menu_noise(content: str) -> bool:
    """Return whether one message body should be omitted from restart snapshots.

    Args:
        content (str): Raw ``gateway_messages.content`` (not the ``role:`` prefix).

    Returns:
        bool: ``True`` for menu callbacks, slash commands, and prior restart acks.

    Examples:
        >>> _message_content_is_menu_noise("act:gateway:restart:confirm")
        True
        >>> _message_content_is_menu_noise("hello")
        False
    """
    text = content.strip()
    if not text:
        return True
    if text.startswith("/"):
        return True
    lowered = text.casefold()
    if lowered.startswith(_MENU_SNAPSHOT_PREFIXES):
        return True
    if "gateway restarted" in lowered:
        return True
    if "you can continue chatting here" in lowered:
        return True
    if "deployment id:" in lowered:
        return True
    return "last messages before restart:" in lowered


def _filter_snapshot_lines(lines: tuple[str, ...]) -> tuple[str, ...]:
    """Drop menu/callback noise from ``role: content`` snapshot lines.

    Args:
        lines (tuple[str, ...]): Snapshot lines from :func:`conversation_snapshot_for_session`.

    Returns:
        tuple[str, ...]: Filtered lines, preserving order.

    Examples:
        >>> _filter_snapshot_lines(("user: act:gateway:restart:confirm", "user: hi"))
        ('user: hi',)
    """
    kept: list[str] = []
    for line in lines:
        if ": " not in line:
            continue
        _role, _sep, content = line.partition(": ")
        if _message_content_is_menu_noise(content):
            continue
        kept.append(line)
    return tuple(kept)


def conversation_snapshot_for_session(
    conn: object,
    session_id: str,
    *,
    limit: int = _MAX_SNAPSHOT_LINES,
) -> tuple[str, ...]:
    """Build a short transcript snapshot for one gateway session.

    Args:
        conn (object): Open ``sevn.db`` connection.
        session_id (str): Gateway session id.
        limit (int): Maximum lines to retain.

    Returns:
        tuple[str, ...]: ``role: content`` lines, oldest first within the window.

    Examples:
        >>> conversation_snapshot_for_session.__name__
        'conversation_snapshot_for_session'
    """
    from sevn.gateway.session_manager import latest_messages

    if not session_id.strip():
        return ()
    rows = latest_messages(conn, session_id)  # type: ignore[arg-type]
    lines: list[str] = []
    for row in rows[-max(1, limit) :]:
        role = str(row.get("role", "unknown"))
        content = str(row.get("content", "")).strip().replace("\n", " ")
        if len(content) > _MAX_LINE_CHARS:
            content = content[: _MAX_LINE_CHARS - 1] + "…"
        if content and not _message_content_is_menu_noise(content):
            lines.append(f"{role}: {content}")
    return tuple(lines[-max(1, limit) :])


def record_pending_gateway_restart(
    dot_sevn: Path,
    *,
    service: RestartService,
    channel: str,
    user_id: str,
    chat_id: int,
    message_id: int,
    topic_id: int | None,
    session_id: str,
    conversation_snapshot: tuple[str, ...],
) -> None:
    """Write one pending restart row before invoking service manager.

    Args:
        dot_sevn (Path): Workspace ``.sevn`` directory.
        service (RestartService): ``gateway`` (paired proxy) or ``proxy`` only.
        channel (str): Channel id (``telegram``).
        user_id (str): Operator user id.
        chat_id (int): Telegram chat id for the ack message.
        message_id (int): Host ``/config`` message id (for operator context).
        topic_id (int | None): Forum topic id when set.
        session_id (str): Active gateway session id.
        conversation_snapshot (tuple[str, ...]): Recent transcript lines.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> td = Path(tempfile.mkdtemp())
        >>> dot = td / ".sevn"
        >>> dot.mkdir()
        >>> record_pending_gateway_restart(
        ...     dot,
        ...     service="gateway",
        ...     channel="telegram",
        ...     user_id="1",
        ...     chat_id=42,
        ...     message_id=99,
        ...     topic_id=None,
        ...     session_id="s1",
        ...     conversation_snapshot=("user: hi",),
        ... )
        >>> load_pending_gateway_restarts(dot)[0].session_id
        's1'
    """
    path = pending_restart_store_path(dot_sevn)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = PendingGatewayRestart(
        requested_at=int(time.time()),
        service=service,
        channel=channel,
        user_id=user_id,
        chat_id=chat_id,
        message_id=message_id,
        topic_id=topic_id,
        session_id=session_id,
        conversation_snapshot=_filter_snapshot_lines(conversation_snapshot),
    )
    payload = {
        "version": _RESTART_STORE_VERSION,
        "pending": [asdict(row)],
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_pending_gateway_restarts(dot_sevn: Path) -> tuple[PendingGatewayRestart, ...]:
    """Load pending restart rows from disk.

    Args:
        dot_sevn (Path): Workspace ``.sevn`` directory.

    Returns:
        tuple[PendingGatewayRestart, ...]: Rows awaiting post-boot delivery.

    Examples:
        >>> load_pending_gateway_restarts(Path("/nonexistent/.sevn"))
        ()
    """
    path = pending_restart_store_path(dot_sevn)
    if not path.is_file():
        return ()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    if not isinstance(raw, dict):
        return ()
    pending = raw.get("pending")
    if not isinstance(pending, list):
        return ()
    out: list[PendingGatewayRestart] = []
    for item in pending:
        if not isinstance(item, dict):
            continue
        service = item.get("service")
        if service not in {"gateway", "proxy"}:
            continue
        try:
            service_lit: RestartService = "gateway" if service == "gateway" else "proxy"
            out.append(
                PendingGatewayRestart(
                    requested_at=int(item.get("requested_at", 0)),
                    service=service_lit,
                    channel=str(item.get("channel", "")),
                    user_id=str(item.get("user_id", "")),
                    chat_id=int(item.get("chat_id", 0)),
                    message_id=int(item.get("message_id", 0)),
                    topic_id=(int(item["topic_id"]) if item.get("topic_id") is not None else None),
                    session_id=str(item.get("session_id", "")),
                    conversation_snapshot=tuple(
                        str(line) for line in (item.get("conversation_snapshot") or [])
                    ),
                ),
            )
        except (TypeError, ValueError):
            continue
    return tuple(out)


def mark_restart_ack_delivered(
    dot_sevn: Path,
    *,
    chat_id: int,
    user_id: str,
) -> None:
    """Record that a post-boot restart ack was delivered for one Telegram chat.

    Args:
        dot_sevn (Path): Workspace ``.sevn`` directory.
        chat_id (int): Telegram chat id that received the ack.
        user_id (str): Operator user id.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> dot = Path(tempfile.mkdtemp()) / ".sevn"
        >>> dot.mkdir()
        >>> mark_restart_ack_delivered(dot, chat_id=42, user_id="1")
        >>> recent_restart_ack_delivered(dot, 42)
        True
    """
    path = restart_ack_delivered_path(dot_sevn)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": _ACK_DELIVERED_STORE_VERSION,
        "delivered_at": int(time.time()),
        "chat_id": chat_id,
        "user_id": user_id,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def recent_restart_ack_delivered(
    dot_sevn: Path,
    chat_id: int,
    *,
    within_s: int = _RESTART_ACK_COOLDOWN_S,
) -> bool:
    """Return whether a restart ack was delivered recently for ``chat_id``.

    Args:
        dot_sevn (Path): Workspace ``.sevn`` directory.
        chat_id (int): Telegram chat id to match.
        within_s (int): Cooldown window in seconds.

    Returns:
        bool: ``True`` when a recent delivery marker exists for the chat.

    Examples:
        >>> recent_restart_ack_delivered(Path("/nonexistent/.sevn"), 42)
        False
    """
    path = restart_ack_delivered_path(dot_sevn)
    if not path.is_file():
        return False
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(raw, dict):
        return False
    try:
        stored_chat = int(raw.get("chat_id", 0))
        delivered_at = int(raw.get("delivered_at", 0))
    except (TypeError, ValueError):
        return False
    if stored_chat != chat_id or delivered_at <= 0:
        return False
    return int(time.time()) - delivered_at <= max(1, within_s)


def has_pending_gateway_restart(dot_sevn: Path) -> bool:
    """Return whether a restart handoff file exists with at least one row.

    Args:
        dot_sevn (Path): Workspace ``.sevn`` directory.

    Returns:
        bool: ``True`` when :func:`load_pending_gateway_restarts` would be non-empty.

    Examples:
        >>> has_pending_gateway_restart(Path("/nonexistent/.sevn"))
        False
    """
    return bool(load_pending_gateway_restarts(dot_sevn))


def _dedupe_pending_by_chat(
    rows: tuple[PendingGatewayRestart, ...],
) -> tuple[PendingGatewayRestart, ...]:
    """Keep the newest pending row per Telegram chat id.

    Args:
        rows (tuple[PendingGatewayRestart, ...]): Rows from disk (legacy multi-append).

    Returns:
        tuple[PendingGatewayRestart, ...]: At most one row per ``chat_id``.

    Examples:
        >>> older = PendingGatewayRestart(
        ...     requested_at=1,
        ...     service="gateway",
        ...     channel="telegram",
        ...     user_id="1",
        ...     chat_id=9,
        ...     message_id=1,
        ...     topic_id=None,
        ...     session_id="a",
        ...     conversation_snapshot=(),
        ... )
        >>> newer = PendingGatewayRestart(
        ...     requested_at=2,
        ...     service="gateway",
        ...     channel="telegram",
        ...     user_id="1",
        ...     chat_id=9,
        ...     message_id=2,
        ...     topic_id=None,
        ...     session_id="b",
        ...     conversation_snapshot=(),
        ... )
        >>> _dedupe_pending_by_chat((older, newer)) == (newer,)
        True
    """
    by_chat: dict[int, PendingGatewayRestart] = {}
    for row in rows:
        if row.chat_id <= 0:
            continue
        prev = by_chat.get(row.chat_id)
        if prev is None or row.requested_at >= prev.requested_at:
            by_chat[row.chat_id] = row
    return tuple(by_chat[k] for k in sorted(by_chat))


def claim_pending_gateway_restarts(dot_sevn: Path) -> tuple[PendingGatewayRestart, ...]:
    """Atomically read and remove pending rows (deduped per chat).

    Args:
        dot_sevn (Path): Workspace ``.sevn`` directory.

    Returns:
        tuple[PendingGatewayRestart, ...]: Rows to deliver; file is cleared first.

    Examples:
        >>> claim_pending_gateway_restarts(Path("/nonexistent/.sevn"))
        ()
    """
    rows = _dedupe_pending_by_chat(load_pending_gateway_restarts(dot_sevn))
    if rows:
        clear_pending_gateway_restarts(dot_sevn)
    return rows


def clear_pending_gateway_restarts(dot_sevn: Path) -> None:
    """Remove the pending-restart marker file.

    Args:
        dot_sevn (Path): Workspace ``.sevn`` directory.

    Examples:
        >>> from pathlib import Path
        >>> clear_pending_gateway_restarts(Path("/tmp/empty/.sevn"))
    """
    path = pending_restart_store_path(dot_sevn)
    path.unlink(missing_ok=True)


def _ack_message_text(
    row: PendingGatewayRestart,
    *,
    deployment_id: str | None,
) -> str:
    """Format the post-restart confirmation body.

    Args:
        row (PendingGatewayRestart): Persisted handoff row.
        deployment_id (str | None): Current gateway deployment id when known.

    Returns:
        str: Plain-text Telegram message body.

    Examples:
        >>> _ack_message_text(
        ...     PendingGatewayRestart(
        ...         requested_at=0,
        ...         service="gateway",
        ...         channel="telegram",
        ...         user_id="1",
        ...         chat_id=1,
        ...         message_id=2,
        ...         topic_id=None,
        ...         session_id="s",
        ...         conversation_snapshot=(),
        ...     ),
        ...     deployment_id="dep-1",
        ... ).startswith("Gateway restarted")
        True
    """
    if row.service == "gateway":
        headline = "Gateway restarted (proxy restarted too when installed)."
    else:
        headline = "Proxy restarted."
    lines = [
        headline,
        "",
        "Your conversation before the restart is saved in this session.",
    ]
    if deployment_id:
        lines.append(f"Deployment id: {deployment_id}")
    if row.conversation_snapshot:
        lines.append("")
        lines.append("Last messages before restart:")
        lines.extend(row.conversation_snapshot[-_MAX_SNAPSHOT_LINES:])
    lines.append("")
    lines.append("You can continue chatting here.")
    return "\n".join(lines)


def _telegram_outbound_metadata(row: PendingGatewayRestart) -> dict[str, Any]:
    """Build routing metadata for :meth:`TelegramAdapter.send`.

    Args:
        row (PendingGatewayRestart): Persisted restart handoff row.

    Returns:
        dict[str, Any]: Must include ``chat_id`` (TelegramAdapter requirement).

    Examples:
        >>> _telegram_outbound_metadata(
        ...     PendingGatewayRestart(
        ...         requested_at=0,
        ...         service="gateway",
        ...         channel="telegram",
        ...         user_id="1",
        ...         chat_id=42,
        ...         message_id=9,
        ...         topic_id=None,
        ...         session_id="s",
        ...         conversation_snapshot=(),
        ...     ),
        ... )["chat_id"]
        42
    """
    meta: dict[str, Any] = {"chat_id": row.chat_id}
    if row.topic_id is not None:
        meta["topic_id"] = row.topic_id
        meta["telegram_thread_id"] = row.topic_id
    return meta


async def deliver_pending_gateway_restart_acks(
    *,
    router: ChannelRouter,
    dot_sevn: Path,
    deployment_id: str | None = None,
) -> int:
    """Send Telegram confirmations for pending owner restarts.

    Args:
        router (ChannelRouter): Live gateway router with adapters started.
        dot_sevn (Path): Workspace ``.sevn`` directory.
        deployment_id (str | None): Current deployment id for the ack body.

    Returns:
        int: Number of acknowledgments delivered.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(deliver_pending_gateway_restart_acks)
        True
    """
    pending = _dedupe_pending_by_chat(load_pending_gateway_restarts(dot_sevn))
    if not pending:
        return 0
    adapter = router._adapters.get("telegram")
    if adapter is None:
        logger.warning(
            "gateway_restart_ack skipped: no telegram adapter (pending={})",
            len(pending),
        )
        return 0
    clear_pending_gateway_restarts(dot_sevn)
    from sevn.gateway.channel_router import OutgoingMessage

    delivered = 0
    for row in pending:
        if row.channel != "telegram" or not row.user_id.strip() or row.chat_id <= 0:
            continue
        try:
            message_ids = await adapter.send(
                OutgoingMessage(
                    channel="telegram",
                    user_id=row.user_id,
                    text=_ack_message_text(row, deployment_id=deployment_id),
                    session_id=row.session_id,
                    metadata=_telegram_outbound_metadata(row),
                ),
            )
            if not message_ids:
                logger.warning(
                    "gateway_restart_ack deliver returned no message ids chat_id={}",
                    row.chat_id,
                )
                continue
            mark_restart_ack_delivered(
                dot_sevn,
                chat_id=row.chat_id,
                user_id=row.user_id,
            )
            delivered += 1
        except Exception as exc:
            logger.warning(
                "gateway_restart_ack deliver failed chat_id={}: {}",
                row.chat_id,
                exc,
            )
    if delivered:
        logger.info("gateway_restart_ack delivered {} confirmation(s)", delivered)
    return delivered


__all__ = [
    "PendingGatewayRestart",
    "claim_pending_gateway_restarts",
    "clear_pending_gateway_restarts",
    "conversation_snapshot_for_session",
    "deliver_pending_gateway_restart_acks",
    "has_pending_gateway_restart",
    "load_pending_gateway_restarts",
    "mark_restart_ack_delivered",
    "pending_restart_store_path",
    "recent_restart_ack_delivered",
    "record_pending_gateway_restart",
    "restart_ack_delivered_path",
]
