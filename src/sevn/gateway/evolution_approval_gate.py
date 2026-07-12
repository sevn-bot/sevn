"""Gateway evolution approval Telegram callbacks (`specs/35-bot-evolution.md` §2.8).

Module: sevn.gateway.evolution_approval_gate
Depends: asyncio, sevn.evolution.approvals, sevn.evolution.events,
    sevn.evolution.pipeline_runner, sevn.gateway.channel_router

Exports:
    EvolutionApprovalWaitRegistry — in-process waiters keyed by ``approval_id``.
    EvolutionApprovalCallbackHandler — routes ``evo:*`` callback_query bypasses.
    build_evolution_approval_inline_keyboard — Approve / Edit / Reject keyboard payload.
    parse_evolution_callback_data — parse ``evo:<id>:<action>`` payloads.
"""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from sevn.evolution.approvals import get_approval, resolve_approval
from sevn.evolution.events import EvolutionIssueEventPayload, maybe_publish_issue_event
from sevn.evolution.pipeline_runner import run_pipeline
from sevn.gateway.channel_router import IncomingMessage
from sevn.gateway.strings import CALLBACK_AUTH_BLOCKED_TOAST, CALLBACK_GENERIC_TOAST_ACK
from sevn.runtime.background_tasks import spawn_logged
from sevn.workspace.layout import WorkspaceLayout

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig

ApprovalCallbackAction = Literal["approve", "reject", "edit"]


@dataclass
class _EvolutionApprovalWaiter:
    """One blocked approval waiter (reserved for future async pipeline hooks)."""

    event: asyncio.Event = field(default_factory=asyncio.Event)
    outcome: str | None = None


class EvolutionApprovalWaitRegistry:
    """In-process waiters for evolution approval resolution."""

    def __init__(self) -> None:
        """Create an empty waiter map.

        Examples:
            >>> isinstance(EvolutionApprovalWaitRegistry(), EvolutionApprovalWaitRegistry)
            True
        """
        self._waiters: dict[str, _EvolutionApprovalWaiter] = {}

    def resolve(self, approval_id: str, outcome: str) -> bool:
        """Unblock a registered waiter with the gate decision.

        Args:
            approval_id (str): Approval id.
            outcome (str): Terminal label.

        Returns:
            bool: ``True`` when a waiter existed and was signalled.

        Examples:
            >>> reg = EvolutionApprovalWaitRegistry()
            >>> reg.resolve("missing", "approved")
            False
        """
        waiter = self._waiters.pop(approval_id, None)
        if waiter is None:
            return False
        waiter.outcome = outcome
        waiter.event.set()
        return True


def build_evolution_approval_inline_keyboard(approval_id: str) -> dict[str, Any]:
    """Build Telegram ``inline_keyboard`` for evolution feature approval.

    Args:
        approval_id (str): Persisted approval id.

    Returns:
        dict[str, Any]: ``reply_markup``-shaped dict for outbound metadata.

    Examples:
        >>> kb = build_evolution_approval_inline_keyboard("abc")
        >>> kb["inline_keyboard"][0][0]["callback_data"]
        'evo:abc:approve'
    """
    return {
        "inline_keyboard": [
            [
                {"text": "1. Approve", "callback_data": f"evo:{approval_id}:approve"},
                {"text": "2. Edit", "callback_data": f"evo:{approval_id}:edit"},
                {"text": "3. Reject", "callback_data": f"evo:{approval_id}:reject"},
            ],
        ],
    }


def parse_evolution_callback_data(data: str) -> tuple[str, ApprovalCallbackAction] | None:
    """Parse ``evo:<approval_id>:<action>`` callback payloads.

    Args:
        data (str): Raw callback data string.

    Returns:
        tuple[str, ApprovalCallbackAction] | None: Parsed pair or ``None`` when malformed.

    Examples:
        >>> parse_evolution_callback_data("evo:abc:approve")
        ('abc', 'approve')
        >>> parse_evolution_callback_data("plan:abc:approve") is None
        True
    """
    parts = data.split(":", 2)
    if len(parts) != 3 or parts[0] != "evo":
        return None
    approval_id, action = parts[1].strip(), parts[2].strip()
    if not approval_id or action not in ("approve", "reject", "edit"):
        return None
    return approval_id, action  # type: ignore[return-value]


