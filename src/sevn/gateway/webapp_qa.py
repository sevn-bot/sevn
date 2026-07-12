"""Telegram/Web App quick-action helpers (share + structured feedback).

Module: sevn.gateway.webapp_qa
Depends: json, secrets, sqlite3, urllib.parse, sevn.config.defaults,
    sevn.gateway.dispatcher_state, sevn.self_improve.feedback

Exports:
    resolve_webapp_public_base — HTTPS origin for ``web_app`` button URLs.
    webapp_inline_buttons_allowed — whether Share/Feedback buttons may be attached.
    webapp_https_disabled_notice — operator-facing text when Share/Feedback are hidden.
    maybe_log_qa_bar_webapp_disabled — emit ``qa_bar_webapp_disabled`` once per gateway base.
    quick_action_visibility — per-button show flags from workspace config.
    mint_webapp_dispatcher_token — ``dispatcher_state`` row for share/feedback.
    load_webapp_dispatcher_payload — fetch token payload when not consumed.
    consume_webapp_dispatcher_token — mark token single-use.
    resolve_thumbs_polarity — current 👍/👎 state for a user + message.
    resolve_thumbs_transition — map tap to ``feedback_events`` kind.
    insert_structured_feedback — persist free-text feedback row.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlparse

from loguru import logger

from sevn.config.defaults import DEFAULT_GATEWAY_HOST, DEFAULT_GATEWAY_PORT
from sevn.gateway.dispatcher_state import (
    dispatcher_state_ttl_for_kind,
    insert_dispatcher_state,
)
from sevn.infrastructure.tunnel_config import tunnel_cfg_from_disk
from sevn.infrastructure.tunnel_manager import default_manager

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig

ThumbsPolarity = Literal["up", "down"]
_FEEDBACK_THUMB_KINDS = frozenset(
    {
        "thumbs_up",
        "thumbs_down",
        "thumbs_up_clear",
        "thumbs_down_clear",
        "thumbs_switch",
    },
)


def resolve_webapp_public_base(workspace: WorkspaceConfig) -> str:
    """Resolve gateway HTTPS origin for Telegram ``web_app`` URLs.

    Prefers ``channels.telegram.webhook_url`` origin, then a healthy
    ``infrastructure.tunnel`` public URL from :mod:`sevn.infrastructure.tunnel_manager`,
    else falls back to the local gateway HTTP base.

    Args:
        workspace (WorkspaceConfig): Active workspace document.

    Returns:
        str: ``scheme://host[:port]`` without trailing slash.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> ws = WorkspaceConfig.minimal(workspace_root=".")
        >>> resolve_webapp_public_base(ws).startswith("http://127.0.0.1:")
        True
    """
    channels = workspace.channels
    tg = channels.telegram if channels is not None else None
    if tg is not None and isinstance(tg.webhook_url, str) and tg.webhook_url.strip():
        parsed = urlparse(tg.webhook_url.strip())
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    tunnel_cfg = tunnel_cfg_from_disk(workspace)
    if tunnel_cfg:
        ts = default_manager.status(tunnel_cfg)
        if ts.public_url:
            return str(ts.public_url).rstrip("/")
    gw = workspace.gateway
    host = (gw.host if gw is not None else None) or DEFAULT_GATEWAY_HOST
    port = (gw.port if gw is not None else None) or DEFAULT_GATEWAY_PORT
    return f"http://{host}:{int(port)}"


def webapp_inline_buttons_allowed(public_base: str) -> bool:
    """Return whether Telegram accepts ``web_app`` inline buttons for ``public_base``.

    Bot API rejects non-HTTPS ``web_app`` URLs; attaching them fails the whole
    ``editMessageReplyMarkup`` call and drops callback buttons too.

    Args:
        public_base (str): Gateway origin from :func:`resolve_webapp_public_base`.

    Returns:
        bool: ``True`` when Share/Feedback ``web_app`` buttons may be included.

    Examples:
        >>> webapp_inline_buttons_allowed("https://bot.example.com")
        True
        >>> webapp_inline_buttons_allowed("http://127.0.0.1:3001")
        False
    """
    return public_base.strip().lower().startswith("https://")


_QA_BAR_WEBAPP_DISABLED_BASES_SEEN: set[str] = set()


def webapp_https_disabled_notice(public_base: str) -> str | None:
    """Return the operator notice when Web App buttons cannot be attached.

    Args:
        public_base (str): Gateway origin from :func:`resolve_webapp_public_base`.

    Returns:
        str | None: Notice text when ``public_base`` is not HTTPS; else ``None``.

    Examples:
        >>> webapp_https_disabled_notice("http://127.0.0.1:3001") is not None
        True
        >>> webapp_https_disabled_notice("https://bot.example.com") is None
        True
    """
    if webapp_inline_buttons_allowed(public_base):
        return None
    return (
        f"WebApp buttons disabled — gateway base `{public_base}` is not HTTPS; "
        "share/feedback buttons hidden"
    )


def maybe_log_qa_bar_webapp_disabled(
    workspace: WorkspaceConfig | None,
    *,
    once_per_base: bool = True,
) -> str | None:
    """Log ``qa_bar_webapp_disabled`` when the gateway base is plain HTTP.

    Args:
        workspace (WorkspaceConfig | None): Active workspace; ``None`` skips logging.
        once_per_base (bool): When ``True``, emit at most once per resolved base URL.

    Returns:
        str | None: Notice text when buttons are disabled; else ``None``.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> notice = maybe_log_qa_bar_webapp_disabled(WorkspaceConfig.minimal())
        >>> notice is None or notice.startswith("WebApp buttons disabled")
        True
    """
    if workspace is None:
        return None
    base = resolve_webapp_public_base(workspace)
    notice = webapp_https_disabled_notice(base)
    if notice is None:
        return None
    if once_per_base and base in _QA_BAR_WEBAPP_DISABLED_BASES_SEEN:
        return notice
    if once_per_base:
        _QA_BAR_WEBAPP_DISABLED_BASES_SEEN.add(base)
    logger.info("qa_bar_webapp_disabled base={} {}", base, notice)
    return notice


def quick_action_visibility(workspace: WorkspaceConfig | None) -> dict[str, bool]:
    """Return per-button visibility for the QA bar.

    Args:
        workspace (WorkspaceConfig | None): Active workspace; ``None`` uses defaults.

    Returns:
        dict[str, bool]: Keys ``regen``, ``thumbs_up``, ``thumbs_down``, ``share``, ``feedback``.

    Examples:
        >>> quick_action_visibility(None)["regen"]
        True
    """
    defaults = {
        "regen": True,
        "thumbs_up": True,
        "thumbs_down": True,
        "share": True,
        "feedback": True,
    }
    if workspace is None or workspace.channels is None:
        return defaults
    tg = workspace.channels.telegram
    if tg is None or tg.quick_actions is None:
        return defaults
    qa = tg.quick_actions
    return {
        "regen": bool(qa.show_regen),
        "thumbs_up": bool(qa.show_thumbs_up),
        "thumbs_down": bool(qa.show_thumbs_down),
        "share": bool(qa.show_share),
        "feedback": bool(qa.show_feedback),
    }


def mint_webapp_dispatcher_token(
    conn: sqlite3.Connection,
    *,
    kind: Literal["webapp_share", "webapp_feedback", "webapp_viewer"],
    workspace: WorkspaceConfig | None,
    user_id: str,
    chat_id: int,
    topic_id: int | None,
    gateway_message_id: int,
    platform_message_id: int,
    share_text: str = "",
) -> str:
    """Insert a short-lived ``dispatcher_state`` token for a Web App handoff.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle.
        kind (Literal["webapp_share", "webapp_feedback"]): Row discriminator.
        workspace (WorkspaceConfig | None): TTL overrides.
        user_id (str): Operator user id string.
        chat_id (int): Telegram chat id (``0`` when unknown).
        topic_id (int | None): Forum thread id when set.
        gateway_message_id (int): ``gateway_messages.id`` join key.
        platform_message_id (int): Telegram ``message_id``.
        share_text (str): Assistant text snippet for share payload.

    Returns:
        str: URL-safe opaque token.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> tok = mint_webapp_dispatcher_token(
        ...     c,
        ...     kind="webapp_share",
        ...     workspace=None,
        ...     user_id="owner",
        ...     chat_id=9,
        ...     topic_id=None,
        ...     gateway_message_id=1,
        ...     platform_message_id=42,
        ...     share_text="hi",
        ... )
        >>> len(tok) >= 8
        True
        >>> c.close()
    """
    token = secrets.token_urlsafe(16)
    payload = json.dumps(
        {
            "v": 1,
            "user_id": user_id,
            "gateway_message_id": int(gateway_message_id),
            "platform_message_id": int(platform_message_id),
            "share_text": share_text[:4000],
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    uid_int = 0
    if user_id.isdigit():
        uid_int = int(user_id)
    insert_dispatcher_state(
        conn,
        token=token,
        kind=kind,
        user_id=uid_int,
        chat_id=int(chat_id),
        topic_id=topic_id,
        payload_json=payload,
        ttl_seconds=dispatcher_state_ttl_for_kind(kind, workspace),
        consumed=0,
    )
    return token


def load_webapp_dispatcher_payload(
    conn: sqlite3.Connection,
    *,
    token: str,
    expected_kind: Literal["webapp_share", "webapp_feedback", "webapp_viewer"],
) -> dict[str, Any] | None:
    """Load a non-consumed Web App dispatcher token payload.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle.
        token (str): Opaque token from the Web App URL.
        expected_kind (Literal["webapp_share", "webapp_feedback"]): Required kind.

    Returns:
        dict[str, Any] | None: Parsed payload or ``None`` when missing/expired/consumed.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> tok = mint_webapp_dispatcher_token(
        ...     c,
        ...     kind="webapp_feedback",
        ...     workspace=None,
        ...     user_id="u",
        ...     chat_id=1,
        ...     topic_id=None,
        ...     gateway_message_id=3,
        ...     platform_message_id=9,
        ... )
        >>> load_webapp_dispatcher_payload(c, token=tok, expected_kind="webapp_feedback") is not None
        True
        >>> c.close()
    """
    row = conn.execute(
        """
        SELECT kind, payload_json, consumed, expires_at
        FROM dispatcher_state
        WHERE token = ?
        """,
        (token.strip(),),
    ).fetchone()
    if row is None:
        return None
    kind, payload_raw, consumed, expires_at = row
    if kind != expected_kind or int(consumed) != 0:
        return None
    import time

    if int(expires_at) <= int(time.time()):
        return None
    try:
        payload = json.loads(str(payload_raw))
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def consume_webapp_dispatcher_token(conn: sqlite3.Connection, *, token: str) -> None:
    """Mark a Web App dispatcher token consumed (single-use).

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle.
        token (str): Token primary key.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> tok = mint_webapp_dispatcher_token(
        ...     c,
        ...     kind="webapp_share",
        ...     workspace=None,
        ...     user_id="u",
        ...     chat_id=1,
        ...     topic_id=None,
        ...     gateway_message_id=1,
        ...     platform_message_id=2,
        ... )
        >>> consume_webapp_dispatcher_token(c, token=tok)
        >>> row = c.execute(
        ...     "SELECT consumed FROM dispatcher_state WHERE token = ?",
        ...     (tok,),
        ... ).fetchone()
        >>> row is not None and int(row[0]) == 1
        True
        >>> c.close()
    """
    conn.execute(
        "UPDATE dispatcher_state SET consumed = 1 WHERE token = ?",
        (token.strip(),),
    )
    conn.commit()


def resolve_thumbs_polarity(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    platform_message_id: int,
    target_turn_id: str,
) -> ThumbsPolarity | None:
    """Return active thumbs polarity for ``(user_id, platform_message_id)``.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` with ``feedback_events``.
        user_id (str): Operator id.
        platform_message_id (int): Telegram message id.
        target_turn_id (str): ``gateway_messages.id`` string.

    Returns:
        ThumbsPolarity | None: ``up``, ``down``, or no active vote.

    Examples:
        >>> import sqlite3
        >>> from sevn.self_improve.feedback import insert_feedback_event
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> _ = insert_feedback_event(
        ...     c,
        ...     kind="thumbs_up",
        ...     target_turn_id="7",
        ...     schema_version=1,
        ...     payload={"user_id": "u", "platform_message_id": 9},
        ... )
        >>> resolve_thumbs_polarity(c, user_id="u", platform_message_id=9, target_turn_id="7")
        'up'
        >>> c.close()
    """
    rows = conn.execute(
        """
        SELECT kind, payload_json FROM feedback_events
        WHERE target_turn_id = ?
          AND kind IN (
              'thumbs_up', 'thumbs_down', 'thumbs_up_clear',
              'thumbs_down_clear', 'thumbs_switch'
          )
        ORDER BY created_at ASC
        """,
        (target_turn_id,),
    ).fetchall()
    state: ThumbsPolarity | None = None
    for kind, payload_raw in rows:
        try:
            payload = json.loads(str(payload_raw))
        except (TypeError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            continue
        if str(payload.get("user_id", "")) != user_id:
            continue
        pmid = payload.get("platform_message_id")
        if pmid is None or int(pmid) != int(platform_message_id):
            continue
        if kind == "thumbs_up":
            state = "up"
        elif kind == "thumbs_down":
            state = "down"
        elif kind == "thumbs_up_clear":
            if state == "up":
                state = None
        elif kind == "thumbs_down_clear":
            if state == "down":
                state = None
        elif kind == "thumbs_switch":
            to_val = payload.get("to")
            if to_val in ("up", "down"):
                state = to_val
    return state


def resolve_thumbs_transition(
    *,
    action: Literal["up", "down"],
    current: ThumbsPolarity | None,
) -> tuple[str, dict[str, object]]:
    """Map a thumbs tap to ``feedback_events`` kind + payload extras.

    Args:
        action (Literal["up", "down"]): Button pressed.
        current (ThumbsPolarity | None): Active polarity before tap.

    Returns:
        tuple[str, dict[str, object]]: ``(kind, extra_payload)``.

    Examples:
        >>> resolve_thumbs_transition(action="up", current=None)
        ('thumbs_up', {})
        >>> resolve_thumbs_transition(action="up", current="up")
        ('thumbs_up_clear', {})
        >>> resolve_thumbs_transition(action="down", current="up")
        ('thumbs_switch', {'from': 'up', 'to': 'down'})
    """
    if current == action:
        clear_kind = "thumbs_up_clear" if action == "up" else "thumbs_down_clear"
        return clear_kind, {}
    if current is not None and current != action:
        return "thumbs_switch", {"from": current, "to": action}
    kind = "thumbs_up" if action == "up" else "thumbs_down"
    return kind, {}


def insert_structured_feedback(
    conn: sqlite3.Connection,
    *,
    target_turn_id: str,
    user_id: str,
    channel: str,
    platform_message_id: str | None,
    body_text: str,
    dropdowns: dict[str, object],
    schema_version: int = 1,
    submission_key: str | None = None,
) -> str | None:
    """Persist one structured feedback row (idempotent on ``submission_key``).

    Args:
        conn (sqlite3.Connection): Migrated ``sevn.db`` handle.
        target_turn_id (str): ``gateway_messages.id`` join key.
        user_id (str): Operator id.
        channel (str): Channel key (``telegram``, ``webchat``, …).
        platform_message_id (str | None): Platform message id when known.
        body_text (str): Free-text body (stored raw).
        dropdowns (dict[str, object]): Structured radio/dropdown answers.
        schema_version (int): Wire schema version.
        submission_key (str | None): Client idempotency key.

    Returns:
        str | None: New ``feedback_id``, or existing id when ``submission_key`` matches.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> fid = insert_structured_feedback(
        ...     c,
        ...     target_turn_id="1",
        ...     user_id="owner",
        ...     channel="webchat",
        ...     platform_message_id=None,
        ...     body_text="too long",
        ...     dropdowns={"severity": "minor"},
        ... )
        >>> fid is not None and len(fid) > 0
        True
        >>> c.close()
    """
    if submission_key:
        existing = conn.execute(
            "SELECT feedback_id FROM structured_feedback WHERE submission_key = ?",
            (submission_key,),
        ).fetchone()
        if existing is not None:
            return str(existing[0])
    from datetime import UTC, datetime

    feedback_id = secrets.token_hex(16)
    created_at = datetime.now(tz=UTC).isoformat()
    conn.execute(
        """
        INSERT INTO structured_feedback (
            feedback_id, target_turn_id, user_id, channel,
            platform_message_id, body_text, dropdowns_json,
            schema_version, created_at, submission_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            feedback_id,
            target_turn_id,
            user_id,
            channel,
            platform_message_id,
            body_text[:2000],
            json.dumps(dropdowns, sort_keys=True),
            int(schema_version),
            created_at,
            submission_key,
        ),
    )
    conn.commit()
    return feedback_id


__all__ = [
    "consume_webapp_dispatcher_token",
    "insert_structured_feedback",
    "load_webapp_dispatcher_payload",
    "maybe_log_qa_bar_webapp_disabled",
    "mint_webapp_dispatcher_token",
    "quick_action_visibility",
    "resolve_thumbs_polarity",
    "resolve_thumbs_transition",
    "resolve_webapp_public_base",
    "webapp_https_disabled_notice",
    "webapp_inline_buttons_allowed",
]
