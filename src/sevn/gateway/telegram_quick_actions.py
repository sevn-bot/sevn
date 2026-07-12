"""Telegram streaming edits + quick-action callbacks (`specs/18-channel-telegram.md` §4.4-4.5).

Module: sevn.gateway.telegram_quick_actions
Depends: sqlite3, sevn.gateway.channel_router, sevn.self_improve.feedback,
    sevn.gateway.webapp_qa

Exports:
    build_quick_action_inline_keyboard — Regen + thumbs + Web App bar (PRD 01 §5.2).
    parse_qa_callback_data — parse ``qa:<message_id>:<action>`` payloads.
    telegram_fast_callback_ack_text — ``answerCallbackQuery`` toast for ``qa:*`` / ``menu:*``.
    is_telegram_fast_callback_ack — whether inbound needs a 4 s ack short path.
    QuickActionCallbackHandler — dispatcher bypass for ``qa:*`` callbacks.
    record_assistant_platform_message — persist Telegram ids on history rows.
    lookup_assistant_row_by_platform_message — resolve ``qa:*`` targets.
    lookup_origin_user_text_for_assistant — recover user text for qa regen retries.
"""

from __future__ import annotations

import asyncio
import sqlite3
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

from sevn.gateway.strings import (
    CALLBACK_AUTH_BLOCKED_TOAST,
    CALLBACK_GENERIC_TOAST_ACK,
    QA_CLEARED_VOTE_V1,
    QA_LOGGED_FEEDBACK_V1,
    QA_MARKED_HELPFUL_V1,
    QA_REGEN_QUEUED_V1,
)
from sevn.gateway.webapp_qa import (
    maybe_log_qa_bar_webapp_disabled,
    mint_webapp_dispatcher_token,
    quick_action_visibility,
    resolve_thumbs_polarity,
    resolve_thumbs_transition,
    resolve_webapp_public_base,
    webapp_inline_buttons_allowed,
)
from sevn.gateway.webapp_viewer import (
    build_viewer_web_app_button,
    infer_viewer_payload_from_markdown,
    webapp_viewer_launch_allowed,
)
from sevn.self_improve.feedback import insert_feedback_event

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.gateway.channel_router import ChannelRouter, IncomingMessage

GATEWAY_OUTBOUND_PHASE_KEY = "gateway_outbound_phase"
OutboundPhase = Literal["early", "continue", "final", "persist"]

_QA_ACTIONS = frozenset({"regen", "up", "down"})


