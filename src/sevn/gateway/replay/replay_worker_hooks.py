"""Gateway hook registration for dashboard turn replay (Batch D lane #5).

Module: sevn.gateway.replay.replay_worker_hooks
Depends: sevn.gateway.boot_registry, sevn.gateway.hooks.post_turn_hooks,
    sevn.gateway.replay.replay_job_events, sevn.gateway.replay.replay_worker

Exports:
    register_replay_worker_hooks — register boot + post-turn hooks.
"""

from __future__ import annotations

from loguru import logger

from sevn.gateway.boot_registry import BootContext, register_boot_hook
from sevn.gateway.hooks.post_turn_hooks import PostTurnContext, register_post_turn_hook
from sevn.gateway.replay.replay_job_events import ReplayJobEventFanout
from sevn.gateway.replay.replay_worker import TurnReplayWorker


async def _start_replay_worker(ctx: BootContext) -> None:
    """Start the dashboard replay worker and attach fan-out to app state.

    Args:
        ctx (BootContext): Lifespan startup context.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_start_replay_worker)
        True
    """
    hub = getattr(ctx.app.state, "dashboard_hub", None)
    fanout = ReplayJobEventFanout(hub=hub)
    ctx.app.state.replay_job_event_fanout = fanout
    worker = TurnReplayWorker(
        sqlite_conn=ctx.conn,
        gateway_router=ctx.gateway_router,
        job_event_fanout=fanout.publish,
    )
    ctx.gateway_router._replay_job_event_fanout = fanout
    await worker.start()
    ctx.app.state.replay_worker = worker


async def _post_turn_replay_terminal(ctx: PostTurnContext) -> None:
    """Publish terminal replay job status after the replay turn completes.

    Args:
        ctx (PostTurnContext): Turn-end state from ``run_post_turn_hooks``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_post_turn_replay_terminal)
        True
    """
    terminal = ctx.router._sessions.pop_replay_terminal(ctx.session_id)
    if terminal is None:
        return
    replay_job_id, origin_turn_id = terminal
    fanout = getattr(ctx.router, "_replay_job_event_fanout", None)
    if fanout is None:
        return
    status = "completed" if ctx.terminal_status == "ok" else "failed"
    try:
        await fanout.publish(
            {
                "replay_job_id": replay_job_id,
                "session_id": ctx.session_id,
                "turn_id": origin_turn_id,
                "event": "terminal",
                "status": status,
            },
        )
    except Exception:
        logger.exception(
            "replay_terminal_event_failed replay_job_id={} session_id={}",
            replay_job_id,
            ctx.session_id,
        )


def register_replay_worker_hooks() -> None:
    """Register replay worker boot and post-turn hooks via CW-1 / CW-2 registries.

    Examples:
        >>> "register_replay_worker_hooks" in __all__
        True
    """
    register_boot_hook("replay_worker", _start_replay_worker, priority=70)
    register_post_turn_hook("replay_terminal", _post_turn_replay_terminal, priority=40)


register_replay_worker_hooks()

__all__ = ["register_replay_worker_hooks"]
