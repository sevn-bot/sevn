"""Fan evolution issue transitions to Mission Control WS + Telegram (`specs/35-bot-evolution.md` §2.8).

Module: sevn.gateway.evolution_issue_events
Depends: asyncio, sevn.config.workspace_config, sevn.evolution.events

Exports:
    EvolutionIssueEventFanout — gateway-injected publisher for ``evolution.issue.*`` topics.

Private:
    _format_evolution_telegram — build Telegram copy for one evolution event.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Protocol

from loguru import logger

from sevn.evolution.events import EvolutionIssueEventPayload, evolution_issue_ws_topic
from sevn.gateway.channel_router import OutgoingMessage
from sevn.gateway.self_improve_job_events import resolve_owner_telegram_user_id

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


def _format_evolution_telegram(
    payload: EvolutionIssueEventPayload,
) -> tuple[str, dict[str, Any] | None]:
    """Build Telegram copy for one evolution issue event.

    Emits a distinct message when ``pr_url`` is present on a transition event
    so the operator is notified as soon as promotion creates the pull request.

    Args:
        payload (EvolutionIssueEventPayload): Event fields.

    Returns:
        tuple[str, dict[str, Any] | None]: Text and optional inline keyboard metadata.

    Examples:
        >>> text, kb = _format_evolution_telegram({"issue_id": "i1", "event": "log_line", "line": "ok"})
        >>> "i1" in text
        True
    """
    issue_id = str(payload.get("issue_id", ""))
    event = str(payload.get("event", "transition"))
    if event == "log_line":
        line = str(payload.get("line", ""))
        return f"Evolution {issue_id}: {line}", None
    if event == "approval":
        state = str(payload.get("state", ""))
        return f"Evolution {issue_id} approval resolved → {state}", None
    # pr_url notify — transition events that carry a pr_url get a prominent message.
    pr_url = str(payload.get("pr_url") or "")
    if pr_url:
        return f"Evolution {issue_id}: PR ready → {pr_url}", None
    state = str(payload.get("state", ""))
    stage = payload.get("pipeline_stage")
    suffix = f" ({stage})" if stage else ""
    return f"Evolution {issue_id}: {state}{suffix}", None


class EvolutionIssueEventFanout:
    """Publish ``evolution.issue.*`` topics and optional owner Telegram copy."""

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
            >>> fan = EvolutionIssueEventFanout(
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

    async def publish(self, payload: EvolutionIssueEventPayload) -> None:
        """Fan one evolution issue event to dashboard subscribers and Telegram.

        Args:
            payload (EvolutionIssueEventPayload): Transition or log-line fields.

        Returns:
            None: Side-effect only.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(EvolutionIssueEventFanout.publish)
            True
        """
        issue_id = str(payload.get("issue_id", ""))
        if not issue_id:
            return
        topic = evolution_issue_ws_topic(issue_id)
        body = dict(payload)
        if self._hub is not None:
            await self._hub.publish(topic, body)
        if self._telegram is None or not self._owner_user_id:
            return
        state_key = str(payload.get("event") or payload.get("state") or "transition")
        throttle_key = (issue_id, state_key)
        now = asyncio.get_running_loop().time()
        async with self._lock:
            last = self._last_sent.get(throttle_key)
            if last is not None and (now - last) < 15.0:
                return
            self._last_sent[throttle_key] = now
        text, inline_keyboard = _format_evolution_telegram(payload)
        metadata: dict[str, Any] = {"chat_id": int(self._owner_user_id)}
        if inline_keyboard is not None:
            metadata["inline_keyboard"] = inline_keyboard
        try:
            await self._telegram.send(
                OutgoingMessage(
                    channel="telegram",
                    user_id=self._owner_user_id,
                    text=text,
                    metadata=metadata,
                ),
            )
        except Exception:
            logger.exception(
                "evolution_issue_telegram_notify_failed issue_id={} event={}",
                issue_id,
                state_key,
            )


__all__ = ["EvolutionIssueEventFanout"]
