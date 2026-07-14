"""Gateway PlanGate adapter + Telegram callback resume (`specs/17-gateway.md` §2.6 Wave 6).

Module: sevn.gateway.routing.plan_gate
Depends: sevn.agent.executors.plan_gate_store, sevn.agent.executors.cd_types, sevn.gateway.channel_router

Exports:
    PlanGateWaitRegistry — in-process waiters keyed by ``plan_id``.
    SqlitePlanGate — ``PlanGatePort`` backed by ``pending_plans`` + Telegram UI.
    PlanGateCallbackHandler — routes ``plan:*`` callback_query bypasses.
    build_plan_inline_keyboard — Approve / Edit / Reject keyboard payload.
    format_plan_message_text — user-visible plan summary for Telegram.
    parse_plan_callback_data — parse ``plan:<id>:<action>`` payloads.
"""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Literal

from sevn.agent.executors.cd_types import CdBackendLiteral, Plan
from sevn.agent.executors.plan_gate_store import (
    load_pending_plan_by_id,
    store_pending_plan,
    update_pending_plan_status,
)
from sevn.agent.tracing.sink import TraceSink
from sevn.gateway.channel_router import ChannelRouter, IncomingMessage, OutgoingMessage
from sevn.gateway.util.strings import CALLBACK_AUTH_BLOCKED_TOAST, CALLBACK_GENERIC_TOAST_ACK

PlanGateOutcome = Literal["approved", "superseded"] | Plan


@dataclass
class _PlanGateWaiter:
    """One blocked ``await_approval`` caller."""

    event: asyncio.Event = field(default_factory=asyncio.Event)
    outcome: PlanGateOutcome | None = None


class PlanGateWaitRegistry:
    """In-process waiters for ``SqlitePlanGate.await_approval``."""

    def __init__(self) -> None:
        """Create an empty waiter map.

        Examples:
            >>> isinstance(PlanGateWaitRegistry(), PlanGateWaitRegistry)
            True
        """
        self._waiters: dict[str, _PlanGateWaiter] = {}

    def register(self, plan_id: str) -> _PlanGateWaiter:
        """Create or return the waiter for ``plan_id``.

        Args:
            plan_id (str): ``pending_plans.plan_id``.

        Returns:
            _PlanGateWaiter: Waiter whose ``event`` unblocks ``await_approval``.

        Examples:
            >>> reg = PlanGateWaitRegistry()
            >>> w = reg.register("p1")
            >>> isinstance(w.event, asyncio.Event)
            True
        """
        waiter = _PlanGateWaiter()
        self._waiters[plan_id] = waiter
        return waiter

    def resolve(self, plan_id: str, outcome: PlanGateOutcome) -> bool:
        """Unblock a registered waiter with the gate decision.

        Args:
            plan_id (str): ``pending_plans.plan_id``.
            outcome (PlanGateOutcome): Terminal gate label or edited plan.

        Returns:
            bool: ``True`` when a waiter existed and was signalled.

        Examples:
            >>> reg = PlanGateWaitRegistry()
            >>> w = reg.register("p1")
            >>> reg.resolve("p1", "approved")
            True
            >>> w.outcome
            'approved'
        """
        waiter = self._waiters.pop(plan_id, None)
        if waiter is None:
            return False
        waiter.outcome = outcome
        waiter.event.set()
        return True

    def supersede_all(self, plan_ids: list[str]) -> None:
        """Signal superseded for each plan id (new inbound user message).

        Args:
            plan_ids (list[str]): Ids returned from :func:`supersede_awaiting_for_session`.

        Examples:
            >>> reg = PlanGateWaitRegistry()
            >>> w = reg.register("p1")
            >>> reg.supersede_all(["p1"])
            >>> w.outcome
            'superseded'
        """
        for plan_id in plan_ids:
            self.resolve(plan_id, "superseded")


def build_plan_inline_keyboard(plan_id: str) -> dict[str, Any]:
    """Build Telegram ``inline_keyboard`` for plan approval (PRD 04 §5.4).

    Args:
        plan_id (str): Persisted ``pending_plans`` id.

    Returns:
        dict[str, Any]: ``reply_markup``-shaped dict for outbound metadata.

    Examples:
        >>> kb = build_plan_inline_keyboard("abc")
        >>> kb["inline_keyboard"][0][0]["callback_data"]
        'plan:abc:approve'
    """
    return {
        "inline_keyboard": [
            [
                {"text": "1. Approve", "callback_data": f"plan:{plan_id}:approve"},
                {"text": "2. Edit", "callback_data": f"plan:{plan_id}:edit"},
                {"text": "3. Reject", "callback_data": f"plan:{plan_id}:reject"},
            ],
        ],
    }


