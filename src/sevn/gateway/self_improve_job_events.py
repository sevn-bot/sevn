"""Fan improve-job transitions to Mission Control WS + Telegram (`specs/24-dashboard.md` §2.3).
Module: sevn.gateway.self_improve_job_events
Depends: asyncio, sevn.channels.self_improve_copy, sevn.config.workspace_config,
    sevn.gateway.channel_router, sevn.self_improve.effective, sevn.self_improve.jobs.events
Exports:
    SelfImproveJobEventFanout — gateway-injected publisher.
    resolve_owner_telegram_user_id — pick DM target from Telegram allowlist.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Protocol

from loguru import logger

from sevn.channels.self_improve_copy import format_self_improve_job_telegram
from sevn.gateway.channel_router import OutgoingMessage
from sevn.self_improve.effective import effective_self_improve_enabled
from sevn.self_improve.jobs.events import ImproveJobEventPayload, improve_job_ws_topic

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig


class _SupportsPublish(Protocol):
    """Minimal Mission Control hub publish surface."""

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        """Publish one JSON payload to a dashboard topic.
        Args:
            topic (str): WebSocket topic name.
            payload (dict[str, Any]): JSON-serializable event body.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        ...


class _SupportsTelegramSend(Protocol):
    """Minimal Telegram adapter send surface."""

    async def send(self, message: OutgoingMessage) -> list[str]:
        """Deliver one outbound Telegram message.
        Args:
            message (OutgoingMessage): Gateway outbound envelope.
        Returns:
            list[str]: Provider message ids when available.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        ...


def resolve_owner_telegram_user_id(workspace: WorkspaceConfig) -> str | None:
    """Return the first configured Telegram owner user id for DM notifications.
    Args:
        workspace (WorkspaceConfig): Parsed ``sevn.json``.
    Returns:
        str | None: Stringified Telegram user id, or ``None`` when unset.
    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> resolve_owner_telegram_user_id(WorkspaceConfig.minimal()) is None
        True
    """
    ch = workspace.channels
    if ch is None or ch.telegram is None:
        return None
    allowed = ch.telegram.allowed_users
    if not allowed:
        return None
    return str(int(allowed[0]))


class SelfImproveJobEventFanout:
    """Publish ``self_improve.job.*`` topics and optional owner Telegram copy."""

    def __init__(
        self,
        *,
        hub: _SupportsPublish | None,
        telegram: _SupportsTelegramSend | None,
        workspace: WorkspaceConfig,
        owner_user_id: str | None = None,
    ) -> None:
        """Bind dashboard hub + Telegram adapter references for fan-out.
        Args:
            hub (_SupportsPublish | None): Mission Control pub/sub hub.
            telegram (_SupportsTelegramSend | None): Telegram adapter when configured.
            workspace (WorkspaceConfig): Active workspace config.
            owner_user_id (str | None): Override DM target; defaults to allowlist head.
        Examples:
            >>> from sevn.config.workspace_config import WorkspaceConfig
            >>> fan = SelfImproveJobEventFanout(
            ...     hub=None,
            ...     telegram=None,
            ...     workspace=WorkspaceConfig.minimal(),
            ... )
            >>> fan._hub is None
            True
        """
        self._hub = hub
        self._telegram = telegram
        self._workspace = workspace
        self._owner_user_id = owner_user_id or resolve_owner_telegram_user_id(workspace)
        self._lock = asyncio.Lock()
        self._last_sent: dict[tuple[str, str], float] = {}

    async def publish(self, payload: ImproveJobEventPayload) -> None:
        """Fan one improve-job event to dashboard subscribers and Telegram.
        No-ops when ``self_improve`` is effectively disabled. Telegram delivery is
        best-effort and rate-limited per ``(job_id, state)`` tuple.
        Args:
            payload (ImproveJobEventPayload): Transition fields from the worker/façade.
        Returns:
            None: Side-effect only.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SelfImproveJobEventFanout.publish)
            True
        """
        if not effective_self_improve_enabled(self._workspace):
            return
        job_id = str(payload.get("job_id", ""))
        if not job_id:
            return
        topic = improve_job_ws_topic(job_id)
        body = dict(payload)
        if self._hub is not None:
            await self._hub.publish(topic, body)
        if self._telegram is None or not self._owner_user_id:
            return
        state_key = str(payload.get("event") or payload.get("state") or "transition")
        throttle_key = (job_id, state_key)
        now = asyncio.get_running_loop().time()
        async with self._lock:
            last = self._last_sent.get(throttle_key)
            if last is not None and (now - last) < 30.0:
                return
            self._last_sent[throttle_key] = now
        note = format_self_improve_job_telegram(payload)
        metadata: dict[str, Any] = {"chat_id": int(self._owner_user_id)}
        if note.inline_keyboard is not None:
            metadata["inline_keyboard"] = note.inline_keyboard
        try:
            await self._telegram.send(
                OutgoingMessage(
                    channel="telegram",
                    user_id=self._owner_user_id,
                    text=note.text,
                    metadata=metadata,
                ),
            )
        except Exception:
            logger.exception(
                "self_improve_job_telegram_notify_failed job_id={} state={}",
                job_id,
                state_key,
            )