def build_quick_action_inline_keyboard(
    platform_message_id: int,
    *,
    workspace: WorkspaceConfig | None = None,
    conn: sqlite3.Connection | None = None,
    user_id: str | None = None,
    gateway_message_id: int | None = None,
    platform_chat_id: int | None = None,
    topic_id: int | None = None,
    share_text: str = "",
    viewer_source_text: str = "",
) -> dict[str, Any]:
    """Build Telegram ``inline_keyboard`` for the 5-button QA bar (PRD 01 §5.2).

    Args:
        platform_message_id (int): Telegram ``message_id`` attached to the reply.
        workspace (WorkspaceConfig | None): Per-button visibility flags.
        conn (sqlite3.Connection | None): Mint Web App tokens when set.
        user_id (str | None): Operator id for token binding.
        gateway_message_id (int | None): ``gateway_messages.id`` for Web App payload.
        platform_chat_id (int | None): Telegram chat id for dispatcher scope.
        topic_id (int | None): Forum thread id when set.
        share_text (str): Assistant snippet for share Web App payload.
        viewer_source_text (str): Assistant Markdown for rich viewer launch (M2).

    Returns:
        dict[str, Any]: ``reply_markup``-shaped dict for outbound metadata.

    Examples:
        >>> kb = build_quick_action_inline_keyboard(42)
        >>> len(kb["inline_keyboard"][0]) >= 3
        True
    """
    mid = int(platform_message_id)
    vis = quick_action_visibility(workspace)
    row: list[dict[str, Any]] = []
    viewer_row: list[dict[str, Any]] = []
    if vis["regen"]:
        row.append({"text": "♻ Regen", "callback_data": f"qa:{mid}:regen"})
    if vis["thumbs_up"]:
        row.append({"text": "👍", "callback_data": f"qa:{mid}:up"})
    if vis["thumbs_down"]:
        row.append({"text": "👎", "callback_data": f"qa:{mid}:down"})
    base = (
        resolve_webapp_public_base(workspace) if workspace is not None else "http://127.0.0.1:8787"
    )
    webapp_ok = webapp_inline_buttons_allowed(base)
    chat_id = int(platform_chat_id) if platform_chat_id is not None else 0
    uid = user_id or "owner"
    if conn is not None and gateway_message_id is not None:
        if (vis["share"] or vis["feedback"]) and not webapp_ok:
            maybe_log_qa_bar_webapp_disabled(workspace, once_per_base=True)
        if webapp_ok:
            if vis["share"]:
                share_tok = mint_webapp_dispatcher_token(
                    conn,
                    kind="webapp_share",
                    workspace=workspace,
                    user_id=uid,
                    chat_id=chat_id,
                    topic_id=topic_id,
                    gateway_message_id=int(gateway_message_id),
                    platform_message_id=mid,
                    share_text=share_text,
                )
                row.append(
                    {
                        "text": "🔗 Share",
                        "web_app": {"url": f"{base}/webapp/share?token={share_tok}"},
                    },
                )
            if vis["feedback"]:
                fb_tok = mint_webapp_dispatcher_token(
                    conn,
                    kind="webapp_feedback",
                    workspace=workspace,
                    user_id=uid,
                    chat_id=chat_id,
                    topic_id=topic_id,
                    gateway_message_id=int(gateway_message_id),
                    platform_message_id=mid,
                )
                row.append(
                    {
                        "text": "📝 Feedback",
                        "web_app": {"url": f"{base}/webapp/feedback?token={fb_tok}"},
                    },
                )
            if webapp_ok and workspace is not None and webapp_viewer_launch_allowed(workspace):
                inferred = infer_viewer_payload_from_markdown(
                    viewer_source_text or share_text,
                )
                if inferred is not None:
                    view, view_data = inferred
                    viewer_btn = build_viewer_web_app_button(
                        conn,
                        workspace=workspace,
                        user_id=uid,
                        chat_id=chat_id,
                        topic_id=topic_id,
                        gateway_message_id=int(gateway_message_id),
                        platform_message_id=mid,
                        view=view,
                        view_data=view_data,
                    )
                    if viewer_btn is not None:
                        viewer_row.append(viewer_btn)
    if not row and not viewer_row:
        return {"inline_keyboard": []}
    keyboard: list[list[dict[str, Any]]] = []
    if row:
        keyboard.append(row)
    if viewer_row:
        keyboard.append(viewer_row)
    return {"inline_keyboard": keyboard}


def parse_qa_callback_data(data: str) -> tuple[int, str] | None:
    """Parse ``qa:<message_id>:<action>`` callback payloads.

    Args:
        data (str): Raw callback data string.

    Returns:
        tuple[int, str] | None: ``(telegram_message_id, action)`` or ``None``.

    Examples:
        >>> parse_qa_callback_data("qa:99:regen")
        (99, 'regen')
        >>> parse_qa_callback_data("plan:x:approve") is None
        True
    """
    raw = data.strip()
    if not raw.startswith("qa:"):
        return None
    parts = raw.split(":")
    if len(parts) != 3:
        return None
    try:
        mid = int(parts[1])
    except ValueError:
        return None
    action = parts[2].strip().lower()
    if action not in _QA_ACTIONS:
        return None
    return mid, action


def _callback_data_raw(msg: IncomingMessage) -> str:
    """Return callback ``data`` from metadata or ``text``.
    Args:
        msg (IncomingMessage): Inbound callback envelope.
    Returns:
        str: Stripped callback data, or empty when absent.
    Examples:
        >>> from sevn.gateway.channel_router import IncomingMessage
        >>> _callback_data_raw(
        ...     IncomingMessage(
        ...         channel="telegram",
        ...         user_id="1",
        ...         text="qa:1:up",
        ...         metadata={"callback_data": "qa:1:up"},
        ...     ),
        ... )
        'qa:1:up'
    """
    md = msg.metadata if isinstance(msg.metadata, dict) else {}
    raw = md.get("callback_data")
    if not isinstance(raw, str):
        raw = msg.text or ""
    return raw.strip() if isinstance(raw, str) else ""


