"""Gateway → LCM ingest glue (`specs/17-gateway.md` §2.6 Wave 8).

Module: sevn.gateway.lcm.lcm_ingest
Depends: sevn.lcm.engine, sevn.config.workspace_config, sevn.workspace.layout

Exports:
    ingest_gateway_message_row — mirror ``gateway_messages`` rows into ``lcm_messages``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from sevn.config.workspace_config import WorkspaceConfig
from sevn.lcm.engine import InboundLcmMessage, LcmEngine, SessionView

if TYPE_CHECKING:
    from sevn.agent.tracing.sink import TraceSink


async def ingest_gateway_message_row(
    *,
    conn: sqlite3.Connection,
    workspace: WorkspaceConfig,
    content_root: Path,
    trace: TraceSink | None,
    session_id: str,
    channel: str,
    role: str,
    content: str,
    kind: str = "message",
    visible_to_llm: bool = True,
    status: str = "sent",
    turn_id: str | None = None,
) -> int | None:
    """Ingest one gateway history row into LCM when enabled.

    No-op when ``lcm.enabled`` is false or the row is not LCM-eligible
    (non-``message`` kind or not visible to the LLM).

    Args:
        conn (sqlite3.Connection): Workspace SQLite handle (``sevn.db``).
        workspace (WorkspaceConfig): Parsed workspace configuration.
        content_root (Path): Resolved workspace content root.
        trace (TraceSink | None): Optional trace sink for ``lcm.ingest`` spans.
        session_id (str): Gateway session id (LCM ``session_key``).
        channel (str): Delivery channel key (e.g. ``telegram``).
        role (str): ``user`` or ``assistant``.
        content (str): Message body already stored on ``gateway_messages``.
        kind (str): Gateway row kind; only ``message`` is ingested.
        visible_to_llm (bool): Mirror ``gateway_messages.visible_to_llm``.
        status (str): LCM delivery status (``sent`` / ``pending`` / ``failed``).
        turn_id (str | None): Gateway turn correlation id for ``lcm.ingest`` traces.

    Returns:
        int | None: ``lcm_messages.id`` when ingested, else ``None``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(ingest_gateway_message_row)
        True
    """
    if kind != "message" or not visible_to_llm:
        return None
    lcm_cfg = workspace.lcm
    if lcm_cfg is not None and not lcm_cfg.enabled:
        return None
    body = (content or "").strip()
    if not body:
        return None
    engine = LcmEngine(
        conn,
        workspace_root=content_root,
        workspace_cfg=workspace,
        trace_sink=trace,
    )
    session = SessionView(
        session_key=session_id,
        conversation_id=0,
        channel=channel,
    )
    msg = InboundLcmMessage(
        role=role,
        content=body,
        kind="message",
        visible_to_llm=True,
        status=status,  # type: ignore[arg-type]
    )
    try:
        return await engine.ingest(session, msg, turn_id=turn_id or "lcm")
    except RuntimeError as exc:
        if "LCM disabled" in str(exc):
            return None
        raise
    except Exception:
        logger.exception(
            "lcm_ingest failed session_id={} role={} channel={}",
            session_id,
            role,
            channel,
        )
        return None


__all__ = ["ingest_gateway_message_row"]