def format_plan_message_text(plan: Plan) -> str:
    """Render a compact plan summary for Telegram.

    Args:
        plan (Plan): Structured C/D plan artefact.

    Returns:
        str: User-visible multi-line summary.

    Examples:
        >>> from sevn.agent.executors.cd_types import Plan, PlanStep
        >>> p = Plan(
        ...     steps=[PlanStep(id="1", title="step")],
        ...     summary="do work",
        ...     meta=Plan.Meta(complexity="C", registry_version=1),
        ... )
        >>> "do work" in format_plan_message_text(p)
        True
    """
    lines = [plan.summary.strip() or "Plan", ""]
    for step in plan.steps:
        lines.append(f"{step.id}. {step.title}")
    return "\n".join(lines).strip()


def parse_plan_callback_data(data: str) -> tuple[str, str] | None:
    """Parse ``plan:<plan_id>:<action>`` callback payloads.

    Args:
        data (str): Raw callback data string.

    Returns:
        tuple[str, str] | None: ``(plan_id, action)`` or ``None`` when malformed.

    Examples:
        >>> parse_plan_callback_data("plan:abc:approve")
        ('abc', 'approve')
        >>> parse_plan_callback_data("menu:home") is None
        True
    """
    parts = data.split(":", 2)
    if len(parts) != 3 or parts[0] != "plan":
        return None
    plan_id, action = parts[1].strip(), parts[2].strip()
    if not plan_id or not action:
        return None
    return plan_id, action


class SqlitePlanGate:
    """Production ``PlanGatePort`` using SQLite + Telegram callbacks."""

    def __init__(
        self,
        *,
        conn: sqlite3.Connection,
        router: ChannelRouter,
        registry: PlanGateWaitRegistry,
        channel: str,
        user_id: str,
        route_metadata: dict[str, Any],
        c_d_backend: CdBackendLiteral = "dspy",
    ) -> None:
        """Bind gate state to one outbound channel session.

        Args:
            conn (sqlite3.Connection): Gateway SQLite handle.
            router (ChannelRouter): Router for plan post + resume path.
            registry (PlanGateWaitRegistry): Shared in-process waiters.
            channel (str): Delivery channel key (e.g. ``telegram``).
            user_id (str): Session owner user id for auth checks.
            route_metadata (dict[str, Any]): Outbound routing hints (``chat_id``, ...).
            c_d_backend (CdBackendLiteral): Backend label stored on the row.

        Examples:
            >>> import sqlite3
            >>> from sevn.storage.migrate import apply_migrations
            >>> c = sqlite3.connect(":memory:")
            >>> apply_migrations(c)
            >>> g = SqlitePlanGate(
            ...     conn=c,
            ...     router=object(),
            ...     registry=PlanGateWaitRegistry(),
            ...     channel="telegram",
            ...     user_id="1",
            ...     route_metadata={},
            ... )
            >>> g._channel
            'telegram'
        """
        self._conn = conn
        self._router = router
        self._registry = registry
        self._channel = channel
        self._user_id = user_id
        self._route_metadata = dict(route_metadata)
        self._c_d_backend: CdBackendLiteral = c_d_backend

    async def await_approval(
        self,
        *,
        plan: Plan,
        session_id: str,
        turn_id: str,
        trace: TraceSink | None,
    ) -> PlanGateOutcome:
        """Persist plan, post Telegram keyboard, block until callback or supersession.

        Args:
            plan (Plan): Pending plan artefact from decompose.
            session_id (str): Gateway session id.
            turn_id (str): Correlation / turn id.
            trace (TraceSink | None): Optional trace sink (unused in v1 scaffold).

        Returns:
            PlanGateOutcome: ``approved``, ``superseded``, or edited ``Plan``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SqlitePlanGate.await_approval)
            True
        """
        _ = trace
        record = await asyncio.to_thread(
            store_pending_plan,
            self._conn,
            session_id=session_id,
            turn_id=turn_id,
            plan=plan,
            c_d_backend=self._c_d_backend,
        )
        waiter = self._registry.register(record.plan_id)
        out_meta = dict(self._route_metadata)
        out_meta["inline_keyboard"] = build_plan_inline_keyboard(record.plan_id)
        await self._router.route_outgoing(
            OutgoingMessage(
                channel=self._channel,
                user_id=self._user_id,
                text=format_plan_message_text(plan),
                session_id=session_id,
                metadata=out_meta,
            ),
        )
        await waiter.event.wait()
        outcome = waiter.outcome
        if outcome is None:
            return "superseded"
        return outcome