def is_telegram_fast_callback_ack(msg: IncomingMessage) -> bool:
    """Return whether ``msg`` is a ``qa:*`` or ``menu:*`` / ``nav:*`` callback.
    Args:
        msg (IncomingMessage): Inbound envelope.
    Returns:
        bool: ``True`` when Telegram must receive ``answerCallbackQuery`` on the
            dedicated short path before session or executor work.
    Examples:
        >>> from sevn.gateway.channel_router import IncomingMessage
        >>> is_telegram_fast_callback_ack(
        ...     IncomingMessage(
        ...         channel="telegram",
        ...         user_id="1",
        ...         text="qa:9:down",
        ...         metadata={
        ...             "callback_data": "qa:9:down",
        ...             "callback_query_id": "cq1",
        ...             "is_callback": True,
        ...         },
        ...     ),
        ... )
        True
    """
    if msg.channel != "telegram":
        return False
    md = msg.metadata if isinstance(msg.metadata, dict) else {}
    if not md.get("is_callback"):
        return False
    cqid = md.get("callback_query_id")
    if not isinstance(cqid, str) or not cqid.strip():
        return False
    data = _callback_data_raw(msg)
    if not data:
        return False
    if data.startswith("qa:"):
        return True
    return data.startswith(("menu:", "nav:"))


def telegram_fast_callback_ack_text(msg: IncomingMessage) -> str:
    """Map ``qa:*`` / ``menu:*`` callback data to ``answerCallbackQuery`` toast text.
    Args:
        msg (IncomingMessage): Inbound Telegram callback envelope.
    Returns:
        str: One-line acknowledgement for Bot API ``text`` (≤ 200 chars).
    Examples:
        >>> from sevn.gateway.channel_router import IncomingMessage
        >>> telegram_fast_callback_ack_text(
        ...     IncomingMessage(
        ...         channel="telegram",
        ...         user_id="1",
        ...         text="qa:1:up",
        ...         metadata={"callback_data": "qa:1:up"},
        ...     ),
        ... )
        'Marked helpful'
    """
    data = _callback_data_raw(msg)
    if data.startswith(("menu:", "nav:")):
        return CALLBACK_GENERIC_TOAST_ACK
    parsed = parse_qa_callback_data(data)
    if parsed is None:
        return CALLBACK_GENERIC_TOAST_ACK
    _mid, action = parsed
    if action == "up":
        return QA_MARKED_HELPFUL_V1
    if action == "down":
        return QA_LOGGED_FEEDBACK_V1
    return QA_REGEN_QUEUED_V1


def record_assistant_platform_message(
    conn: sqlite3.Connection,
    *,
    gateway_message_id: int,
    platform_message_id: str,
    platform_chat_id: str | None,
) -> None:
    """Persist Telegram ids on a sent assistant row for ``qa:*`` resolution.

    Args:
        conn (sqlite3.Connection): Open gateway SQLite handle.
        gateway_message_id (int): ``gateway_messages.id`` for the assistant row.
        platform_message_id (str): Telegram ``message_id`` string.
        platform_chat_id (str | None): Telegram ``chat_id`` when known.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(record_assistant_platform_message)
        True
    """
    conn.execute(
        """
        UPDATE gateway_messages
        SET platform_message_id = ?, platform_chat_id = ?
        WHERE id = ?
        """,
        (platform_message_id, platform_chat_id, gateway_message_id),
    )
    conn.commit()


