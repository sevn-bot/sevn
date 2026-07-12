"""Owner-only ``/improve`` slash command (`specs/35-bot-evolution.md` §2.9).

Module: sevn.gateway.commands.self_improve_commands
Depends: sevn.self_improve.effective, sevn.self_improve.facade, sevn.self_improve.types

Exports:
    SelfImproveCommandHandler — enqueue an improve job from Telegram.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from sevn.self_improve.effective import effective_self_improve_enabled
from sevn.self_improve.types import ImproveJobId, OwnerPrincipal

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.gateway.channel_router import ChannelRouter, IncomingMessage
    from sevn.workspace.layout import WorkspaceLayout

EnqueueImproveFn = Callable[..., Awaitable[ImproveJobId]]


class SelfImproveCommandHandler:
    """Handle ``/improve`` before the LLM pipeline."""

    def __init__(
        self,
        *,
        workspace: WorkspaceConfig,
        layout: WorkspaceLayout,
        router: ChannelRouter,
        enqueue_improve: EnqueueImproveFn,
    ) -> None:
        """Bind workspace context and enqueue callable.

        Args:
            workspace (WorkspaceConfig): Parsed workspace config.
            layout (WorkspaceLayout): Resolved layout.
            router (ChannelRouter): Channel router for owner checks.
            enqueue_improve (EnqueueImproveFn): Gateway-bound enqueue façade.

        Examples:
            >>> SelfImproveCommandHandler.__name__
            'SelfImproveCommandHandler'
        """
        self._workspace = workspace
        self._layout = layout
        self._router = router
        self._enqueue_improve = enqueue_improve

    def matches_slash(self, msg: IncomingMessage) -> bool:
        """Return whether *msg* is ``/improve``.

        Args:
            msg (IncomingMessage): Inbound message.

        Returns:
            bool: ``True`` for the improve slash command.

        Examples:
            >>> from sevn.gateway.channel_router import IncomingMessage
            >>> h = SelfImproveCommandHandler.__new__(SelfImproveCommandHandler)
            >>> h.matches_slash(
            ...     IncomingMessage(channel="telegram", user_id="1", text="/improve"),
            ... )
            True
        """
        text = (msg.text or "").strip().lower()
        return text == "/improve" or text.startswith("/improve ")

    async def handle(self, msg: IncomingMessage, *, session_id: str) -> str | None:
        """Enqueue one improve job for the owner.

        Args:
            msg (IncomingMessage): Inbound slash command.
            session_id (str): Active gateway session id.

        Returns:
            str | None: User-visible status line.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SelfImproveCommandHandler.handle)
            True
        """
        _ = session_id
        if not self._router._resolve_owner_flag(msg):
            return "Self-improve commands are owner-only."
        if not effective_self_improve_enabled(self._workspace):
            return "Self-improve is disabled for this workspace."
        workspace_id = self._workspace.workspace_root or str(self._layout.content_root)
        principal = OwnerPrincipal(principal_kind="owner", principal_id=msg.user_id)
        job_id = await self._enqueue_improve(
            workspace_id=workspace_id,
            experiment_id="default",
            trigger="manual",
            correlation_id=None,
            owner_principal=principal,
        )
        return f"Queued improve job {job_id}. Track it in Mission Control → Self-improve → Jobs."


__all__ = ["SelfImproveCommandHandler"]