class EvolutionApprovalCallbackHandler:
    """Handle ``evo:*`` Telegram callbacks without LLM Guard (PlanGate-style)."""

    def __init__(
        self,
        layout: WorkspaceLayout,
        registry: EvolutionApprovalWaitRegistry,
        *,
        fanout: Any | None = None,
        owner_user_id: str | None = None,
        ws: WorkspaceConfig | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        """Store layout + waiter registry handles.

        Args:
            layout (WorkspaceLayout): Workspace layout for approval JSON.
            registry (EvolutionApprovalWaitRegistry): In-process waiters.
            fanout (Any | None): Optional :class:`EvolutionIssueEventFanout`.
            owner_user_id (str | None): Expected Telegram owner user id.
            ws (WorkspaceConfig | None): Workspace config for pipeline resume (W0.1).
            conn (sqlite3.Connection | None): Workspace SQLite for pipeline resume.

        Examples:
            >>> from pathlib import Path
            >>> from sevn.config.workspace_config import WorkspaceConfig
            >>> from sevn.workspace.layout import WorkspaceLayout
            >>> lay = WorkspaceLayout(Path("/tmp/s.json"), Path("/tmp/w"))
            >>> isinstance(
            ...     EvolutionApprovalCallbackHandler(lay, EvolutionApprovalWaitRegistry()),
            ...     EvolutionApprovalCallbackHandler,
            ... )
            True
        """
        self._layout = layout
        self._registry = registry
        self._fanout = fanout
        self._owner_user_id = owner_user_id
        self._ws = ws
        self._conn = conn

    @staticmethod
    def matches(msg: IncomingMessage) -> bool:
        """Return whether ``msg`` is an evolution approval callback.

        Args:
            msg (IncomingMessage): Normalised inbound envelope.

        Returns:
            bool: ``True`` for ``evo:<id>:<action>`` callback data.

        Examples:
            >>> from sevn.gateway.channel_router import IncomingMessage
            >>> m = IncomingMessage(
            ...     channel="telegram",
            ...     user_id="1",
            ...     text="evo:a:approve",
            ...     metadata={"callback_data": "evo:a:approve"},
            ... )
            >>> EvolutionApprovalCallbackHandler.matches(m)
            True
        """
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        raw = md.get("callback_data")
        if not isinstance(raw, str):
            raw = msg.text or ""
        return parse_evolution_callback_data(str(raw).strip()) is not None

    async def handle(
        self,
        msg: IncomingMessage,
        *,
        session_id: str,
    ) -> str | None:
        """Apply approve / reject / edit for one evolution approval.

        Args:
            msg (IncomingMessage): Callback inbound message.
            session_id (str): Gateway session id for the callback row.

        Returns:
            str | None: Optional user toast text; ``None`` when silent.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(EvolutionApprovalCallbackHandler.handle)
            True
        """
        _ = session_id
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        raw = md.get("callback_data")
        if not isinstance(raw, str):
            raw = msg.text or ""
        parsed = parse_evolution_callback_data(str(raw).strip())
        if parsed is None:
            return CALLBACK_GENERIC_TOAST_ACK
        approval_id, action = parsed
        if self._owner_user_id is not None and str(msg.user_id) != str(self._owner_user_id):
            return CALLBACK_AUTH_BLOCKED_TOAST
        approval = await asyncio.to_thread(get_approval, self._layout, approval_id)
        if approval is None or approval.status != "pending":
            return CALLBACK_GENERIC_TOAST_ACK
        if action == "edit":
            return "Edit plan in Mission Control Approvals tab — use Approve or Reject here."
        resolved, issue = await asyncio.to_thread(
            resolve_approval,
            self._layout,
            approval_id,
            action,
        )
        if resolved is None:
            return CALLBACK_GENERIC_TOAST_ACK
        self._registry.resolve(approval_id, action)
        if issue is not None and self._fanout is not None:
            payload: EvolutionIssueEventPayload = {
                "issue_id": issue.id,
                "event": "approval",
                "state": issue.state,
                "pipeline_stage": issue.pipeline_stage,
                "approval_id": approval_id,
            }
            await maybe_publish_issue_event(self._fanout, payload=payload)
        # Resume pipeline after approve (not reject) — fire-and-forget (W0.1).
        if (
            action != "reject"
            and issue is not None
            and issue.pipeline_stage == "implementing"
            and self._ws is not None
            and self._conn is not None
        ):
            spawn_logged(
                run_pipeline(
                    self._conn,
                    self._ws,
                    self._layout,
                    issue.id,
                    stage="implement",
                    fanout=self._fanout,
                ),
                label="evolution_pipeline_resume",
            )
        return CALLBACK_GENERIC_TOAST_ACK


__all__ = [
    "EvolutionApprovalCallbackHandler",
    "EvolutionApprovalWaitRegistry",
    "build_evolution_approval_inline_keyboard",
    "parse_evolution_callback_data",
]
