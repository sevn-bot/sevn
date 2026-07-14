"""Inbound update parsing and access policy for TelegramAdapter.

Module: sevn.channels.telegram_inbound
Depends: asyncio, pathlib, sevn.gateway.channel_types, sevn.channels.telegram_config

Exports:
    TelegramInboundMixin — webhook/callback/inline/message parsing mixed into the adapter.

Examples:
    >>> from sevn.channels.telegram import TelegramAdapter
    >>> TelegramAdapter(resolved_bot_token="t").name
    'telegram'
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any

from loguru import logger

from sevn.channels.callback_overflow import resolve_dispatcher_overflow_callback_data
from sevn.channels.telegram_api import _BOT_API
from sevn.channels.telegram_config import (
    DMPolicy,
    _normalize_topic_id,
    _session_scope_override,
    format_reply_quote,
)
from sevn.channels.telegram_send_host import TelegramSendHost
from sevn.config.defaults import TELEGRAM_UPDATE_DEDUP_CAP, TELEGRAM_UPDATE_DEDUP_TRIM_TO
from sevn.gateway.channel_types import IncomingMessage
from sevn.gateway.telegram.telegram_inline import resolve_inline_config


class TelegramInboundMixin(TelegramSendHost):
    """Mixed into :class:`TelegramAdapter`."""

    def _remember_update(self, update_id: int) -> bool:
        """Return True if *update_id* is new; False if duplicate.
        Maintains an LRU-ordered ``OrderedDict`` capped at
        ``TELEGRAM_UPDATE_DEDUP_CAP``; when the cap is exceeded the oldest
        entries are trimmed down to ``TELEGRAM_UPDATE_DEDUP_TRIM_TO``.
        Args:
            update_id (int): Telegram update id.
        Returns:
            bool: True if previously unseen; False if already remembered.
        Examples:
            >>> from sevn.channels.telegram import TelegramAdapter
            >>> adapter = TelegramAdapter(resolved_bot_token="t")
            >>> adapter._remember_update(1)
            True
            >>> adapter._remember_update(1)
            False
        """
        if update_id in self._seen_updates:
            return False
        self._seen_updates[update_id] = None
        self._seen_updates.move_to_end(update_id)
        if len(self._seen_updates) > TELEGRAM_UPDATE_DEDUP_CAP:
            while len(self._seen_updates) > TELEGRAM_UPDATE_DEDUP_TRIM_TO:
                self._seen_updates.popitem(last=False)
        return True

    def _upsert_topic_name(self, chat_id: int, topic_id: int, name: str) -> None:
        """Persist the latest known display name for a forum topic.
        Failures are logged at exception level but never raised, so a
        transient sqlite issue cannot break message ingestion.
        Args:
            chat_id (int): Telegram chat id.
            topic_id (int): Forum topic id.
            name (str): Latest display name from a service event.
        Examples:
            >>> from sevn.channels.telegram import TelegramAdapter
            >>> adapter = TelegramAdapter(resolved_bot_token="t")
            >>> adapter._upsert_topic_name(1, 2, "general") is None
            True
        """
        if self._conn is None:
            return
        try:
            self._conn.execute(
                """
                INSERT INTO telegram_topic_names (chat_id, topic_id, name, updated_at)
                VALUES (?, ?, ?, datetime('now'))
                ON CONFLICT(chat_id, topic_id) DO UPDATE SET
                    name = excluded.name,
                    updated_at = excluded.updated_at
                """,
                (chat_id, topic_id, name),
            )
            self._conn.commit()
        except sqlite3.Error:
            logger.exception("telegram_topic_names_upsert_failed")

    def _apply_forum_service(self, msg: dict[str, Any]) -> None:
        """Capture topic-name updates from ``forum_topic_{created,edited}`` events.
        Side-effects only: drops the latest name into the
        ``telegram_topic_names`` table via :meth:`_upsert_topic_name`.
        Args:
            msg (dict[str, Any]): Telegram message object carrying a
                ``forum_topic_created`` or ``forum_topic_edited`` blob.
        Examples:
            >>> from sevn.channels.telegram import TelegramAdapter
            >>> adapter = TelegramAdapter(resolved_bot_token="t")
            >>> adapter._apply_forum_service({}) is None
            True
        """
        chat = msg.get("chat")
        if not isinstance(chat, dict):
            return
        cid = chat.get("id")
        if not isinstance(cid, int):
            return
        mtid = msg.get("message_thread_id")
        tid = int(mtid) if isinstance(mtid, int) else 0
        created = msg.get("forum_topic_created")
        edited = msg.get("forum_topic_edited")
        blob = created if isinstance(created, dict) else edited
        if isinstance(blob, dict):
            n = blob.get("name")
            if isinstance(n, str) and n.strip():
                self._upsert_topic_name(cid, tid, n.strip())

    def _access_allows(
        self,
        *,
        chat: dict[str, Any],
        user_id: int,
        topic_id: int | None,
    ) -> bool:
        """Apply DM policy / allowlist filters to one inbound message.
        DM chats consult ``self._cfg.dm_policy`` (``OPEN`` lets anyone in,
        ``ALLOWLIST`` / ``PAIRING`` consult ``allowed_users``, ``DISABLED``
        rejects). Group / supergroup chats consult ``allowed_groups`` and
        any per-topic ``allow_from`` restriction.
        Args:
            chat (dict[str, Any]): Telegram chat object (must include
                ``id`` and ``type``).
            user_id (int): Sender id.
            topic_id (int | None): Normalised topic id (``None`` outside
                forum supergroups).
        Returns:
            bool: True when the message should be accepted.
        Examples:
            >>> from sevn.channels.telegram import TelegramAdapter
            >>> adapter = TelegramAdapter(resolved_bot_token="t")
            >>> adapter._access_allows(
            ...     chat={"id": 1, "type": "private"}, user_id=2, topic_id=None
            ... )
            True
            >>> adapter._access_allows(chat={"type": "private"}, user_id=2, topic_id=None)
            False
        """
        ctype = str(chat.get("type") or "")
        chat_id = chat.get("id")
        if not isinstance(chat_id, int):
            return False
        if ctype == "private":
            pol = self._cfg.dm_policy
            if pol == DMPolicy.DISABLED:
                return False
            if pol == DMPolicy.OPEN:
                return True
            allow = set(self._cfg.allowed_users)
            if pol in (DMPolicy.ALLOWLIST, DMPolicy.PAIRING):
                if user_id in allow:
                    return True
                if pol == DMPolicy.PAIRING and self._pairing_store is not None:
                    return bool(self._pairing_store.is_approved(self.name, str(user_id)))
                return False
            return False
        # groups / supergroups / channel
        groups = self._cfg.allowed_groups
        if groups and chat_id not in groups:
            return False
        if topic_id is not None:
            tcfg = self._cfg.topics.get(topic_id)
            if tcfg and tcfg.allow_from and user_id not in tcfg.allow_from:
                return False
        return True

    def _topic_ignored(self, topic_id: int | None) -> bool:
        """Return True when messages in ``topic_id`` are configured to be dropped.
        Args:
            topic_id (int | None): Normalised topic id.
        Returns:
            bool: True when the topic has ``ignored=True`` in config.
        Examples:
            >>> from sevn.channels.telegram import TelegramAdapter
            >>> adapter = TelegramAdapter(resolved_bot_token="t")
            >>> adapter._topic_ignored(None)
            False
            >>> adapter._topic_ignored(42)
            False
        """
        if topic_id is None:
            return False
        tcfg = self._cfg.topics.get(topic_id)
        return bool(tcfg and tcfg.ignored)

    def _topic_disable_preview(self, topic_id: int | None) -> bool | None:
        """Return the per-topic ``disable_web_page_preview`` override (if any).
        Args:
            topic_id (int | None): Normalised topic id.
        Returns:
            bool | None: ``True`` / ``False`` from config, or ``None`` when
            no topic override applies.
        Examples:
            >>> from sevn.channels.telegram import TelegramAdapter
            >>> adapter = TelegramAdapter(resolved_bot_token="t")
            >>> adapter._topic_disable_preview(None) is None
            True
            >>> adapter._topic_disable_preview(99) is None
            True
        """
        if topic_id is None:
            return None
        tcfg = self._cfg.topics.get(topic_id)
        if tcfg is None:
            return None
        return bool(tcfg.disable_link_preview)

    def _attachment_descriptors(self, msg: dict[str, Any]) -> list[dict[str, Any]]:
        """Project attachments from a Telegram message into ``IncomingMessage`` rows.
        Picks the largest photo entry (last in the Telegram ``photo`` list)
        and copies through descriptor metadata for documents, audio, video,
        and voice notes. The returned dicts intentionally include only the
        ``file_id`` (plus shape hints) so callers download lazily.
        Args:
            msg (dict[str, Any]): Telegram message object.
        Returns:
            list[dict[str, Any]]: Plain-dict descriptors with a ``type`` and
            ``file_id`` for each attachment; empty when none are present.
        Examples:
            >>> from sevn.channels.telegram import TelegramAdapter
            >>> adapter = TelegramAdapter(resolved_bot_token="t")
            >>> adapter._attachment_descriptors({})
            []
            >>> adapter._attachment_descriptors(
            ...     {"document": {"file_id": "abc", "file_name": "a.txt"}}
            ... )
            [{'type': 'document', 'file_id': 'abc', 'file_name': 'a.txt'}]
        """
        out: list[dict[str, Any]] = []
        photos = msg.get("photo")
        if isinstance(photos, list) and photos:
            last = photos[-1]
            if isinstance(last, dict) and last.get("file_id"):
                meta = {
                    k: last[k] for k in ("file_id", "width", "height", "file_size") if k in last
                }
                meta["type"] = "photo"
                out.append(meta)
        for key, typ in (
            ("document", "document"),
            ("audio", "audio"),
            ("video", "video"),
            ("voice", "voice"),
        ):
            blob = msg.get(key)
            if isinstance(blob, dict) and blob.get("file_id"):
                row: dict[str, Any] = {"type": typ, "file_id": str(blob["file_id"])}
                fn = blob.get("file_name")
                if isinstance(fn, str):
                    row["file_name"] = fn
                dur = blob.get("duration")
                if isinstance(dur, int | float):
                    row["duration_s"] = float(dur)
                fs = blob.get("file_size")
                if isinstance(fs, int):
                    row["file_size"] = fs
                out.append(row)
        return out

    async def download_attachment(
        self,
        file_id: str,
        *,
        dest_dir: Path,
        attachment_type: str = "voice",
        suggested_name: str | None = None,
    ) -> Path:
        """Download one Telegram attachment via ``getFile`` + HTTPS fetch.

        Args:
            file_id (str): Bot API ``file_id`` from the inbound update.
            dest_dir (Path): Directory under ``channel_files/<session_id>/``.
            attachment_type (str): ``voice``, ``audio``, ``document``, etc.
            suggested_name (str | None): Optional filename hint from the update.

        Returns:
            Path: Absolute path to the downloaded bytes on disk.

        Raises:
            RuntimeError: When Bot API or download fails.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramInboundMixin.download_attachment)
            True
        """
        token = self._cfg.bot_token
        if not token:
            msg = "telegram bot token not configured"
            raise RuntimeError(msg)
        data = await self._api("getFile", {"file_id": file_id})
        if not data.get("ok"):
            msg = f"telegram getFile failed for file_id={file_id!r}"
            raise RuntimeError(msg)
        result = data.get("result")
        if not isinstance(result, dict):
            msg = "telegram getFile missing result"
            raise RuntimeError(msg)
        remote_path = str(result.get("file_path") or "").strip()
        if not remote_path:
            msg = "telegram getFile missing file_path"
            raise RuntimeError(msg)
        await asyncio.to_thread(dest_dir.mkdir, parents=True, exist_ok=True)
        suffix = Path(remote_path).suffix.lower()
        if not suffix:
            suffix = ".ogg" if attachment_type == "voice" else ".bin"
        if suggested_name and suggested_name.strip():
            name = Path(suggested_name.strip()).name
        else:
            stem = attachment_type or "attachment"
            name = f"{stem}-{file_id[:8]}{suffix}"
        out_path = (dest_dir / name).resolve()
        url = f"{_BOT_API}/file/bot{token}/{remote_path}"
        client = self._external_client
        if client is None:
            raise RuntimeError("telegram_http_client_not_initialized")
        resp = await client.get(url)
        if resp.status_code != 200:
            msg = f"telegram file download failed status={resp.status_code}"
            raise RuntimeError(msg)
        out_path.write_bytes(resp.content)
        return out_path

    def _is_bot_self_reply(self, reply_to_message: dict[str, Any]) -> bool:
        """True when the user replied to this bot's own message (§3.2, §10.17).

        Args:
            reply_to_message (dict[str, Any]): Telegram ``reply_to_message`` blob.

        Returns:
            bool: Whether quote text must be suppressed for the LLM context.

        Examples:
            >>> from sevn.channels.telegram_config import TelegramConfig
            >>> cfg = TelegramConfig(bot_token="", bot_user_id=99)
            >>> from sevn.channels.telegram import TelegramAdapter
            >>> a = TelegramAdapter(config=cfg)
            >>> a._is_bot_self_reply({"from": {"id": 99, "is_bot": True}})
            True
            >>> a._is_bot_self_reply({"from": {"id": 1, "is_bot": False}})
            False
        """
        bot_uid = self._cfg.bot_user_id
        if bot_uid is None:
            return False
        rtm_from = reply_to_message.get("from")
        if not isinstance(rtm_from, dict):
            return False
        if not rtm_from.get("is_bot"):
            return False
        rtm_id = rtm_from.get("id")
        return rtm_id is not None and str(rtm_id) == str(bot_uid)

    async def _populate_bot_user_id_from_getme(self) -> None:
        """Resolve ``TelegramConfig.bot_user_id`` via Bot API ``getMe`` (§10.17).

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramInboundMixin._populate_bot_user_id_from_getme)
            True
        """
        if self._cfg.bot_user_id is not None:
            return
        data = await self._api("getMe", {})
        if not data.get("ok"):
            self._warn_bot_user_id_unresolved(reason="getMe_failed")
            return
        result = data.get("result")
        if not isinstance(result, dict):
            self._warn_bot_user_id_unresolved(reason="getMe_missing_result")
            return
        uid = result.get("id")
        if not isinstance(uid, int):
            self._warn_bot_user_id_unresolved(reason="getMe_missing_id")
            return
        self._cfg = self._cfg.model_copy(update={"bot_user_id": uid})

    def _warn_bot_user_id_unresolved(self, *, reason: str) -> None:
        """Emit one boot warning when ``bot_user_id`` cannot be resolved (§10.17).

        Args:
            reason (str): Short failure classifier for operators.

        Examples:
            >>> from sevn.channels.telegram import TelegramAdapter
            >>> a = TelegramAdapter(resolved_bot_token="t")
            >>> a._warn_bot_user_id_unresolved(reason="test")
            >>> a._bot_user_id_warned
            True
        """
        if self._bot_user_id_warned:
            return
        self._bot_user_id_warned = True
        logger.warning(
            "telegram_bot_user_id_unresolved reason={} legacy_reply_quotes=enabled",
            reason,
        )

    def parse_webhook(self, payload: dict[str, Any]) -> IncomingMessage | None:
        """Normalise a raw Telegram update into an :class:`IncomingMessage`.
        Deduplicates by ``update_id`` via :meth:`_remember_update` so retries
        on the webhook path do not double-deliver. Returns ``None`` for
        duplicate updates, malformed payloads, or events the gateway does
        not consume (channel posts, etc.).
        Args:
            payload (dict[str, Any]): Raw Telegram update body.
        Returns:
            IncomingMessage | None: Normalised inbound envelope, or ``None``
            when the update should be ignored.
        Examples:
            >>> from sevn.channels.telegram import TelegramAdapter
            >>> adapter = TelegramAdapter(resolved_bot_token="t")
            >>> adapter.parse_webhook({}) is None
            True
            >>> adapter.parse_webhook({"update_id": "bad"}) is None
            True
        """
        if not isinstance(payload, dict):
            return None
        uid_raw = payload.get("update_id")
        try:
            update_id = int(uid_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        if not self._remember_update(update_id):
            return None
        inline_cfg = resolve_inline_config(self._cfg.inline)
        if inline_cfg.enabled:
            if "inline_query" in payload:
                return self._parse_inline_query(payload)
            if inline_cfg.feedback and "chosen_inline_result" in payload:
                return self._parse_chosen_inline_result(payload)
        if "callback_query" in payload:
            return self._parse_callback_query(payload)
        msg = payload.get("message") or payload.get("edited_message")
        if isinstance(msg, dict):
            return self._parse_message(payload, msg, edited="edited_message" in payload)
        return None

    def _parse_callback_query(self, payload: dict[str, Any]) -> IncomingMessage | None:
        """Normalise a ``callback_query`` update into an :class:`IncomingMessage`.
        Applies DM-policy and topic filters, expands compact overflow
        tokens via the callback-overflow store when a sqlite connection is
        attached, and populates ``metadata.callback_query_id`` so the
        gateway can answer the query.
        Args:
            payload (dict[str, Any]): Raw Telegram update; must contain
                ``callback_query``.
        Returns:
            IncomingMessage | None: Normalised envelope, or ``None`` when
            the callback fails access filters or is malformed.
        Examples:
            >>> import inspect
            >>> inspect.signature(
            ...     TelegramInboundMixin._parse_callback_query
            ... ).return_annotation
            'IncomingMessage | None'
        """
        cq = payload["callback_query"]
        if not isinstance(cq, dict):
            return None
        from_blob = cq.get("from")
        if not isinstance(from_blob, dict):
            return None
        uid = from_blob.get("id")
        if not isinstance(uid, int):
            return None
        data_raw = cq.get("data") or ""
        data = data_raw if isinstance(data_raw, str) else ""
        msg = cq.get("message")
        chat: dict[str, Any] = {}
        message_id: int | None = None
        if isinstance(msg, dict):
            message_id = msg.get("message_id") if isinstance(msg.get("message_id"), int) else None
            cr = msg.get("chat")
            if isinstance(cr, dict):
                chat = cr
        chat_id = chat.get("id")
        if not isinstance(chat_id, int):
            return None
        mtid = cq.get("message_thread_id")
        if mtid is None and isinstance(msg, dict):
            mtid = msg.get("message_thread_id")
        api_thread_id = int(mtid) if isinstance(mtid, int) else None
        topic_id = _normalize_topic_id(mtid)
        if not self._access_allows(chat=chat, user_id=uid, topic_id=topic_id):
            return None
        if self._topic_ignored(topic_id):
            return None
        if self._conn is not None:
            expanded = resolve_dispatcher_overflow_callback_data(
                self._conn,
                data=data,
                chat_id=chat_id,
            )
            if expanded is not None:
                data = expanded
        cq_id = cq.get("id")
        cq_id_str = str(cq_id) if cq_id is not None else ""
        meta: dict[str, Any] = {
            "chat_id": chat_id,
            "topic_id": topic_id,
            "telegram_thread_id": api_thread_id,
            "message_id": message_id or 0,
            "is_callback": True,
            "callback_query_id": cq_id_str,
            "is_edited_message": False,
            "reply_to_message_id": None,
            "disable_link_preview": self._topic_disable_preview(topic_id),
            "session_scope_override": _session_scope_override(chat_id, topic_id),
            "callback_data": data,
            "telegram_chat_id": str(chat_id),
        }
        return IncomingMessage(
            channel=self.name,
            user_id=str(uid),
            text=data,
            raw=payload,
            attachments=[],
            metadata=meta,
        )

    def _parse_inline_query(self, payload: dict[str, Any]) -> IncomingMessage | None:
        """Normalise an ``inline_query`` update into an :class:`IncomingMessage`.

        Inline queries have no chat context; per-source auth is applied in
        :mod:`sevn.gateway.telegram.telegram_inline` (D8). Returns ``None`` when the
        payload is malformed.

        Args:
            payload (dict[str, Any]): Raw Telegram update; must contain
                ``inline_query``.

        Returns:
            IncomingMessage | None: Normalised envelope tagged with
            ``metadata.is_inline_query``, or ``None`` when ignored.

        Examples:
            >>> from sevn.channels.telegram import TelegramAdapter
            >>> adapter = TelegramAdapter(resolved_bot_token="t")
            >>> payload = {
            ...     "update_id": 1,
            ...     "inline_query": {
            ...         "id": "q1",
            ...         "from": {"id": 42, "first_name": "Alice"},
            ...         "query": "weather",
            ...         "offset": "",
            ...     },
            ... }
            >>> msg = adapter._parse_inline_query(payload)
            >>> msg is not None and msg.metadata["inline_query_id"] == "q1"
            True
        """
        iq = payload.get("inline_query")
        if not isinstance(iq, dict):
            return None
        from_blob = iq.get("from")
        if not isinstance(from_blob, dict):
            return None
        uid = from_blob.get("id")
        if not isinstance(uid, int):
            return None
        query_id = iq.get("id")
        if query_id is None:
            return None
        query_raw = iq.get("query")
        query_text = query_raw if isinstance(query_raw, str) else ""
        offset_raw = iq.get("offset")
        offset = offset_raw if isinstance(offset_raw, str) else ""
        meta: dict[str, Any] = {
            "is_inline_query": True,
            "inline_query_id": str(query_id),
            "inline_offset": offset,
            "inline_from": dict(from_blob),
        }
        location = iq.get("location")
        if isinstance(location, dict):
            meta["inline_location"] = dict(location)
        return IncomingMessage(
            channel=self.name,
            user_id=str(uid),
            text=query_text,
            raw=payload,
            attachments=[],
            metadata=meta,
        )

    def _parse_chosen_inline_result(self, payload: dict[str, Any]) -> IncomingMessage | None:
        """Normalise a ``chosen_inline_result`` update into an :class:`IncomingMessage`.

        Emitted only when ``channels.telegram.inline.feedback`` is enabled (D7).
        Returns ``None`` when the payload is malformed.

        Args:
            payload (dict[str, Any]): Raw Telegram update; must contain
                ``chosen_inline_result``.

        Returns:
            IncomingMessage | None: Normalised envelope tagged with
            ``metadata.is_chosen_inline_result``, or ``None`` when ignored.

        Examples:
            >>> from sevn.channels.telegram import TelegramAdapter
            >>> adapter = TelegramAdapter(resolved_bot_token="t")
            >>> payload = {
            ...     "update_id": 2,
            ...     "chosen_inline_result": {
            ...         "result_id": "r1",
            ...         "from": {"id": 42},
            ...         "query": "weather",
            ...     },
            ... }
            >>> msg = adapter._parse_chosen_inline_result(payload)
            >>> msg is not None and msg.metadata["inline_result_id"] == "r1"
            True
        """
        cir = payload.get("chosen_inline_result")
        if not isinstance(cir, dict):
            return None
        from_blob = cir.get("from")
        if not isinstance(from_blob, dict):
            return None
        uid = from_blob.get("id")
        if not isinstance(uid, int):
            return None
        result_id = cir.get("result_id")
        if result_id is None:
            return None
        query_raw = cir.get("query")
        query_text = query_raw if isinstance(query_raw, str) else ""
        meta: dict[str, Any] = {
            "is_chosen_inline_result": True,
            "inline_result_id": str(result_id),
            "inline_from": dict(from_blob),
        }
        loc = cir.get("location")
        if isinstance(loc, dict):
            meta["inline_location"] = dict(loc)
        return IncomingMessage(
            channel=self.name,
            user_id=str(uid),
            text=query_text,
            raw=payload,
            attachments=[],
            metadata=meta,
        )

    def _parse_message(
        self,
        payload: dict[str, Any],
        msg: dict[str, Any],
        *,
        edited: bool,
    ) -> IncomingMessage | None:
        """Normalise a ``message`` / ``edited_message`` update.
        Handles text and caption bodies, attachments, ``/start`` deep-link
        sanitisation (per the deep-link prefix registry at the top of the
        module), reply-quote prefix construction, forum topic-name capture
        on service messages, and DM policy / allowlist filtering. Returns
        ``None`` when the message should be ignored (forum service stub,
        empty body without attachments, access policy rejection).
        Args:
            payload (dict[str, Any]): Full raw update (preserved on
                ``IncomingMessage.raw`` for debugging).
            msg (dict[str, Any]): ``message`` or ``edited_message`` blob.
            edited (bool): True when the update was an ``edited_message``.
        Returns:
            IncomingMessage | None: Normalised envelope, or ``None`` when
            the message should be dropped.
        Examples:
            >>> import inspect
            >>> "edited" in inspect.signature(TelegramInboundMixin._parse_message).parameters
            True
        """
        chat = msg.get("chat")
        if not isinstance(chat, dict):
            return None
        chat_id = chat.get("id")
        if not isinstance(chat_id, int):
            return None
        if msg.get("forum_topic_created") or msg.get("forum_topic_edited"):
            self._apply_forum_service(msg)
            return None
        rtm = msg.get("reply_to_message")
        if isinstance(rtm, dict) and (
            rtm.get("forum_topic_created") is not None or rtm.get("forum_topic_edited") is not None
        ):
            inner = rtm.get("forum_topic_created") or rtm.get("forum_topic_edited")
            if isinstance(inner, dict) and isinstance(chat.get("id"), int):
                name = inner.get("name")
                tid_raw = rtm.get("message_thread_id")
                tid = int(tid_raw) if isinstance(tid_raw, int) else 0
                if isinstance(name, str) and name.strip():
                    self._upsert_topic_name(chat_id, tid, name.strip())
        from_blob = msg.get("from")
        if not isinstance(from_blob, dict):
            return None
        uid = from_blob.get("id")
        if not isinstance(uid, int):
            return None
        mtid = msg.get("message_thread_id")
        api_thread_id = int(mtid) if isinstance(mtid, int) else None
        topic_id = _normalize_topic_id(mtid)
        if not self._access_allows(chat=chat, user_id=uid, topic_id=topic_id):
            if (
                str(chat.get("type") or "") == "private"
                and self._cfg.dm_policy == DMPolicy.PAIRING
                and self._pairing_store is not None
            ):
                display = from_blob.get("username") or from_blob.get("first_name") or ""
                return IncomingMessage(
                    channel=self.name,
                    user_id=str(uid),
                    text="",
                    raw=payload,
                    attachments=[],
                    metadata={
                        "chat_id": chat_id,
                        "pairing_pending": True,
                        "user_name": str(display),
                        "chat_type": "private",
                    },
                )
            return None
        if self._topic_ignored(topic_id):
            return None
        text_val = msg.get("text")
        cap_val = msg.get("caption")
        text = ""
        if isinstance(text_val, str):
            text = text_val.strip()
        elif isinstance(cap_val, str):
            text = cap_val.strip()
        if not text and msg.get("voice"):
            text = "[voice]"
        attachments = self._attachment_descriptors(msg)
        if not text and not attachments:
            return None
        if isinstance(text_val, str) and text_val.strip().startswith("/start"):
            raw_line = text_val.strip()
            parts = raw_line.split(maxsplit=1)
            arg = parts[1].strip() if len(parts) > 1 else ""
            if len(arg) > 256:
                arg = arg[:256]
            low = arg.lower()
            if low.startswith(("onb_", "dash_", "short_")):
                meta_extras: dict[str, Any] = {"start_deep_link": arg}
            elif arg:
                meta_extras = {"start_payload_redacted": "1"}
            else:
                meta_extras = {}
            text = "/start"
        else:
            meta_extras = {}
        reply_quote: str | None = None
        rtm2 = msg.get("reply_to_message")
        suppress_bot_self_quote = False
        if isinstance(rtm2, dict):
            reply_quote = format_reply_quote(rtm2)
            suppress_bot_self_quote = self._is_bot_self_reply(rtm2)
            if suppress_bot_self_quote:
                reply_quote = None
        message_id = msg.get("message_id")
        mid = int(message_id) if isinstance(message_id, int) else 0
        rmid = None
        if isinstance(rtm2, dict):
            rmid_raw = rtm2.get("message_id")
            if isinstance(rmid_raw, int):
                rmid = rmid_raw
        meta: dict[str, Any] = {
            "chat_id": chat_id,
            "topic_id": topic_id,
            "telegram_thread_id": api_thread_id,
            "message_id": mid,
            "is_callback": False,
            "callback_query_id": "",
            "is_edited_message": edited,
            "reply_to_message_id": rmid,
            "disable_link_preview": self._topic_disable_preview(topic_id),
            "session_scope_override": _session_scope_override(chat_id, topic_id),
            "telegram_chat_id": str(chat_id),
        }
        meta.update(meta_extras)
        if suppress_bot_self_quote:
            meta["reply_to_quote"] = None
        elif reply_quote:
            meta["reply_to_quote"] = reply_quote
        return IncomingMessage(
            channel=self.name,
            user_id=str(uid),
            text=text,
            raw=payload,
            attachments=attachments,
            metadata=meta,
        )