def lookup_origin_user_text_for_assistant(
    conn: sqlite3.Connection,
    *,
    assistant_message_id: int,
) -> tuple[str, str] | None:
    """Return ``(user_text, origin_turn_id)`` for the user message that produced ``assistant_message_id``.

    Wave 3 (`CONVERSATION_REVIEW_2026-05-28.md` §A15): quick-action regen needs
    to re-ask the **original** user request, not whatever the user typed after
    the failed assistant reply. Resolution: load the assistant row's
    ``turn_id``; the most recent user message with the same ``turn_id`` (or
    the closest preceding user row when ``turn_id`` is unset) is the origin.

    Args:
        conn (sqlite3.Connection): Open gateway SQLite handle.
        assistant_message_id (int): Gateway row id of the assistant message
            the user tapped regen on.

    Returns:
        tuple[str, str] | None: ``(user_text, origin_turn_id)`` when found.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(lookup_origin_user_text_for_assistant)
        True
    """
    row = conn.execute(
        "SELECT session_id, turn_id FROM gateway_messages WHERE id = ?",
        (assistant_message_id,),
    ).fetchone()
    if row is None:
        return None
    session_id, turn_id = str(row[0]), str(row[1] or "")
    if turn_id:
        match = conn.execute(
            """
            SELECT content, turn_id
            FROM gateway_messages
            WHERE session_id = ?
              AND role = 'user'
              AND kind = 'message'
              AND turn_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (session_id, turn_id),
        ).fetchone()
        if match is not None:
            return str(match[0] or ""), str(match[1] or "")
    fallback = conn.execute(
        """
        SELECT content, turn_id
        FROM gateway_messages
        WHERE session_id = ?
          AND role = 'user'
          AND kind = 'message'
          AND id < ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (session_id, assistant_message_id),
    ).fetchone()
    if fallback is None:
        return None
    return str(fallback[0] or ""), str(fallback[1] or "")


