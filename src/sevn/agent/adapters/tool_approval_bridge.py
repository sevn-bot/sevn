"""Out-of-band tier-B tool approval bridge for Mission Control (MC W7).

When a ``requires_human`` gate blocks tool execution, the bridge publishes a
``mission.approval.pending`` hub event and awaits an operator verdict from
``POST /api/v1/agent/approvals/{decision_id}``.

Module: sevn.agent.adapters.tool_approval_bridge
Depends: asyncio, json, re, uuid, sevn.agent.tracing.sink, sevn.ui.dashboard.ws

Exports:
    PendingToolApproval — one in-flight operator approval decision.
    ToolApprovalBridge — pending registry + asyncio wait/resume.
    get_tool_approval_bridge — process-wide bridge accessor.
    install_tool_approval_bridge — attach bridge to gateway app state.
    summarize_tool_args — redacted args summary for approval cards.
    ack_tool_on_deps — mutate ``human_acknowledged_tools`` on ``BTierDeps``.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from sevn.agent.tracing.sink import TraceEvent, TraceSink

if TYPE_CHECKING:
    from fastapi import FastAPI

    from sevn.agent.executors.b_types import BTierDeps
    from sevn.ui.dashboard.ws import DashboardHub

ApprovalVerdict = Literal["once", "session", "always", "deny"]

_SECRET_REF_PATTERN = re.compile(r"\$\{SECRET:[^}]+\}")
_DEFAULT_TIMEOUT_S = 300.0

_bridge: ToolApprovalBridge | None = None


def get_tool_approval_bridge() -> ToolApprovalBridge | None:
    """Return the process-wide tool approval bridge when installed.

    Returns:
        ToolApprovalBridge | None: Bridge from gateway boot, or ``None`` in tests.

    Examples:
        >>> get_tool_approval_bridge() is None or isinstance(get_tool_approval_bridge(), ToolApprovalBridge)
        True
    """

    return _bridge


def install_tool_approval_bridge(app: FastAPI, *, hub: DashboardHub | None) -> ToolApprovalBridge:
    """Create and register the tool approval bridge on ``app.state``.

    Args:
        app (FastAPI): Gateway application instance.
        hub (DashboardHub | None): Dashboard pub/sub hub (may be ``None`` in tests).

    Returns:
        ToolApprovalBridge: Newly installed bridge instance.

    Examples:
        >>> from fastapi import FastAPI
        >>> from sevn.ui.dashboard.ws import DashboardHub
        >>> app = FastAPI()
        >>> bridge = install_tool_approval_bridge(app, hub=DashboardHub())
        >>> app.state.tool_approval_bridge is bridge
        True
    """

    global _bridge
    bridge = ToolApprovalBridge(hub=hub)
    app.state.tool_approval_bridge = bridge
    _bridge = bridge
    return bridge


def summarize_tool_args(args: dict[str, Any], *, max_len: int = 400) -> str:
    """Build a redacted single-line summary of tool arguments.

    Args:
        args (dict[str, Any]): Validated tool arguments.
        max_len (int): Maximum returned string length.

    Returns:
        str: JSON summary with ``${SECRET:…}`` replaced by placeholders.

    Examples:
        >>> summarize_tool_args({"path": "x", "token": "${SECRET:k:t}"})
        '{"path": "x", "token": "<redacted-secret-ref>"}'
    """

    def _redact(value: object) -> object:
        if isinstance(value, str):
            return _SECRET_REF_PATTERN.sub("<redacted-secret-ref>", value)
        if isinstance(value, dict):
            return {str(k): _redact(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_redact(item) for item in value]
        return value

    raw = json.dumps(_redact(dict(args)), sort_keys=True, default=str)
    if len(raw) <= max_len:
        return raw
    return raw[: max_len - 3] + "..."


def ack_tool_on_deps(deps: BTierDeps, tool_name: str) -> None:
    """Add ``tool_name`` to the turn template ``human_acknowledged_tools`` set.

    Args:
        deps (BTierDeps): Mutable per-run dependency bag.
        tool_name (str): Tool registry name to acknowledge.

    Returns:
        None: Mutates ``deps.tool_context_template`` in place.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.agent.executors.b_types import BTierDeps
        >>> from sevn.tools.context import ToolContext
        >>> from sevn.tools.permissions import AllowAllPermissionPolicy
        >>> deps = BTierDeps(
        ...     tool_executor=None,  # type: ignore[arg-type]
        ...     tool_context_template=ToolContext(
        ...         session_id="s",
        ...         workspace_path=Path("/tmp"),
        ...         workspace_id="w",
        ...         registry_version=1,
        ...         trace=None,
        ...         permissions=AllowAllPermissionPolicy(),
        ...     ),
        ...     workspace_path=Path("/tmp"),
        ...     registry_version=1,
        ... )
        >>> ack_tool_on_deps(deps, "delete")
        >>> "delete" in deps.tool_context_template.human_acknowledged_tools
        True
    """

    current = deps.tool_context_template.human_acknowledged_tools
    deps.tool_context_template.human_acknowledged_tools = frozenset(current | {tool_name})


@dataclass
class PendingToolApproval:
    """One in-flight operator approval decision."""

    decision_id: str
    session_id: str
    turn_id: str
    tool_name: str
    args_summary: str
    event: asyncio.Event = field(default_factory=asyncio.Event)
    verdict: ApprovalVerdict | None = None


@dataclass
class ToolApprovalBridge:
    """Registry of pending tool approvals and session-scoped acknowledgements."""

    hub: DashboardHub | None = None
    timeout_s: float = _DEFAULT_TIMEOUT_S
    _pending: dict[str, PendingToolApproval] = field(default_factory=dict)
    _session_acks: dict[str, set[str]] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def preapproved_tools(
        self,
        session_id: str,
        *,
        workspace_tools: dict[str, Any] | None = None,
    ) -> frozenset[str]:
        """Return session + config pre-approved tool names for one turn.

        Args:
            session_id (str): Active gateway session id.
            workspace_tools (dict[str, Any] | None): ``sevn.json`` ``tools`` subtree.

        Returns:
            frozenset[str]: Names cleared for ``requires_human`` this turn.

        Examples:
            >>> bridge = ToolApprovalBridge()
            >>> bridge.record_session_ack("s1", "delete")
            >>> "delete" in bridge.preapproved_tools("s1", workspace_tools={"human_preapproved": ["write"]})
            True
        """

        session = set(self._session_acks.get(session_id, set()))
        always_raw = (workspace_tools or {}).get("human_preapproved") or []
        always = {str(x).strip() for x in always_raw if str(x).strip()}
        return frozenset(session | always)

    def list_pending(self) -> list[dict[str, Any]]:
        """Return serializable pending approval rows for the dashboard API.

        Returns:
            list[dict[str, Any]]: Pending decisions newest-first by registration order.

        Examples:
            >>> bridge = ToolApprovalBridge()
            >>> bridge.list_pending()
            []
        """

        return [
            {
                "decision_id": row.decision_id,
                "tool_name": row.tool_name,
                "args_summary": row.args_summary,
                "session_id": row.session_id,
                "turn_id": row.turn_id,
            }
            for row in self._pending.values()
        ]

    def record_session_ack(self, session_id: str, tool_name: str) -> None:
        """Persist a session-scoped human acknowledgement in memory.

        Args:
            session_id (str): Gateway session id.
            tool_name (str): Tool name approved for the session lifetime.

        Returns:
            None: Side-effect only.

        Examples:
            >>> bridge = ToolApprovalBridge()
            >>> bridge.record_session_ack("s1", "delete")
            >>> "delete" in bridge.preapproved_tools("s1")
            True
        """

        bucket = self._session_acks.setdefault(session_id, set())
        bucket.add(tool_name)

    async def submit_verdict(self, decision_id: str, verdict: ApprovalVerdict) -> bool:
        """Apply an operator verdict to one pending decision.

        Args:
            decision_id (str): Pending decision uuid.
            verdict (ApprovalVerdict): Operator choice.

        Returns:
            bool: ``True`` when the decision existed and was updated.

        Examples:
            >>> import asyncio
            >>> bridge = ToolApprovalBridge()
            >>> pending = PendingToolApproval(
            ...     decision_id="d1",
            ...     session_id="s",
            ...     turn_id="t",
            ...     tool_name="delete",
            ...     args_summary="{}",
            ... )
            >>> bridge._pending["d1"] = pending
            >>> asyncio.run(bridge.submit_verdict("d1", "once"))
            True
        """

        async with self._lock:
            row = self._pending.get(decision_id)
            if row is None or row.verdict is not None:
                return False
            row.verdict = verdict
            row.event.set()
            return True

    async def await_operator_verdict(
        self,
        *,
        session_id: str,
        turn_id: str,
        tool_name: str,
        args_summary: str,
        trace: TraceSink | None = None,
    ) -> ApprovalVerdict:
        """Publish a pending approval and block until verdict or timeout.

        Args:
            session_id (str): Gateway session id.
            turn_id (str): Active turn / correlation id.
            tool_name (str): Blocked tool registry name.
            args_summary (str): Redacted argument summary for the UI card.
            trace (TraceSink | None): Optional trace sink for audit rows.

        Returns:
            ApprovalVerdict: Operator verdict, or ``deny`` on timeout.

        Examples:
            >>> import asyncio
            >>> bridge = ToolApprovalBridge(timeout_s=0.01)
            >>> asyncio.run(
            ...     bridge.await_operator_verdict(
            ...         session_id="s",
            ...         turn_id="t",
            ...         tool_name="delete",
            ...         args_summary='{"path":"x"}',
            ...     )
            ... )
            'deny'
        """

        decision_id = str(uuid.uuid4())
        row = PendingToolApproval(
            decision_id=decision_id,
            session_id=session_id,
            turn_id=turn_id,
            tool_name=tool_name,
            args_summary=args_summary,
        )
        async with self._lock:
            self._pending[decision_id] = row

        payload = {
            "type": "mission.approval.pending",
            "decision_id": decision_id,
            "tool_name": tool_name,
            "args_summary": args_summary,
            "session_id": session_id,
            "turn_id": turn_id,
        }
        if self.hub is not None:
            await self.hub.publish("mission.approval.pending", payload)
        if trace is not None:
            now = time.time_ns()
            await trace.emit(
                TraceEvent(
                    kind="mission.approval.pending",
                    span_id=str(uuid.uuid4()),
                    parent_span_id=None,
                    session_id=session_id,
                    turn_id=turn_id,
                    tier="B",
                    ts_start_ns=now,
                    ts_end_ns=now,
                    status="pending",
                    attrs={
                        "decision_id": decision_id,
                        "tool_name": tool_name,
                        "args_summary": args_summary,
                    },
                ),
            )

        try:
            await asyncio.wait_for(row.event.wait(), timeout=self.timeout_s)
        except TimeoutError:
            async with self._lock:
                row.verdict = "deny"
            verdict: ApprovalVerdict = "deny"
        else:
            verdict = row.verdict or "deny"

        if trace is not None:
            now = time.time_ns()
            await trace.emit(
                TraceEvent(
                    kind="mission.approval.resolved",
                    span_id=str(uuid.uuid4()),
                    parent_span_id=None,
                    session_id=session_id,
                    turn_id=turn_id,
                    tier="B",
                    ts_start_ns=now,
                    ts_end_ns=now,
                    status="ok" if verdict != "deny" else "denied",
                    attrs={
                        "decision_id": decision_id,
                        "tool_name": tool_name,
                        "verdict": verdict,
                    },
                ),
            )

        async with self._lock:
            self._pending.pop(decision_id, None)

        if self.hub is not None:
            await self.hub.publish(
                "mission.approval.resolved",
                {
                    "type": "mission.approval.resolved",
                    "decision_id": decision_id,
                    "tool_name": tool_name,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "verdict": verdict,
                },
            )

        return verdict


__all__ = [
    "ApprovalVerdict",
    "PendingToolApproval",
    "ToolApprovalBridge",
    "ack_tool_on_deps",
    "get_tool_approval_bridge",
    "install_tool_approval_bridge",
    "summarize_tool_args",
]
