"""Outbound send/edit/attachment orchestration for TelegramAdapter.

Module: sevn.channels.telegram_outbound
Depends: asyncio, pathlib, sevn.channels.telegram_config, sevn.channels.telegram_rich

Exports:
    TelegramOutboundMixin — ``send`` / edit / attachment paths mixed into the adapter.

Examples:
    >>> import inspect
    >>> inspect.iscoroutinefunction(TelegramOutboundMixin.send)
    True
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from loguru import logger

from sevn.channels.callback_overflow import tokenize_inline_keyboard_callback_data
from sevn.channels.telegram_config import (
    TelegramSendError,
    _coerce_chat_id,
    _coerce_telegram_thread_id,
    _should_attach_reply_keyboard,
    _voice_upload_meta,
    build_reply_keyboard_markup,
    chunk_text,
)
from sevn.channels.telegram_format import to_telegram
from sevn.channels.telegram_rich import send_with_rich_fallback
from sevn.channels.telegram_rich_send import (
    TELEGRAM_RICH_DRAFT_KEY,
    TELEGRAM_STREAMING_ACTIVE_KEY,
)
from sevn.channels.telegram_send_host import TelegramSendHost
from sevn.gateway.channel_types import OutgoingMessage

TELEGRAM_STREAM_PLACEHOLDER = "…"
"""Non-empty streaming placeholder (U+2026) per ``specs/18-channel-telegram.md`` §2.3."""

_TELEGRAM_MAX_CAPTION_LENGTH = 1024
_ATTACHMENT_API: dict[str, tuple[str, str]] = {
    "document": ("sendDocument", "document"),
    "photo": ("sendPhoto", "photo"),
    "voice": ("sendVoice", "voice"),
    "audio": ("sendAudio", "audio"),
    "video": ("sendVideo", "video"),
}


class TelegramOutboundMixin(TelegramSendHost):
    """Mixed into :class:`TelegramAdapter`."""

    async def send(self, message: OutgoingMessage) -> list[str]:
        """Send an outbound message to Telegram, chunking and falling back as needed.
        Splits the body via :func:`chunk_text`, attaches inline keyboards to
        the first chunk only, and retries Markdown sends through escaped
        and plain modes when the Bot API rejects entities. When a TTS audio
        path is present in metadata the call is delegated to
        :meth:`_send_voice` instead. A missing bot token returns ``["0"]``
        so callers can short-circuit without raising in test fixtures.
        Args:
            message (OutgoingMessage): Outbound envelope. Required metadata:
                ``chat_id`` (or ``telegram_chat_id``); optional:
                ``topic_id``, ``reply_to_message_id``, ``disable_link_preview``,
                ``inline_keyboard``, ``tts_audio_path``, ``edit_message_id``.
        Returns:
            list[str]: Telegram ``message_id`` strings for each sent chunk.
            ``["0"]`` is used as a sentinel for stubbed / no-token sends;
            an empty list signals "nothing to send" (missing chat_id or
            empty text).
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramOutboundMixin.send)
            True
            >>> inspect.signature(TelegramOutboundMixin.send).return_annotation
            'list[str]'
        """
        await self._emit_trace(
            kind="channel.telegram.send",
            status="started",
            attrs={"user_id": message.user_id},
        )
        md = message.metadata if isinstance(message.metadata, dict) else {}
        chat_id = _coerce_chat_id(md.get("chat_id"))
        if chat_id is None:
            chat_id = _coerce_chat_id(md.get("telegram_chat_id"))
        if chat_id is None:
            logger.warning("telegram_send_missing_chat_id")
            return []
        token = self._cfg.bot_token
        if not token:
            logger.info("telegram_send_skipped_no_token")
            return ["0"]
        thread_id = _coerce_telegram_thread_id(md)
        reply_to = md.get("reply_to_message_id")
        reply_to_int = int(reply_to) if isinstance(reply_to, int) else None
        disable_preview = md.get("disable_link_preview")
        dwp = bool(disable_preview) if disable_preview is not None else False
        inline_keyboard = md.get("inline_keyboard")
        reply_markup: dict[str, Any] | None = None
        if isinstance(inline_keyboard, dict):
            reply_markup = inline_keyboard
        elif isinstance(inline_keyboard, str) and inline_keyboard.strip():
            try:
                reply_markup = json.loads(inline_keyboard)
            except json.JSONDecodeError:
                reply_markup = None
        if reply_markup is not None and self._conn is not None:
            reply_markup = tokenize_inline_keyboard_callback_data(
                reply_markup,
                conn=self._conn,
                chat_id=chat_id,
                topic_id=thread_id,
            )
        attachment_path = md.get("attachment_path")
        if isinstance(attachment_path, str) and attachment_path.strip():
            kind_raw = md.get("attachment_kind")
            kind = str(kind_raw).strip().lower() if kind_raw else "document"
            filename_raw = md.get("attachment_filename")
            display_name = (
                str(filename_raw).strip()
                if isinstance(filename_raw, str) and str(filename_raw).strip()
                else Path(attachment_path.strip()).name
            )
            mime_raw = md.get("attachment_mime")
            mime_hint = (
                str(mime_raw).strip()
                if isinstance(mime_raw, str) and str(mime_raw).strip()
                else "application/octet-stream"
            )
            caption = (message.text or "").strip()
            return await self._send_attachment(
                chat_id=chat_id,
                path=attachment_path.strip(),
                kind=kind,
                filename=display_name,
                mime_type=mime_hint,
                caption=caption or None,
                thread_id=thread_id,
                reply_to_int=reply_to_int,
                caption_use_rich=self._outbound_use_rich(md, caption),
            )
        tts_path = md.get("tts_audio_path")
        if isinstance(tts_path, str) and tts_path.strip():
            return await self._send_voice(chat_id, tts_path.strip(), thread_id=thread_id)
        chunks = [c for c in chunk_text(message.text or "") if c.strip()]
        if not chunks:
            return []
        edit_mid = md.get("edit_message_id")
        edit_first: int | None = int(edit_mid) if isinstance(edit_mid, int) else None
        skip_text_edit = bool(md.get("telegram_skip_text_edit"))
        first_reply_markup = reply_markup
        attach_reply_kb = False
        if first_reply_markup is None and _should_attach_reply_keyboard(
            metadata=md,
            chat_id=chat_id,
            reply_keyboard_enabled=self._cfg.reply_keyboard_enabled,
            attached_chats=self._reply_keyboard_chats,
        ):
            first_reply_markup = build_reply_keyboard_markup()
            attach_reply_kb = True
        client = await self._ensure_client()
        if client is None:
            return ["0"]
        body_markdown = message.text or ""
        streaming_active = bool(md.get(TELEGRAM_STREAMING_ACTIVE_KEY))
        rich_draft = bool(md.get(TELEGRAM_RICH_DRAFT_KEY))
        use_rich = self._outbound_use_rich(md, body_markdown, streaming_active=streaming_active)
        if use_rich and len(chunks) == 1:
            out_ids = await self._send_rich_outbound(
                markdown=body_markdown,
                chat_id=chat_id,
                thread_id=thread_id,
                reply_to_int=reply_to_int,
                disable_preview=dwp,
                reply_markup_first=first_reply_markup,
                edit_first=edit_first,
                skip_text_edit=skip_text_edit,
                streaming_active=streaming_active,
                rich_draft=rich_draft,
            )
        else:
            out_ids = await self._send_text(
                chat_id=chat_id,
                chunks=chunks,
                thread_id=thread_id,
                reply_to_int=reply_to_int,
                disable_preview=dwp,
                reply_markup_first=first_reply_markup,
                edit_first=edit_first,
                skip_text_edit=skip_text_edit,
            )
        if attach_reply_kb and out_ids and out_ids != ["0"]:
            self._reply_keyboard_chats.add(chat_id)
        await self._emit_trace(
            kind="channel.telegram.send",
            status="completed",
            attrs={"chunks": len(out_ids)},
        )
        return out_ids if out_ids else ["0"]

    def _prepare_inline_reply_markup(
        self,
        reply_markup: dict[str, Any] | None,
        *,
        chat_id: int,
        message_thread_id: int | None,
    ) -> dict[str, Any] | None:
        """Tokenize overlong callback_data before Bot API edit/send.

        Args:
            reply_markup (dict[str, Any] | None): Inline keyboard markup.
            chat_id (int): Destination chat id.
            message_thread_id (int | None): Forum thread id when set.

        Returns:
            dict[str, Any] | None: Markup safe for Telegram, or ``None``.

        Examples:
            >>> from sevn.channels.telegram import TelegramAdapter
            >>> adapter = TelegramAdapter(resolved_bot_token="t")
            >>> adapter._prepare_inline_reply_markup(None, chat_id=1, message_thread_id=None) is None
            True
        """
        if reply_markup is None:
            return None
        if self._conn is None:
            return reply_markup
        return tokenize_inline_keyboard_callback_data(
            reply_markup,
            conn=self._conn,
            chat_id=chat_id,
            topic_id=message_thread_id,
        )

    async def edit_text(
        self,
        *,
        channel_message_id: str,
        new_text: str,
        metadata: dict[str, Any] | None = None,
        send_split_followups: bool = True,
    ) -> bool:
        """``ChannelAdapter.edit_text`` override delegating to ``edit_message_text``.

        Parses ``chat_id`` and optional ``message_thread_id`` from ``metadata``
        (same hints adapters use on outbound ``OutgoingMessage``). Returns
        ``False`` when the channel message id isn't a positive integer or when
        ``chat_id`` is missing — caller falls back to a fresh send.

        Args:
            channel_message_id (str): Telegram message id captured from a
                prior :meth:`send`.
            new_text (str): Replacement body.
            metadata (dict[str, Any] | None): Must contain ``chat_id``;
                ``topic_id`` / ``telegram_thread_id`` optional.
            send_split_followups (bool): When ``False``, a ``MESSAGE_TOO_LONG``
                split edits only the first chunk (streaming defers follow-ups).

        Returns:
            bool: ``True`` on Bot API success, ``False`` on failure.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramOutboundMixin.edit_text)
            True
        """
        if not new_text.strip():
            return False
        meta = metadata or {}
        try:
            message_id_int = int(channel_message_id)
        except (TypeError, ValueError):
            return False
        chat_id_raw = meta.get("chat_id")
        try:
            chat_id_int = int(chat_id_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False
        thread_raw = meta.get("telegram_thread_id") or meta.get("topic_id")
        thread_id: int | None = None
        if thread_raw is not None:
            try:
                thread_id = int(thread_raw)
            except (TypeError, ValueError):
                thread_id = None
        streaming_active = bool(meta.get(TELEGRAM_STREAMING_ACTIVE_KEY))
        use_rich = self._outbound_use_rich(meta, new_text, streaming_active=streaming_active)
        if use_rich and not send_split_followups and len(chunk_text(new_text)) == 1:

            async def legacy_send(converted: str) -> bool:
                ids = await self._send_rendered_text(
                    chat_id=chat_id_int,
                    rendered_text=converted,
                    thread_id=thread_id,
                    reply_to_int=None,
                    disable_preview=False,
                    reply_markup_first=None,
                    edit_first=message_id_int,
                )
                return bool(ids)

            async def rich_send() -> bool:
                ok = await self.edit_rich_message(
                    chat_id=chat_id_int,
                    message_id=message_id_int,
                    markdown=new_text,
                    message_thread_id=thread_id,
                )
                if not ok:
                    raise ValueError("editMessageText rich_message failed")
                return True

            return await send_with_rich_fallback(
                reply=new_text,
                capability=self.rich_capability,
                rich_cfg=self._cfg.rich,
                parse_mode=self._cfg.parse_mode,
                legacy_send=legacy_send,
                rich_send=rich_send,
                emit_trace=self._emit_trace,
                streaming_active=streaming_active,
            )
        return await self.edit_message_text(
            chat_id=chat_id_int,
            message_id=message_id_int,
            text=new_text,
            message_thread_id=thread_id,
            send_split_followups=send_split_followups,
        )

    async def edit_message_text(
        self,
        *,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        message_thread_id: int | None = None,
        send_split_followups: bool = True,
    ) -> bool:
        """Edit message text and inline keyboard via ``editMessageText``.

        When the body exceeds Telegram's UTF-16 limit, splits via
        :func:`chunk_text`, edits chunk 0 in place, and optionally sends
        follow-up ``sendMessage`` bubbles for the remainder.

        Args:
            chat_id (int): Destination chat id.
            message_id (int): Target Telegram message id.
            text (str): New plain-text body.
            reply_markup (dict[str, Any] | None): Optional inline keyboard.
            message_thread_id (int | None): Forum ``message_thread_id`` when set.
            send_split_followups (bool): When ``False``, only the first chunk is
                edited (streaming defers follow-ups to finalize).

        Returns:
            bool: ``True`` when the Bot API reports success.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramOutboundMixin.edit_message_text)
            True
        """
        if message_id <= 0:
            return False
        if not text.strip():
            return False
        token = self._cfg.bot_token
        if not token:
            return False
        client = await self._ensure_client()
        if client is None:
            return False
        if len(chunk_text(text)) > 1:
            ok, _extra = await self._edit_or_split_long_message(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
                message_thread_id=message_thread_id,
                send_followups=send_split_followups,
            )
            return ok
        ok = await self._edit_message_text_body(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
            message_thread_id=message_thread_id,
        )
        if ok:
            return True
        split_ok, _extra = await self._edit_or_split_long_message(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
            message_thread_id=message_thread_id,
            send_followups=send_split_followups,
        )
        return split_ok

    def _remember_edit_text(self, key: tuple[int, int], text: str) -> None:
        """Record the last text edited for ``key`` in a bounded LRU.

        Args:
            key (tuple[int, int]): ``(chat_id, message_id)`` identity.
            text (str): Text now displayed on that message.

        Returns:
            None

        Examples:
            >>> from sevn.channels.telegram import TelegramAdapter
            >>> a = TelegramAdapter(resolved_bot_token="t")
            >>> a._remember_edit_text((1, 2), "hi")
            >>> a._last_edit_text[(1, 2)]
            'hi'
        """
        cache = self._last_edit_text
        cache[key] = text
        cache.move_to_end(key)
        while len(cache) > 256:
            cache.popitem(last=False)

    async def edit_reply_markup(
        self,
        *,
        chat_id: int,
        message_id: int,
        reply_markup: dict[str, Any],
        message_thread_id: int | None = None,
    ) -> bool:
        """Attach or replace inline keyboard via ``editMessageReplyMarkup``.

        Args:
            chat_id (int): Destination chat id.
            message_id (int): Target Telegram message id.
            reply_markup (dict[str, Any]): ``InlineKeyboardMarkup`` dict.
            message_thread_id (int | None): Optional forum topic id.

        Returns:
            bool: ``True`` when the Bot API reports success.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramOutboundMixin.edit_reply_markup)
            True
        """
        if message_id <= 0:
            return False
        token = self._cfg.bot_token
        if not token:
            return False
        client = await self._ensure_client()
        if client is None:
            return False
        markup = self._prepare_inline_reply_markup(
            reply_markup,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
        )
        if markup is None:
            return False
        body: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": int(message_id),
            "reply_markup": markup,
        }
        if message_thread_id is not None:
            body["message_thread_id"] = message_thread_id
        res = await self._api("editMessageReplyMarkup", body)
        if not res.get("ok"):
            logger.info(
                "telegram_edit_reply_markup_failed chat_id={} message_id={} desc={}",
                chat_id,
                message_id,
                res.get("description"),
            )
        return bool(res.get("ok"))

    async def pin_chat_message(
        self,
        *,
        chat_id: int,
        message_id: int,
        message_thread_id: int | None = None,
        disable_notification: bool = True,
    ) -> bool:
        """Pin one chat message via ``pinChatMessage``.

        Args:
            chat_id (int): Destination chat id.
            message_id (int): Telegram message id to pin.
            message_thread_id (int | None): Optional forum topic id.
            disable_notification (bool): When ``True``, suppress pin notification.

        Returns:
            bool: ``True`` when the Bot API reports success.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramOutboundMixin.pin_chat_message)
            True
        """
        token = self._cfg.bot_token
        if not token:
            return False
        client = await self._ensure_client()
        if client is None:
            return False
        body: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": int(message_id),
            "disable_notification": disable_notification,
        }
        if message_thread_id is not None:
            body["message_thread_id"] = message_thread_id
        res = await self._api("pinChatMessage", body)
        return bool(res.get("ok"))

    async def unpin_chat_message(
        self,
        *,
        chat_id: int,
        message_id: int,
        message_thread_id: int | None = None,
    ) -> bool:
        """Unpin one chat message via ``unpinChatMessage``.

        Args:
            chat_id (int): Destination chat id.
            message_id (int): Telegram message id to unpin.
            message_thread_id (int | None): Optional forum topic id.

        Returns:
            bool: ``True`` when the Bot API reports success.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramOutboundMixin.unpin_chat_message)
            True
        """
        token = self._cfg.bot_token
        if not token:
            return False
        client = await self._ensure_client()
        if client is None:
            return False
        body: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": int(message_id),
        }
        if message_thread_id is not None:
            body["message_thread_id"] = message_thread_id
        res = await self._api("unpinChatMessage", body)
        return bool(res.get("ok"))

    async def _send_attachment(
        self,
        *,
        chat_id: int,
        path: str,
        kind: str,
        filename: str,
        mime_type: str,
        caption: str | None,
        thread_id: int | None,
        reply_to_int: int | None,
        caption_use_rich: bool = False,
    ) -> list[str]:
        """Upload a workspace attachment via the §4.4 send-method matrix.

        Args:
            chat_id (int): Destination Telegram chat id.
            path (str): Workspace-relative attachment path.
            kind (str): ``attachment_kind`` key (document, photo, voice, …).
            filename (str): Multipart filename sent to Telegram.
            mime_type (str): MIME type for the multipart part.
            caption (str | None): Optional caption (truncated to Telegram limits).
            thread_id (int | None): Forum topic id when applicable.
            reply_to_int (int | None): Optional ``reply_to_message_id``.
            caption_use_rich (bool): When ``True``, render caption via ``to_telegram()``.

        Returns:
            list[str]: Platform message ids (stub ``["0"]`` when HTTP client unavailable).

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramOutboundMixin._send_attachment)
            True
        """
        method_field = _ATTACHMENT_API.get(kind)
        if method_field is None:
            raise TelegramSendError(
                method="send",
                description=f"unsupported attachment_kind: {kind}",
            )
        method, field_name = method_field

        def _load_bytes(path_str: str) -> tuple[bytes, Path] | None:
            file_path = Path(path_str)
            if not file_path.is_file():
                return None
            return file_path.read_bytes(), file_path

        loaded = await asyncio.to_thread(_load_bytes, path)
        if loaded is None:
            raise TelegramSendError(
                method=method,
                description=f"attachment file not found: {path}",
            )
        file_bytes, _file_path = loaded
        client = await self._ensure_client()
        if client is None:
            return ["0"]
        form: dict[str, Any] = {"chat_id": chat_id}
        if thread_id is not None:
            form["message_thread_id"] = thread_id
        if reply_to_int is not None:
            form["reply_to_message_id"] = reply_to_int
        if caption:
            cap_body = caption[:_TELEGRAM_MAX_CAPTION_LENGTH]
            if caption_use_rich:
                form["parse_mode"] = self._cfg.parse_mode
                form["caption"] = to_telegram(cap_body, self._cfg.parse_mode)[
                    :_TELEGRAM_MAX_CAPTION_LENGTH
                ]
            else:
                form["caption"] = cap_body
        files = {field_name: (filename, file_bytes, mime_type)}
        res = await self._api_multipart(method, data=form, files=files)
        if not res.get("ok"):
            self._log_send_api_error(method, res)
            err_code = res.get("error_code")
            raise TelegramSendError(
                method=method,
                description=str(res.get("description") or "telegram send failed"),
                error_code=int(err_code) if isinstance(err_code, int) else None,
            )
        mid = self._message_id_from_api_result(res)
        if mid is None:
            self._log_send_api_error(method, res)
            raise TelegramSendError(
                method=method,
                description="telegram response missing message_id",
            )
        logger.info(
            "telegram_send_api_ok method={} chat_id={} message_id={} attachment_kind={}",
            method,
            chat_id,
            mid,
            kind,
        )
        await self._emit_trace(
            kind="channel.telegram.send_attachment",
            status="completed",
            attrs={"method": method, "attachment_kind": kind, "message_id": mid},
        )
        return [mid]

    async def _send_voice(self, chat_id: int, path: str, *, thread_id: int | None) -> list[str]:
        """Upload a TTS file as a Telegram voice note via ``sendVoice``.
        Reads the on-disk path produced by [`specs/20-voice.md`](../specs/20-voice.md)
        (workspace ``channel_files/.tts/`` or equivalent) and POSTs multipart
        form data to the Bot API. Accepts OGG/Opus (``audio/ogg``) and MP3
        (``audio/mpeg``). Returns Telegram ``message_id`` strings with the
        same list shape as text sends.
        Args:
            chat_id (int): Destination chat id.
            path (str): Absolute or workspace-relative path to the TTS audio file.
            thread_id (int | None): Optional forum topic id (``message_thread_id``).
        Returns:
            list[str]: One ``message_id`` per uploaded voice note, or ``["0"]``
            when the file is missing, the client is unavailable, or the API rejects
            the upload.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramOutboundMixin._send_voice)
            True
        """
        await self._emit_trace(
            kind="channel.telegram.send_voice",
            status="started",
            attrs={"chat_id": chat_id, "thread_id": thread_id},
        )

        def _load_voice_bytes(path_str: str) -> tuple[bytes, Path] | None:
            audio_path = Path(path_str)
            if not audio_path.is_file():
                return None
            return audio_path.read_bytes(), audio_path

        loaded = await asyncio.to_thread(_load_voice_bytes, path)
        if loaded is None:
            logger.warning("telegram_send_voice_missing_file path={}", path)
            return ["0"]
        audio_bytes, audio_path = loaded
        if not audio_bytes:
            # Defensive guard for the "files are empty" session-log report: a TTS
            # backend can write a zero-byte file without raising (e.g. a truncated
            # subprocess write). Fail fast with a clear log instead of uploading an
            # empty voice note that Telegram will silently reject or mangle.
            logger.warning("telegram_send_voice_empty_file path={}", path)
            await self._emit_trace(
                kind="channel.telegram.send_voice",
                status="failed",
                attrs={"chat_id": chat_id, "reason": "empty_audio"},
            )
            return ["0"]
        client = await self._ensure_client()
        if client is None:
            return ["0"]
        filename, mime_type = _voice_upload_meta(audio_path)
        form: dict[str, Any] = {"chat_id": chat_id}
        if thread_id is not None:
            form["message_thread_id"] = thread_id
        files = {"voice": (filename, audio_bytes, mime_type)}
        res = await self._api_multipart("sendVoice", data=form, files=files)
        if not res.get("ok"):
            self._log_send_api_error("sendVoice", res)
            await self._emit_trace(
                kind="channel.telegram.send_voice",
                status="failed",
                attrs={"chat_id": chat_id},
            )
            err_code = res.get("error_code")
            raise TelegramSendError(
                method="sendVoice",
                description=str(res.get("description") or "sendVoice failed"),
                error_code=int(err_code) if isinstance(err_code, int) else None,
            )
        mid = self._message_id_from_api_result(res)
        if mid is None:
            self._log_send_api_error("sendVoice", res)
            raise TelegramSendError(
                method="sendVoice",
                description="telegram response missing message_id",
            )
        out_ids = [mid]
        logger.info(
            "telegram_send_api_ok method=sendVoice chat_id={} message_id={} attachment_kind=voice",
            chat_id,
            mid,
        )
        await self._emit_trace(
            kind="channel.telegram.send_voice",
            status="completed",
            attrs={"message_id": out_ids[0]},
        )
        return out_ids
