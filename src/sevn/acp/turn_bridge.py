"""Bridge ACP ``session/prompt`` into the sevn turn loop (#72, W31.2).

Module: sevn.acp.turn_bridge
Depends: asyncio, sevn.triggers.dispatcher

Exports:
    run_acp_prompt_turn — synchronous entry used by :mod:`sevn.acp.runtime`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, NamedTuple

from sevn.config.workspace_config import WorkspaceConfig, parse_workspace_config
from sevn.triggers.dispatcher import assistant_texts_for_session
from sevn.workspace.layout import WorkspaceLayout

_ACP_TURN_FAILED = "[sevn acp] turn completed without assistant output"


class _TurnContext(NamedTuple):
    """Resolved workspace layout + correlation id for one ACP prompt."""

    ws: WorkspaceConfig
    layout: WorkspaceLayout
    correlation_id: str


def _stub_turn_reply(prompt: str) -> str:
    """Return a deterministic stub reply for unit tests and offline stdio runs.

    Args:
        prompt (str): User prompt text.

    Returns:
        str: Stub assistant reply.

    Examples:
        >>> _stub_turn_reply("ping")
        'pong'
    """
    text = prompt.strip().lower()
    if text == "ping":
        return "pong"
    if not prompt.strip():
        return ""
    return f"[sevn acp stub] received: {prompt.strip()[:500]}"


def _workspace_bound(config: dict[str, Any]) -> bool:
    """Return whether ``config`` includes enough data to bind a workspace.

    Args:
        config (dict[str, Any]): Workspace snapshot from ``sevn acp``.

    Returns:
        bool: ``True`` when a content root is present.

    Examples:
        >>> _workspace_bound({"content_root": "/tmp/w"})
        True
    """
    return bool(config.get("content_root") or config.get("workspace_root"))


def _load_turn_context(session_id: str, config: dict[str, Any]) -> _TurnContext:
    """Resolve workspace layout and correlation id for one ACP session.

    Args:
        session_id (str): ACP session id.
        config (dict[str, Any]): Workspace snapshot from ``sevn acp``.

    Returns:
        _TurnContext: Parsed turn context.

    Examples:
        >>> isinstance(_load_turn_context, object)
        True
    """
    root = Path(str(config.get("content_root") or config.get("workspace_root") or ".")).resolve()
    sevn_json = Path(str(config.get("sevn_json") or root / "sevn.json")).resolve()
    ws_blob = config.get("workspace")
    if isinstance(ws_blob, dict):
        ws = parse_workspace_config(ws_blob)
    else:
        raw = json.loads(sevn_json.read_text(encoding="utf-8"))
        ws = parse_workspace_config(raw)
    layout = WorkspaceLayout.from_config(sevn_json, ws)
    return _TurnContext(ws=ws, layout=layout, correlation_id=f"acp-{session_id}")


async def _dispatch_prompt_turn(ctx: _TurnContext, session_id: str, prompt: str) -> str | None:
    """Run one agent turn via the shared trigger dispatch path.

    Args:
        ctx (_TurnContext): Parsed workspace + correlation id.
        session_id (str): ACP session id for trigger metadata.
        prompt (str): User prompt text.

    Returns:
        str | None: Joined assistant text, or ``None`` when dispatch produced no reply.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_dispatch_prompt_turn)
        True
    """
    from sevn.agent.tracing.sink import NullTraceSink
    from sevn.gateway.agent_turn import build_agent_run_turn
    from sevn.gateway.channel_router import ChannelRouter
    from sevn.gateway.commands.dispatcher import CommandDispatcher
    from sevn.gateway.media.media_store import MediaStore
    from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
    from sevn.gateway.session_manager import SessionManager
    from sevn.security.llm_guard_scanner import LLMGuardScanner
    from sevn.storage import open_sevn_sqlite
    from sevn.triggers.dispatcher import dispatch_run
    from sevn.triggers.request import DispatchRequest, ResultChannel

    conn = open_sevn_sqlite(ctx.layout.dot_sevn)
    try:
        sessions = SessionManager(conn)
        media = MediaStore(conn, ctx.layout.content_root)
        router = ChannelRouter(
            workspace=ctx.ws,
            content_root=ctx.layout.content_root,
            sessions=sessions,
            dispatcher=CommandDispatcher(),
            scanner=LLMGuardScanner(ctx.layout.content_root, ctx.ws),
            trace=NullTraceSink(),
            rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
            media=media,
        )
        run_turn = build_agent_run_turn(router, conn, ctx.ws, ctx.layout, NullTraceSink())
        handle = await dispatch_run(
            DispatchRequest(
                prompt=prompt,
                result_channel=ResultChannel(kind="LOG"),
                correlation_id=ctx.correlation_id,
                trigger_meta={"transport": "acp", "session_id": session_id},
            ),
            workspace=ctx.ws,
            content_root=ctx.layout.content_root,
            trace=NullTraceSink(),
            hooks=None,
            run_turn=run_turn,
            session_manager=router.session_manager,
        )
        if not handle.session_id:
            return None
        texts = assistant_texts_for_session(conn, handle.session_id)
        joined = " ".join(t.strip() for t in texts if t.strip()).strip()
        return joined or None
    finally:
        conn.close()


def run_acp_prompt_turn(session_id: str, prompt: str, workspace_config: dict[str, Any]) -> str:
    """Execute one ACP prompt through the sevn turn loop or a deterministic stub.

    Args:
        session_id (str): ACP session id (maps to gateway session when bound).
        prompt (str): User prompt text from ``session/prompt``.
        workspace_config (dict[str, Any]): Workspace snapshot from ``sevn acp``.

    Returns:
        str: Assistant text for ``session/update`` streaming.

    Examples:
        >>> run_acp_prompt_turn("s1", "ping", {})
        'pong'
    """
    if not _workspace_bound(workspace_config):
        return _stub_turn_reply(prompt)
    import asyncio

    ctx = _load_turn_context(session_id, workspace_config)
    from sevn.triggers.delivery import trigger_runs_dir

    trigger_runs_dir(ctx.layout.content_root).mkdir(parents=True, exist_ok=True)
    assistant = asyncio.run(_dispatch_prompt_turn(ctx, session_id, prompt))
    if assistant:
        return assistant
    return _ACP_TURN_FAILED


__all__ = ["run_acp_prompt_turn"]