class PlanGateCallbackHandler:
    """Handle ``plan:*`` Telegram callbacks without LLM Guard."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        registry: PlanGateWaitRegistry,
    ) -> None:
        """Store SQLite + waiter registry handles.

        Args:
            conn (sqlite3.Connection): Gateway SQLite handle.
            registry (PlanGateWaitRegistry): In-process approval waiters.

        Examples:
            >>> import sqlite3
            >>> from sevn.storage.migrate import apply_migrations
            >>> c = sqlite3.connect(":memory:")
            >>> apply_migrations(c)
            >>> isinstance(PlanGateCallbackHandler(c, PlanGateWaitRegistry()), PlanGateCallbackHandler)
            True
        """
        self._conn = conn
        self._registry = registry

    @staticmethod
    def matches(msg: IncomingMessage) -> bool:
        """Return whether ``msg`` is a plan approval callback.

        Args:
            msg (IncomingMessage): Normalised inbound envelope.

        Returns:
            bool: ``True`` for ``plan:<id>:<action>`` callback data.

        Examples:
            >>> from sevn.gateway.channel_router import IncomingMessage
            >>> m = IncomingMessage(
            ...     channel="telegram",
            ...     user_id="1",
            ...     text="plan:p:approve",
            ...     metadata={"callback_data": "plan:p:approve"},
            ... )
            >>> PlanGateCallbackHandler.matches(m)
            True
        """
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        raw = md.get("callback_data")
        if not isinstance(raw, str):
            raw = msg.text or ""
        return parse_plan_callback_data(str(raw).strip()) is not None

    async def handle(
        self,
        msg: IncomingMessage,
        *,
        session_id: str,
    ) -> str | None:
        """Apply approve / reject / edit and unblock the waiting ``run_cd_turn``.

        Args:
            msg (IncomingMessage): Callback inbound message.
            session_id (str): Gateway session id for the callback row.

        Returns:
            str | None: Optional user toast text; ``None`` when silent.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(PlanGateCallbackHandler.handle)
            True
        """
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        raw = md.get("callback_data")
        if not isinstance(raw, str):
            raw = msg.text or ""
        parsed = parse_plan_callback_data(str(raw).strip())
        if parsed is None:
            return CALLBACK_GENERIC_TOAST_ACK
        plan_id, action = parsed
        row = await asyncio.to_thread(load_pending_plan_by_id, self._conn, plan_id=plan_id)
        if row is None or row.status != "awaiting":
            return CALLBACK_GENERIC_TOAST_ACK
        sess_owner = self._owner_for_session(row.session_id)
        if sess_owner is not None and str(msg.user_id) != sess_owner:
            return CALLBACK_AUTH_BLOCKED_TOAST
        if action == "approve":
            await asyncio.to_thread(
                update_pending_plan_status,
                self._conn,
                plan_id=plan_id,
                status="approved",
            )
            self._registry.resolve(plan_id, "approved")
            return CALLBACK_GENERIC_TOAST_ACK
        if action == "reject":
            await asyncio.to_thread(
                update_pending_plan_status,
                self._conn,
                plan_id=plan_id,
                status="rejected",
            )
            self._registry.resolve(plan_id, "superseded")
            return CALLBACK_GENERIC_TOAST_ACK
        if action == "edit":
            return "Plan edit via Web App is not wired in this build — use Approve or Reject."
        return CALLBACK_GENERIC_TOAST_ACK

    def _owner_for_session(self, session_id: str) -> str | None:
        """Load ``gateway_sessions.user_id`` for sender-only auth.

        Args:
            session_id (str): Gateway session id.

        Returns:
            str | None: Owner user id string, or ``None`` when missing.

        Examples:
            >>> import sqlite3
            >>> from sevn.gateway.session_manager import SessionManager
            >>> from sevn.storage.migrate import apply_migrations
            >>> c = sqlite3.connect(":memory:")
            >>> apply_migrations(c)
            >>> import asyncio
            >>> sid = asyncio.run(SessionManager(c).ensure_session(
            ...     scope_key="telegram:u", channel="telegram", user_id="u",
            ... ))
            >>> h = PlanGateCallbackHandler(c, PlanGateWaitRegistry())
            >>> h._owner_for_session(sid)
            'u'
        """
        row = self._conn.execute(
            "SELECT user_id FROM gateway_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return str(row[0])


__all__ = [
    "PlanGateCallbackHandler",
    "PlanGateWaitRegistry",
    "SqlitePlanGate",
    "build_plan_inline_keyboard",
    "format_plan_message_text",
    "parse_plan_callback_data",
]
