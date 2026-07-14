"""Tier-B answer placeholder + finalizer for Priority 2 (``PROBLEMS.md``).

Module: sevn.gateway.turn.turn_finalizer
Depends: sevn.gateway.channel_router (ChannelAdapter, OutgoingMessage, ChannelRouter).

The placeholder/finalize pattern guarantees the tier-B answer message exists
from the moment the executor starts. Failure paths (timeout / empty output /
cancellation) edit the placeholder rather than racing a fresh send that may
never happen. Success paths edit the placeholder with the executor's answer
when the adapter supports edits, or send a follow-up message when it doesn't.

Exports:
    TierBAnswerFinalizer — per-turn placeholder + finalize state machine.

Examples:
    >>> import inspect
    >>> inspect.isclass(TierBAnswerFinalizer)
    True
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

from sevn.channels.telegram import TELEGRAM_STREAM_PLACEHOLDER, chunk_text
from sevn.logging.structured import debug_event, preview
from sevn.prompts.fallbacks import ASSISTANT_NO_OUTPUT_PLACEHOLDER
from sevn.prompts.fallbacks import FINALIZER_FALLBACK_MESSAGES as _FALLBACK_MESSAGES

if TYPE_CHECKING:
    from sevn.gateway.channel_router import ChannelAdapter, ChannelRouter


FinalizationStatus = Literal["success", "timeout", "empty", "cancelled", "error"]
"""Terminal states for a tier-B turn (`PROBLEMS.md` Priority 2)."""


"""Default user-visible text per failure status; overridable by the caller."""


@dataclass
class TierBAnswerFinalizer:
    """Per-turn placeholder + finalize state machine.

    Lifecycle: ``place_placeholder`` → executor runs → ``finalize`` exactly
    once. Calling ``finalize`` more than once is a programming error and
    raises ``RuntimeError`` so the unit test that enforces "exactly 2
    send_message calls per tier-B turn" can catch double-finalize.

    Attributes:
        router: Gateway router used to deliver the placeholder when the
            adapter doesn't support edits (fallback path).
        adapter: Adapter targeted by this turn — used directly for edits to
            avoid the router's hygiene-filter pipeline on the second pass.
        channel: Channel key (``telegram``, ``webchat``, …).
        user_id: Destination user id.
        session_id: Owning session id.
        turn_id: Turn correlation id (`PROBLEMS.md` §V3b).
        metadata: Outbound routing hints (chat_id, topic_id, …).
        placeholder_text: Text used when sending the placeholder; defaults to
            an ellipsis. Made configurable so tests can assert exact strings.

    Examples:
        >>> from dataclasses import is_dataclass
        >>> is_dataclass(TierBAnswerFinalizer)
        True
    """

    router: ChannelRouter
    adapter: ChannelAdapter
    channel: str
    user_id: str
    session_id: str
    turn_id: str
    metadata: dict[str, Any] = field(default_factory=dict)
    placeholder_text: str = TELEGRAM_STREAM_PLACEHOLDER

    _placeholder_message_id: str | None = field(default=None, init=False)
    _finalized: bool = field(default=False, init=False)
    _last_streamed_text: str | None = field(default=None, init=False)
    _stream_needs_split_finalize: bool = field(default=False, init=False)

    @property
    def placeholder_message_id(self) -> str | None:
        """Channel-specific id of the placeholder message, set by :meth:`place_placeholder`.

        Returns:
            str | None: The id, or ``None`` when the placeholder hasn't been
            placed (or the adapter returned no ids).

        Examples:
            >>> TierBAnswerFinalizer.placeholder_message_id.__doc__ is not None
            True
        """
        return self._placeholder_message_id

    @property
    def partial_progress_text(self) -> str | None:
        """Best-effort answer text streamed before a budget/timeout finalization.

        Returns:
            str | None: Last non-placeholder streamed body, or ``None`` when nothing
            substantive was streamed.

        Examples:
            >>> TierBAnswerFinalizer.partial_progress_text.__doc__ is not None
            True
        """
        text = self._last_streamed_text
        if not text or text == self.placeholder_text:
            return None
        return text.strip() or None

    @property
    def is_finalized(self) -> bool:
        """``True`` once :meth:`finalize` has run.

        Returns:
            bool: Reflects whether the turn has been finalized.

        Examples:
            >>> TierBAnswerFinalizer.is_finalized.__doc__ is not None
            True
        """
        return self._finalized

    async def place_placeholder(self) -> str | None:
        """Send the placeholder message; record the channel id for later edit.

        Returns:
            str | None: The first channel-specific message id reported by the
            adapter, or ``None`` if the adapter returned no ids (degraded path —
            :meth:`finalize` will fall back to sending a fresh message).

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TierBAnswerFinalizer.place_placeholder)
            True
        """
        from sevn.channels.telegram import (
            TELEGRAM_RICH_DRAFT_KEY,
            TELEGRAM_STREAMING_ACTIVE_KEY,
        )
        from sevn.gateway.channel_router import OutgoingMessage  # avoid cycle

        md = dict(self.metadata)
        md[TELEGRAM_STREAMING_ACTIVE_KEY] = True
        md[TELEGRAM_RICH_DRAFT_KEY] = True
        msg = OutgoingMessage(
            channel=self.channel,
            user_id=self.user_id,
            text=self.placeholder_text,
            session_id=self.session_id,
            metadata=md,
        )
        ids = await self.adapter.send(msg)
        if ids:
            self._placeholder_message_id = str(ids[0])
        else:
            self._placeholder_message_id = None
        return self._placeholder_message_id

    async def stream_update(self, accumulated_text: str) -> None:
        """Edit the placeholder with the answer accumulated so far (Mode 1).

        Best-effort: silently no-ops when no placeholder was placed, when the
        turn has already been finalized, when the text is identical to the
        previous streamed value, or when the adapter rejects the edit. Telegram
        already absorbs "message is not modified" + 429 retry-after at the
        adapter layer, so this method only needs to dedupe at the application
        layer and catch transport exceptions.

        Args:
            accumulated_text (str): Full answer text up to the current point.
                Must not be a per-token delta — the finalizer overwrites the
                placeholder with this exact value.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TierBAnswerFinalizer.stream_update)
            True
        """
        if self._finalized:
            return
        if self._placeholder_message_id is None:
            return
        text = accumulated_text.strip()
        if not text:
            if self._last_streamed_text is None:
                text = self.placeholder_text
            else:
                return
        if text == self._last_streamed_text:
            return
        if text != self.placeholder_text:
            self.router.cancel_telegram_typing(self.session_id)
        chunks = chunk_text(text)
        stream_body = chunks[0] if len(chunks) > 1 else text
        if len(chunks) > 1:
            self._stream_needs_split_finalize = True
        changed_from_last = self._last_streamed_text is not None
        debug_event(
            "telegram.stream_update",
            session_id=self.session_id,
            turn_id=self.turn_id,
            message_id=self._placeholder_message_id,
            text_len=len(text),
            preview=preview(text),
            changed_from_last=changed_from_last,
        )
        self._last_streamed_text = text
        try:
            from sevn.channels.telegram import TELEGRAM_STREAMING_ACTIVE_KEY

            stream_meta = dict(self.metadata)
            stream_meta[TELEGRAM_STREAMING_ACTIVE_KEY] = True
            await self.adapter.edit_text(
                channel_message_id=self._placeholder_message_id,
                new_text=stream_body,
                metadata=stream_meta,
                send_split_followups=False,
            )
        except Exception:
            logger.exception(
                "turn_finalizer.stream_update failed session_id={} turn_id={}",
                self.session_id,
                self.turn_id,
            )

    async def finalize(
        self,
        *,
        status: FinalizationStatus,
        text: str | None = None,
    ) -> bool:
        """Replace the placeholder with the final text (or fallback for failures).

        Calling more than once raises ``RuntimeError`` to enforce the
        "exactly 2 send_message per tier-B turn" invariant (`PROBLEMS.md`
        Priority 2 contract item 5). Caller is responsible for placing the
        ``try/except/finally`` discipline so ``finalize`` always runs.

        Args:
            status (FinalizationStatus): Terminal disposition.
            text (str | None): For ``status="success"`` this is the executor's
                final answer; for failure statuses, ``None`` picks the canned
                fallback string. Passing ``text`` explicitly on a failure
                status overrides the canned text.

        Returns:
            bool: ``True`` when the placeholder was edited in place;
            ``False`` when the adapter doesn't support edits and a fresh
            send was used as fallback.

        Raises:
            RuntimeError: When called more than once for the same finalizer.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TierBAnswerFinalizer.finalize)
            True
        """
        if self._finalized:
            msg = (
                f"TierBAnswerFinalizer.finalize already called for turn_id={self.turn_id}; "
                "exactly one finalize is allowed per tier-B turn (PROBLEMS.md Priority 2)"
            )
            raise RuntimeError(msg)
        self._finalized = True

        final_text = text if text is not None else _FALLBACK_MESSAGES.get(status, "")
        if not final_text:
            final_text = _FALLBACK_MESSAGES["error"]
        if final_text.strip() == ASSISTANT_NO_OUTPUT_PLACEHOLDER:
            final_text = _FALLBACK_MESSAGES["empty"]

        from sevn.gateway.channel_router import OutgoingMessage  # avoid cycle

        needs_split_finalize = self._stream_needs_split_finalize or len(chunk_text(final_text)) > 1

        # Success path: route through the router with an ``edit_message_id`` hint so
        # the Telegram adapter does ``editMessageText`` instead of ``sendMessage`` —
        # the placeholder bubble becomes the final answer in place, and the router's
        # post-send hooks (quick-action markup, assistant-row insert, TTS, content
        # filter, trace) all fire as on a fresh send. Failure paths bypass the router
        # and edit directly; quick-action buttons don't belong on an error message.
        if status == "success" and self._placeholder_message_id is not None:
            md = dict(self.metadata)
            try:
                md["edit_message_id"] = int(self._placeholder_message_id)
            except (TypeError, ValueError):
                # Non-integer channel ids (e.g., webchat uuids) — fall through to the
                # adapter.edit_text path below.
                md = dict(self.metadata)
            else:
                # ``gateway_outbound_phase = "final"`` tells ChannelRouter this is
                # the closing assistant bubble so quick-action markup attachment
                # (regen / 👍 / 👎) fires after the editMessageText call.
                from sevn.gateway.telegram.telegram_quick_actions import GATEWAY_OUTBOUND_PHASE_KEY

                md[GATEWAY_OUTBOUND_PHASE_KEY] = "final"
                streamed = (self._last_streamed_text or "").strip()
                if streamed and final_text.strip() == streamed and not needs_split_finalize:
                    md["telegram_skip_text_edit"] = True
                await self.router.route_outgoing(
                    OutgoingMessage(
                        channel=self.channel,
                        user_id=self.user_id,
                        text=final_text,
                        session_id=self.session_id,
                        metadata=md,
                    ),
                )
                return True

        if self._placeholder_message_id is not None:
            edited = False
            try:
                edited = await self.adapter.edit_text(
                    channel_message_id=self._placeholder_message_id,
                    new_text=final_text,
                    metadata=dict(self.metadata),
                )
            except Exception:
                logger.exception(
                    "turn_finalizer.edit_text failed session_id={} turn_id={}",
                    self.session_id,
                    self.turn_id,
                )
                edited = False
            if edited:
                return True

        # Edit unsupported or failed — fall back to a fresh send via the router.
        await self.router.route_outgoing(
            OutgoingMessage(
                channel=self.channel,
                user_id=self.user_id,
                text=final_text,
                session_id=self.session_id,
                metadata=dict(self.metadata),
            ),
        )
        return False


__all__ = ["FinalizationStatus", "TierBAnswerFinalizer"]
