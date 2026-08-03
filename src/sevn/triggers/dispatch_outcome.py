"""Cron / trigger dispatch outcome assessment (#135, D13).

Module: sevn.triggers.dispatch_outcome
Depends: sqlite3, sevn.triggers.request

Exports:
    DispatchOutcome — agent + delivery success bookkeeping.
    assess_agent_pass_outcome — classify a completed agent-pass dispatch.
    cron_failure_notify_text — operator-facing failure line for cron jobs.
    notify_cron_dispatch_failure — deliver failure via operator notify sink.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sevn.triggers.request import DispatchRequest, ResultChannelKind

CronLastStatus = Literal["dispatched", "completed", "delivery_failed", "agent_failed"]

_NO_OUTPUT_MARKERS = frozenset(
    {
        "(no output)",
        "(no answer)",
        "(empty response)",
    },
)


@dataclass(frozen=True)
class DispatchOutcome:
    """Downstream result of one trigger dispatch (agent-pass or notify-only)."""

    agent_ok: bool
    delivery_ok: bool
    error: str | None = None

    def cron_last_status(self) -> CronLastStatus:
        """Map to ``trigger_cron_jobs.last_status`` (D13).

        Returns:
            CronLastStatus: ``completed``, ``agent_failed``, or ``delivery_failed``.

        Examples:
            >>> DispatchOutcome(agent_ok=True, delivery_ok=True).cron_last_status()
            'completed'
            >>> DispatchOutcome(agent_ok=False, delivery_ok=False, error="x").cron_last_status()
            'agent_failed'
        """
        if not self.agent_ok:
            return "agent_failed"
        if not self.delivery_ok:
            return "delivery_failed"
        return "completed"

    def cron_audit_status(self) -> str:
        """Map to ``cron_runs.status`` terminal label (migration 28 CHECK).

        ``trigger_cron_jobs.last_status`` uses D13 labels via :meth:`cron_last_status`;
        audit rows keep the existing ``ok`` / ``failed`` vocabulary.

        Returns:
            str: ``ok`` when fully successful, else ``failed``.

        Examples:
            >>> DispatchOutcome(agent_ok=True, delivery_ok=True).cron_audit_status()
            'ok'
            >>> DispatchOutcome(agent_ok=False, delivery_ok=False).cron_audit_status()
            'failed'
        """
        return "ok" if self.cron_last_status() == "completed" else "failed"


def _is_deliverable(text: str | None) -> bool:
    """Return whether assistant text is non-empty and not a placeholder.

    Args:
        text (str | None): Assistant message body.

    Returns:
        bool: ``True`` when text is suitable for delivery success checks.

    Examples:
        >>> _is_deliverable("hello")
        True
    """
    body = str(text or "").strip()
    if not body:
        return False
    lowered = body.lower()
    return lowered not in _NO_OUTPUT_MARKERS and not lowered.startswith("(no output)")


def _assistant_rows_for_dispatch(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    correlation_id: str,
) -> list[dict[str, Any]]:
    """Load assistant message rows produced for one trigger dispatch.

    ``route_outgoing`` mints a fresh per-send turn id, so assistant rows are
    not keyed by ``DispatchRequest.correlation_id``. Anchor on the trigger
    user row (which uses ``correlation_id``) and return subsequent assistant
    rows in the same session.

    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        session_id (str): Trigger session id.
        correlation_id (str): Dispatch correlation / trigger user ``turn_id``.

    Returns:
        list[dict[str, Any]]: Rows with ``id``, ``content``, and ``status``.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> _assistant_rows_for_dispatch(c, session_id="s", correlation_id="t")
        []
    """
    cur = conn.execute(
        """
        SELECT a.id, a.content, a.status
        FROM gateway_messages a
        WHERE a.session_id = ?
          AND a.role = 'assistant'
          AND a.kind = 'message'
          AND a.id > COALESCE(
              (
                SELECT MAX(u.id)
                FROM gateway_messages u
                WHERE u.session_id = ?
                  AND u.turn_id = ?
                  AND u.role = 'user'
                  AND u.kind = 'message'
              ),
              0
          )
        ORDER BY a.id ASC
        """,
        (session_id, session_id, correlation_id),
    )
    return [
        {"id": int(r[0]), "content": str(r[1] or ""), "status": str(r[2] or "")}
        for r in cur.fetchall()
    ]


def _delivery_failed_for_messages(conn: sqlite3.Connection, message_ids: list[int]) -> bool:
    """Return whether any listed gateway messages have failed delivery obligations.

    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        message_ids (list[int]): ``gateway_messages.id`` values to inspect.

    Returns:
        bool: ``True`` when at least one obligation is ``failed``.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> _delivery_failed_for_messages(c, [])
        False
    """
    if not message_ids:
        return False
    placeholders = ",".join("?" for _ in message_ids)
    row = conn.execute(
        f"""
        SELECT 1 FROM delivery_obligations
        WHERE message_id IN ({placeholders})
          AND status = 'failed'
        LIMIT 1
        """,  # nosec B608 — placeholders are bound ? only
        tuple(message_ids),
    ).fetchone()
    return row is not None


def _requires_channel_delivery(kind: ResultChannelKind) -> bool:
    """Return whether the result channel expects an outbound platform send.

    Args:
        kind (ResultChannelKind): Result channel kind from the dispatch envelope.

    Returns:
        bool: ``False`` for ``LOG`` sinks; ``True`` for platform delivery channels.

    Examples:
        >>> _requires_channel_delivery("LOG")
        False
    """
    return kind in ("TELEGRAM_TOPIC", "WEBUI_NOTIFICATION", "BACK_TO_SOURCE")


def assess_agent_pass_outcome(
    conn: sqlite3.Connection | None,
    *,
    req: DispatchRequest,
    session_id: str | None,
    agent_exception: BaseException | None,
    assistant_texts: list[str] | None = None,
) -> DispatchOutcome:
    """Classify agent-pass dispatch result for cron status propagation.

    Args:
        conn (sqlite3.Connection | None): Gateway SQLite handle when available.
        req (DispatchRequest): Original dispatch envelope.
        session_id (str | None): Trigger session id from ``dispatch_run``.
        agent_exception (BaseException | None): Raised exception from ``run_turn``, if any.
        assistant_texts (list[str] | None, optional): Pre-collected assistant bodies.

    Returns:
        DispatchOutcome: Agent and delivery success flags plus optional error text.

    Examples:
        >>> from sevn.triggers.request import DispatchRequest, ResultChannel
        >>> assess_agent_pass_outcome(
        ...     None,
        ...     req=DispatchRequest(
        ...         prompt="x",
        ...         result_channel=ResultChannel(kind="LOG"),
        ...         correlation_id="c1",
        ...     ),
        ...     session_id=None,
        ...     agent_exception=RuntimeError("boom"),
        ... ).cron_last_status()
        'agent_failed'
    """
    if agent_exception is not None:
        return DispatchOutcome(
            agent_ok=False,
            delivery_ok=False,
            error=str(agent_exception)[:500],
        )
    if session_id is None:
        return DispatchOutcome(
            agent_ok=False,
            delivery_ok=False,
            error="run_turn_not_wired",
        )

    rows: list[dict[str, Any]] = []
    if conn is not None:
        rows = _assistant_rows_for_dispatch(
            conn,
            session_id=session_id,
            correlation_id=req.correlation_id,
        )

    texts = list(assistant_texts or [])
    if not texts and rows:
        texts = [str(r.get("content") or "") for r in rows]

    deliverable = [t for t in texts if _is_deliverable(t)]
    if not deliverable:
        return DispatchOutcome(
            agent_ok=False,
            delivery_ok=False,
            error="no_assistant_output",
        )

    rc = req.result_channel
    if not _requires_channel_delivery(rc.kind):
        return DispatchOutcome(agent_ok=True, delivery_ok=True)

    if not rows:
        return DispatchOutcome(
            agent_ok=True,
            delivery_ok=False,
            error="delivery_status_unknown",
        )

    if any(str(r.get("status") or "") == "failed" for r in rows):
        return DispatchOutcome(
            agent_ok=True,
            delivery_ok=False,
            error="outbound_delivery_failed",
        )

    message_ids = [int(r["id"]) for r in rows if isinstance(r.get("id"), int)]
    if conn is not None and _delivery_failed_for_messages(conn, message_ids):
        return DispatchOutcome(
            agent_ok=True,
            delivery_ok=False,
            error="delivery_obligation_failed",
        )

    if rc.kind == "TELEGRAM_TOPIC" and not any(str(r.get("status") or "") == "sent" for r in rows):
        return DispatchOutcome(
            agent_ok=True,
            delivery_ok=False,
            error="no_telegram_delivery",
        )

    return DispatchOutcome(agent_ok=True, delivery_ok=True)


def cron_failure_notify_text(
    *,
    job_id: str,
    correlation_id: str,
    status: CronLastStatus,
    error: str | None,
) -> str:
    """Build operator notify body for a failed cron run.

    Args:
        job_id (str): ``trigger_cron_jobs.job_id``.
        correlation_id (str): Run correlation id.
        status (CronLastStatus): Terminal ``last_status`` label.
        error (str | None): Concise failure reason when present.

    Returns:
        str: Single-line operator message.

    Examples:
        >>> "daily" in cron_failure_notify_text(
        ...     job_id="daily", correlation_id="c1", status="agent_failed", error="x",
        ... )
        True
    """
    detail = f" — {error}" if error else ""
    return f"Cron `{job_id}` failed ({status}){detail} [run={correlation_id}]"


def notify_cron_dispatch_failure(
    *,
    job_id: str,
    correlation_id: str,
    outcome: DispatchOutcome,
    content_root: Path | None,
) -> None:
    """Notify the operator when a cron dispatch ends in failure (D13).

    Args:
        job_id (str): ``trigger_cron_jobs.job_id``.
        correlation_id (str): Run correlation id.
        outcome (DispatchOutcome): Assessed dispatch result.
        content_root (Path | None): Workspace root for LOG fallback.

    Returns:
        None: Side-effect only.

    Examples:
        >>> notify_cron_dispatch_failure(
        ...     job_id="j",
        ...     correlation_id="c",
        ...     outcome=DispatchOutcome(agent_ok=True, delivery_ok=True),
        ...     content_root=None,
        ... )
    """
    status = outcome.cron_last_status()
    if status == "completed":
        return
    from sevn.triggers.operator_notify import deliver_operator_notify

    deliver_operator_notify(
        text=cron_failure_notify_text(
            job_id=job_id,
            correlation_id=correlation_id,
            status=status,
            error=outcome.error,
        ),
        content_root=content_root,
    )


__all__ = [
    "CronLastStatus",
    "DispatchOutcome",
    "assess_agent_pass_outcome",
    "cron_failure_notify_text",
    "notify_cron_dispatch_failure",
]
