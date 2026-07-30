"""Inbound referenced-message context blocks for quote and bot-self-reply paths.

Module: sevn.gateway.inbound.referenced_context
Depends: sqlite3, sevn.gateway.telegram.telegram_quick_actions

Exports:
    explicit_referenced_message_block — wrap quote text for tier-B prompts.
    bot_self_reply_reference_block — resolve assistant content for bot-self-replies.
    prefix_inbound_referenced_context — prepend blocks onto inbound user text.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from sevn.gateway.telegram.telegram_quick_actions import lookup_assistant_row_by_platform_message

if TYPE_CHECKING:
    from sevn.gateway.channel_router import IncomingMessage


def explicit_referenced_message_block(body: str) -> str:
    """Wrap quoted inbound context so the model can distinguish it from user text.

    Args:
        body (str): Reply-quote prefix from ``format_reply_quote`` or adapter metadata.

    Returns:
        str: Block wrapped in ``[Referenced message]`` markers, or the original when already marked.

    Examples:
        >>> explicit_referenced_message_block("Quoted from Alice:\\nhi\\n")
        '[Referenced message]\\nQuoted from Alice:\\nhi\\n[/Referenced message]\\n\\n'
        >>> explicit_referenced_message_block("[Quote]\\nx\\n[/Quote]\\n").startswith("[Quote]")
        True
    """
    stripped = body.strip()
    if not stripped:
        return ""
    if "[Referenced message]" in stripped or stripped.startswith("[Quote]"):
        return body
    return f"[Referenced message]\n{stripped}\n[/Referenced message]\n\n"


def bot_self_reply_reference_block(
    conn: sqlite3.Connection,
    *,
    channel: str,
    platform_message_id: int,
    platform_chat_id: str | None,
) -> str:
    """Build an explicit reference block for bot-self-replies (quote suppressed at parse).

    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        channel (str): Channel key (``telegram``).
        platform_message_id (int): Telegram ``reply_to_message.message_id``.
        platform_chat_id (str | None): Optional chat id filter for lookup.

    Returns:
        str: ``[Referenced message]`` block with assistant content when resolvable.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(bot_self_reply_reference_block)
        True
    """
    lookup = lookup_assistant_row_by_platform_message(
        conn,
        channel=channel,
        platform_message_id=platform_message_id,
        platform_chat_id=platform_chat_id,
    )
    if lookup is not None:
        _session_id, _row_id, content = lookup
        body = content.strip() or "[no text]"
    else:
        body = "[content unavailable at ingest]"
    return (
        f"[Referenced message]\n"
        f"Telegram message_id={platform_message_id} (assistant):\n"
        f"{body}\n"
        f"[/Referenced message]\n\n"
    )


def prefix_inbound_referenced_context(
    msg: IncomingMessage,
    user_text: str,
    *,
    conn: sqlite3.Connection,
) -> str:
    """Prepend explicit referenced-message blocks for quote and bot-self-reply paths.

    Args:
        msg (IncomingMessage): Inbound message carrying quote metadata.
        user_text (str): Operator text after voice/STT normalization.
        conn (sqlite3.Connection): Gateway SQLite handle for bot-self-reply lookup.

    Returns:
        str: User text prefixed with an explicit ``[Referenced message]`` block when applicable.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(prefix_inbound_referenced_context)
        True
    """
    md = msg.metadata if isinstance(msg.metadata, dict) else {}
    rq = md.get("reply_to_quote") or md.get("reply_quote")
    if isinstance(rq, str) and rq.strip():
        return f"{explicit_referenced_message_block(rq)}{user_text}"
    ref_mid = md.get("referenced_message_id")
    if ref_mid is None:
        ref_mid = md.get("reply_to_message_id")
    if isinstance(ref_mid, int) and md.get("reply_to_quote") is None:
        chat_raw = md.get("chat_id") or md.get("telegram_chat_id")
        chat_id = str(chat_raw) if chat_raw is not None else None
        block = bot_self_reply_reference_block(
            conn,
            channel=msg.channel,
            platform_message_id=ref_mid,
            platform_chat_id=chat_id,
        )
        return f"{block}{user_text}"
    return user_text


__all__ = [
    "bot_self_reply_reference_block",
    "explicit_referenced_message_block",
    "prefix_inbound_referenced_context",
]
