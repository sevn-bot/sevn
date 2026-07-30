"""Level-2 sub-agent completion announce-back (D9, `specs/36-sub-agents.md`).

Fire-and-forget is the default spawn mode (W3.3): the ``spawn_subagent`` tool
returns a run id immediately, and this module's hook delivers the result once
the level-2 run finishes — steer-injected into the parent session when a turn
is still in flight there, otherwise sent outbound with a short sub-agent tag.

Module: sevn.gateway.subagents.subagents_announce
Depends: sevn.agent.subagents, sevn.gateway.channel_router, sevn.gateway.session_manager

Exports:
    build_announce_back_hook — construct an ``AnnounceBackHook`` bound to one router/conn.
    format_transcript_reference — human-readable transcript path for one run (#77).
    load_subagent_result_for_announce — read persisted completion text from SQLite.
    deliver_subagent_result_through_ledger — outbound delivery via W18 ledger.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from sevn.agent.subagents.storage import (
    load_subagent_result_body,
    mark_subagent_result_delivered,
)
from sevn.agent.subagents.transcript import (
    load_subagent_transcript_path,
    transcript_relpath_for_run,
)
from sevn.gateway.channel_router import ChannelRouter, OutgoingMessage
from sevn.gateway.session_manager import load_session_row

if TYPE_CHECKING:
    from sevn.agent.subagents.models import SubAgentRun
    from sevn.agent.subagents.supervisor import AnnounceBackHook
    from sevn.gateway.session_manager import SessionRow

__all__ = [
    "build_announce_back_hook",
    "deliver_subagent_result_through_ledger",
    "format_transcript_reference",
    "load_subagent_result_for_announce",
]


def format_transcript_reference(
    conn: sqlite3.Connection,
    run: SubAgentRun,
    *,
    content_root: Path,
) -> str:
    """Return a human-readable transcript location for one sub-agent run (#77).

    Args:
        conn (sqlite3.Connection): Open, migrated ``sevn.db`` connection.
        run (SubAgentRun): Target run row.
        content_root (Path): Workspace content root for fallback path resolution.

    Returns:
        str: Operator-facing transcript reference including the run id.

    Examples:
        >>> import sqlite3
        >>> from pathlib import Path
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus
        >>> from sevn.gateway.subagents.subagents_announce import format_transcript_reference
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> run = SubAgentRun(
        ...     id="run-t1", level=2, role="tier_b", specialist=None, parent_id="p1",
        ...     session_id="s", channel="c", task_summary="t",
        ...     status=SubAgentStatus.DONE, started_at=1, finished_at=2, trace_id=None,
        ... )
        >>> ref = format_transcript_reference(conn, run, content_root=Path("/tmp/ws"))
        >>> "transcript" in ref.lower()
        True
    """
    rel = load_subagent_transcript_path(conn, run.id) or transcript_relpath_for_run(run)
    return f"transcript for run {run.id}: {rel}"


def _render_result_text(
    run: SubAgentRun,
    result: object | None,
    error: BaseException | None,
    *,
    conn: sqlite3.Connection | None = None,
    content_root: Path | None = None,
) -> str:
    """Render the announce-back text for one finished level-2 run.

    Args:
        run (SubAgentRun): The finished run (``done``/``failed``/``killed``).
        result (object | None): Body return value on success.
        error (BaseException | None): Body exception, or timeout/cancel marker.
        conn (sqlite3.Connection | None): Gateway SQLite handle for transcript lookup.
        content_root (Path | None): Workspace content root for transcript path fallback.

    Returns:
        str: One-line (or short) message suitable for steer-inject or outbound send.

    Examples:
        >>> from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus
        >>> run = SubAgentRun(
        ...     id="a1f3", level=2, role="tier_b", specialist=None, parent_id="p1",
        ...     session_id="s", channel="telegram", task_summary="t",
        ...     status=SubAgentStatus.DONE, started_at=1, finished_at=2, trace_id=None,
        ... )
        >>> _render_result_text(run, "done thing", None)
        '[sub-agent a1f3 · tier_b] done thing'
    """
    label = run.specialist or f"{run.role}"
    tag = f"[sub-agent {run.id} · {label}]"
    if error is not None:
        return f"{tag} failed: {error}"
    if isinstance(result, str) and result.strip():
        body = f"{tag} {result.strip()}"
    elif result is None:
        body = f"{tag} done."
    else:
        body = f"{tag} {result}"
    if conn is not None and content_root is not None:
        body = f"{body}\n{format_transcript_reference(conn, run, content_root=content_root)}"
    return body


def load_subagent_result_for_announce(conn: sqlite3.Connection, run_id: str) -> str | None:
    """Load persisted completion text for announce-back after restart (#76).

    Args:
        conn (sqlite3.Connection): Open, migrated ``sevn.db`` connection.
        run_id (str): Target sub-agent run id.

    Returns:
        str | None: Stored ``result_body`` when present.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus
        >>> from sevn.agent.subagents.storage import persist_subagent_run
        >>> from sevn.gateway.subagents.subagents_announce import load_subagent_result_for_announce
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> run = SubAgentRun(
        ...     id="a1f3", level=2, role="tier_b", specialist=None, parent_id="p1",
        ...     session_id="s1", channel="telegram", task_summary="t",
        ...     status=SubAgentStatus.DONE, started_at=1, finished_at=2, trace_id=None,
        ... )
        >>> persist_subagent_run(conn, run, result_body="stored")
        >>> load_subagent_result_for_announce(conn, "a1f3")
        'stored'
    """
    return load_subagent_result_body(conn, run_id)


async def deliver_subagent_result_through_ledger(
    *,
    router: ChannelRouter,
    conn: sqlite3.Connection,
    run: SubAgentRun,
    session: SessionRow,
    result_body: str,
) -> None:
    """Send one persisted sub-agent result through ``route_outgoing`` (#76 / W18).

    Args:
        router (ChannelRouter): Gateway router (creates delivery obligations).
        conn (sqlite3.Connection): Gateway SQLite handle.
        run (SubAgentRun): Completed level-2 run being announced.
        session (SessionRow): Owning gateway session row.
        result_body (str): Raw completion text (tag applied here).

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(deliver_subagent_result_through_ledger)
        True
    """
    if session.session_id != run.session_id:
        logger.warning(
            "subagent_delivery_session_mismatch run_id={} run_session={} row_session={}",
            run.id,
            run.session_id,
            session.session_id,
        )
        return
    text = _render_result_text(
        run,
        result_body,
        None,
        conn=conn,
        content_root=getattr(router, "_content_root", None),
    )
    await router.route_outgoing(
        OutgoingMessage(
            channel=session.channel,
            user_id=session.user_id,
            text=text,
            session_id=run.session_id,
            metadata={"subagent_id": run.id},
        ),
    )
    from sevn.storage.delivery import is_delivery_confirmed

    last_ob = getattr(router, "last_delivery_obligation", None)
    message_id = int(last_ob["message_id"]) if isinstance(last_ob, dict) else None
    if message_id is not None and is_delivery_confirmed(conn, message_id):
        mark_subagent_result_delivered(conn, run.id)


def build_announce_back_hook(
    router: ChannelRouter,
    conn: sqlite3.Connection,
) -> AnnounceBackHook:
    """Build the supervisor's ``announce_back`` completion callback (D9).

    Args:
        router (ChannelRouter): Gateway router for steer-inject / outbound send.
        conn (sqlite3.Connection): Gateway SQLite handle for session lookups.

    Returns:
        AnnounceBackHook: ``(run, result, error) -> None`` callback for
            :class:`~sevn.agent.subagents.supervisor.SubAgentSupervisor`.

    Examples:
        >>> import inspect
        >>> import sqlite3
        >>> from sevn.gateway.channel_router import ChannelRouter
        >>> hook = build_announce_back_hook(ChannelRouter.__new__(ChannelRouter), sqlite3.connect(":memory:"))
        >>> inspect.iscoroutinefunction(hook)
        True
    """

    async def _announce(
        run: SubAgentRun,
        result: object | None,
        error: BaseException | None,
    ) -> None:
        # D9 announce-back only applies to level-2 spawns; level-1 lifecycle is
        # tracked (W3.1) but not announced — the classic turn already sends its
        # own reply through the normal outbound path.
        if run.level != 2:
            return
        effective_result = result
        if effective_result is None and error is None:
            effective_result = load_subagent_result_for_announce(conn, run.id)
        text = _render_result_text(
            run,
            effective_result,
            error,
            conn=conn,
            content_root=getattr(router, "_content_root", None),
        )
        store = getattr(router, "_steer_store", None)
        try:
            _depth, running = router._sessions.dispatch_queue_snapshot(run.session_id)
        except Exception:
            running = False
        if running and store is not None:
            try:
                store.steer_inject_for(run.session_id).inject_pending(text)
                return
            except Exception:
                logger.exception(
                    "subagent_announce_back_steer_inject_failed run_id={} session_id={}",
                    run.id,
                    run.session_id,
                )
        sess = load_session_row(conn, run.session_id)
        if sess is None:
            logger.warning(
                "subagent_announce_back_session_missing run_id={} session_id={}",
                run.id,
                run.session_id,
            )
            return
        try:
            await router.route_outgoing(
                OutgoingMessage(
                    channel=sess.channel,
                    user_id=sess.user_id,
                    text=text,
                    session_id=run.session_id,
                    metadata={"subagent_id": run.id},
                ),
            )
            from sevn.storage.delivery import is_delivery_confirmed

            last_ob = getattr(router, "last_delivery_obligation", None)
            message_id = int(last_ob["message_id"]) if isinstance(last_ob, dict) else None
            if message_id is not None and is_delivery_confirmed(conn, message_id):
                mark_subagent_result_delivered(conn, run.id)
        except Exception:
            logger.exception("subagent_announce_back_send_failed run_id={}", run.id)

    return _announce
