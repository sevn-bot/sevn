"""Gateway hook registration for per-turn diagnostic bundles (W1).

Module: sevn.gateway.turn.turn_bundle_hooks
Depends: asyncio, sevn.gateway.hooks.post_turn_hooks, sevn.gateway.turn.turn_bundle

Exports:
    register_turn_bundle_hooks — register config-gated post-turn bundle writer.
"""

from __future__ import annotations

import asyncio

from loguru import logger

from sevn.gateway.hooks.post_turn_hooks import PostTurnContext, register_post_turn_hook
from sevn.storage.paths import traces_sqlite_path
from sevn.workspace.layout import WorkspaceLayout


async def _post_turn_turn_bundle(ctx: PostTurnContext) -> None:
    """Write one JSONL turn bundle and upsert ``index.json`` when enabled (D8).

    Args:
        ctx (PostTurnContext): Turn-end state from ``run_post_turn_hooks``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_post_turn_turn_bundle)
        True
    """
    router = ctx.router
    content_root = getattr(router, "_content_root", None)
    workspace = getattr(router, "_workspace", None)
    if content_root is None or workspace is None:
        return
    from sevn.gateway.turn.turn_bundle import effective_turn_bundles_enabled, write_turn_bundle

    if not effective_turn_bundles_enabled(workspace):
        return

    layout = WorkspaceLayout(
        sevn_json_path=content_root / "sevn.json",
        content_root=content_root,
    )

    def _write_bundle() -> None:
        from sevn.ui.dashboard.query.traces import ensure_trace_connection

        trace_conn = None
        try:
            traces_path = traces_sqlite_path(layout.dot_sevn)
            if traces_path.is_file():
                trace_conn = ensure_trace_connection(traces_path)
            write_turn_bundle(
                ctx.conn,
                trace_conn,
                content_root=layout.content_root,
                session_id=ctx.session_id,
                turn_id=ctx.correlation_id,
                terminal_status=ctx.terminal_status,
            )
        except Exception:
            logger.exception(
                "turn_bundle_write_failed session_id={} turn_id={}",
                ctx.session_id,
                ctx.correlation_id,
            )
        finally:
            if trace_conn is not None:
                trace_conn.close()

    await asyncio.to_thread(_write_bundle)


def register_turn_bundle_hooks() -> None:
    """Register the turn-bundle post-turn hook via CW-1 registry.

    Examples:
        >>> "register_turn_bundle_hooks" in __all__
        True
    """
    register_post_turn_hook("turn_bundle", _post_turn_turn_bundle, priority=50)


register_turn_bundle_hooks()

__all__ = ["register_turn_bundle_hooks"]
