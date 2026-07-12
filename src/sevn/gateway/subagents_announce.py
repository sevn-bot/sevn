"""Level-2 sub-agent completion announce-back (D9, `specs/36-sub-agents.md`).

Fire-and-forget is the default spawn mode (W3.3): the ``spawn_subagent`` tool
returns a run id immediately, and this module's hook delivers the result once
the level-2 run finishes — steer-injected into the parent session when a turn
is still in flight there, otherwise sent outbound with a short sub-agent tag.

Module: sevn.gateway.subagents_announce
Depends: sevn.agent.subagents, sevn.gateway.channel_router, sevn.gateway.session_manager

Exports:
    build_announce_back_hook — construct an ``AnnounceBackHook`` bound to one router/conn.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from loguru import logger

from sevn.gateway.channel_router import ChannelRouter, OutgoingMessage
from sevn.gateway.session_manager import load_session_row

if TYPE_CHECKING:
    from sevn.agent.subagents.models import SubAgentRun
    from sevn.agent.subagents.supervisor import AnnounceBackHook

__all__ = ["build_announce_back_hook"]


def _render_result_text(
    run: SubAgentRun,
    result: object | None,
    error: BaseException | None,
) -> str:
    """Render the announce-back text for one finished level-2 run.

    Args:
        run (SubAgentRun): The finished run (``done``/``failed``/``killed``).
        result (object | None): Body return value on success.
        error (BaseException | None): Body exception, or timeout/cancel marker.

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
        return f"{tag} {result.strip()}"
    if result is None:
        return f"{tag} done."
    return f"{tag} {result}"


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
        text = _render_result_text(run, result, error)
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
                    metadata={},
                ),
            )
        except Exception:
            logger.exception("subagent_announce_back_send_failed run_id={}", run.id)

    return _announce