def lookup_assistant_row_by_platform_message(
    conn: sqlite3.Connection,
    *,
    channel: str,
    platform_message_id: int,
    platform_chat_id: str | None = None,
) -> tuple[str, int, str] | None:
    """Resolve a Telegram message id to session + gateway row + stored content.

    Args:
        conn (sqlite3.Connection): Open gateway SQLite handle.
        channel (str): Channel key (``telegram``).
        platform_message_id (int): Telegram ``message_id``.
        platform_chat_id (str | None): Optional chat id filter.

    Returns:
        tuple[str, int, str] | None: ``(session_id, gateway_message_id, content)``.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(lookup_assistant_row_by_platform_message)
        True
    """
    pid = str(int(platform_message_id))
    if platform_chat_id is not None:
        row = conn.execute(
            """
            SELECT m.session_id, m.id, m.content
            FROM gateway_messages m
            JOIN gateway_sessions s ON s.session_id = m.session_id
            WHERE m.platform_message_id = ?
              AND m.platform_chat_id = ?
              AND s.channel = ?
              AND m.role = 'assistant'
            ORDER BY m.id DESC
            LIMIT 1
            """,
            (pid, platform_chat_id, channel),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT m.session_id, m.id, m.content
            FROM gateway_messages m
            JOIN gateway_sessions s ON s.session_id = m.session_id
            WHERE m.platform_message_id = ?
              AND s.channel = ?
              AND m.role = 'assistant'
            ORDER BY m.id DESC
            LIMIT 1
            """,
            (pid, channel),
        ).fetchone()
    if row is None:
        return None
    return str(row[0]), int(row[1]), str(row[2])


class QuickActionCallbackHandler:
    """Handle ``qa:*`` Telegram callbacks without LLM Guard (PRD 01 §5.2)."""

    def __init__(self, conn: sqlite3.Connection, router: ChannelRouter) -> None:
        """Bind SQLite + router for regen re-dispatch and feedback inserts.

        Args:
            conn (sqlite3.Connection): Gateway SQLite handle.
            router (ChannelRouter): Router used to enqueue ``run_turn``.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(QuickActionCallbackHandler.__init__)
            True
        """
        self._conn = conn
        self._router = router

    def matches(self, msg: IncomingMessage) -> bool:
        """Return whether ``msg`` is a quick-action callback.

        Args:
            msg (IncomingMessage): Inbound callback envelope.

        Returns:
            bool: ``True`` for ``qa:<id>:<action>`` callback data.

        Examples:
            >>> from sevn.gateway.channel_router import IncomingMessage
            >>> h = QuickActionCallbackHandler.__new__(QuickActionCallbackHandler)
            >>> h.matches(
            ...     IncomingMessage(
            ...         channel="telegram",
            ...         user_id="1",
            ...         text="qa:1:up",
            ...         metadata={"callback_data": "qa:1:up"},
            ...     ),
            ... )
            True
        """
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        raw = md.get("callback_data")
        if not isinstance(raw, str):
            raw = msg.text or ""
        if not isinstance(raw, str):
            return False
        return parse_qa_callback_data(raw.strip()) is not None

    async def handle(
        self,
        msg: IncomingMessage,
        *,
        session_id: str,
        is_owner: bool,
    ) -> str | None:
        """Execute Regen or record thumbs feedback; return optional toast text.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            session_id (str): Session resolved at bypass time.
            is_owner (bool): Whether the sender is the workspace owner.

        Returns:
            str | None: User-visible toast, or ``None`` when silent.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(QuickActionCallbackHandler.handle)
            True
        """
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        raw = md.get("callback_data")
        if not isinstance(raw, str):
            raw = msg.text or ""
        parsed = parse_qa_callback_data(str(raw).strip()) if isinstance(raw, str) else None
        if parsed is None:
            return None
        platform_mid, action = parsed
        chat_raw = md.get("chat_id")
        platform_chat = str(int(chat_raw)) if isinstance(chat_raw, int) else None
        row = await asyncio.to_thread(
            lookup_assistant_row_by_platform_message,
            self._conn,
            channel=msg.channel,
            platform_message_id=platform_mid,
            platform_chat_id=platform_chat,
        )
        if row is None:
            return CALLBACK_GENERIC_TOAST_ACK
        target_session, gateway_mid, _content = row
        if target_session != session_id:
            return CALLBACK_AUTH_BLOCKED_TOAST
        if not is_owner:
            return CALLBACK_AUTH_BLOCKED_TOAST
        if action == "regen":
            prior_summary = self._router._last_turn_summary.get(target_session)
            suggested_tier: str | None = None
            if prior_summary is not None:
                if prior_summary.get("status") == "escalated":
                    suggested_tier = str(
                        prior_summary.get("suggested_tier") or prior_summary.get("tier") or "C",
                    )
                logger.info(
                    "qa_regen_with_prior_summary session_id={} prior_intent={} prior_tier={} prior_status={}",
                    target_session,
                    prior_summary.get("intent"),
                    prior_summary.get("tier"),
                    prior_summary.get("status"),
                )
            else:
                logger.info(
                    "qa_regen_without_prior_summary session_id={} platform_mid={}",
                    target_session,
                    platform_mid,
                )
            # Wave 3 (§A15): stage the ORIGINAL user message as the regen
            # target so the dispatch consumes that instead of the most recent
            # pending user line (which might be "try again" or unrelated).
            origin = await asyncio.to_thread(
                lookup_origin_user_text_for_assistant,
                self._conn,
                assistant_message_id=int(gateway_mid),
            )
            if origin is not None and origin[0].strip():
                origin_text, origin_turn_id = origin
                self._router._sessions.set_regen_target(
                    target_session,
                    user_text=origin_text,
                    origin_turn_id=origin_turn_id,
                    edit_message_id=int(platform_mid),
                    suggested_tier=suggested_tier,
                )
                logger.info(
                    "qa_regen_target session_id={} origin_turn_id={} edit_mid={} text_len={}",
                    target_session,
                    origin_turn_id,
                    platform_mid,
                    len(origin_text),
                )
            await self._router._sessions.enqueue_dispatch(
                target_session,
                correlation_id=str(platform_mid),
                queue_mode=self._router._queue_mode,
                dispatch=self._router._run_turn,
            )
            return QA_REGEN_QUEUED_V1
        polarity_action: Literal["up", "down"] = "up" if action == "up" else "down"
        current = await asyncio.to_thread(
            resolve_thumbs_polarity,
            self._conn,
            user_id=msg.user_id,
            platform_message_id=platform_mid,
            target_turn_id=str(gateway_mid),
        )
        kind, extra = resolve_thumbs_transition(action=polarity_action, current=current)
        payload: dict[str, object] = {
            "channel": msg.channel,
            "platform_message_id": platform_mid,
            "user_id": msg.user_id,
        }
        payload.update(extra)
        await asyncio.to_thread(
            insert_feedback_event,
            self._conn,
            kind=kind,
            target_turn_id=str(gateway_mid),
            schema_version=1,
            payload=payload,
        )
        if kind.endswith("_clear"):
            return QA_CLEARED_VOTE_V1
        if action == "up":
            return QA_MARKED_HELPFUL_V1
        return QA_LOGGED_FEEDBACK_V1
