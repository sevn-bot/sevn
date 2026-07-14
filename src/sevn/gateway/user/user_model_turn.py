"""Post-turn user-model extraction orchestration (Batch D lane #6).

Module: sevn.gateway.user.user_model_turn
Depends: sevn.agent.providers.resolve, sevn.config.model_resolution, sevn.gateway.hooks.post_turn_hooks,
    sevn.gateway.turn.turn_metadata, sevn.memory.user_model

Exports:
    lookup_user_text_for_turn — recover replayable user text for a turn id.
    maybe_schedule_user_model_extraction_after_turn — CW-1 post-turn hook callback.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from typing import TYPE_CHECKING, Literal

from loguru import logger

from sevn.agent.providers.resolve import resolve_model
from sevn.agent.tracing.sink import TraceEvent, TraceSink
from sevn.config.model_resolution import (
    ModelSlot,
    _providers_dict,
    resolve_model_slot,
    resolve_transport_for_model_id,
    user_model_extraction_enabled,
)
from sevn.gateway.hooks.post_turn_hooks import PostTurnContext
from sevn.gateway.session_manager import load_session_row
from sevn.gateway.turn.turn_metadata import load_turn_metadata
from sevn.memory.user_model.extractor import UserModelExtractor
from sevn.memory.user_model.merger import UserModelMerger
from sevn.memory.user_model.models import InferredFact, UserProfile
from sevn.memory.user_model.queue import schedule_user_model_extraction
from sevn.memory.user_model.store import UserModelStore

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig

MergeAction = Literal["append", "bump", "supersede"]


def lookup_user_text_for_turn(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    turn_id: str,
) -> str | None:
    """Return the latest user message text for ``(session_id, turn_id)``.

    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        session_id (str): Owning session id.
        turn_id (str): Turn correlation id.

    Returns:
        str | None: Non-empty user text when found.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.gateway.user.user_model_turn import lookup_user_text_for_turn
        >>> db = sqlite3.connect(":memory:")
        >>> apply_migrations(db)
        >>> lookup_user_text_for_turn(db, session_id="s", turn_id="t") is None
        True
    """
    row = conn.execute(
        """
        SELECT content
        FROM gateway_messages
        WHERE session_id = ?
          AND turn_id = ?
          AND role = 'user'
          AND kind = 'message'
        ORDER BY id DESC
        LIMIT 1
        """,
        (session_id, turn_id),
    ).fetchone()
    if row is None:
        return None
    text = str(row[0] or "").strip()
    return text or None


def _owner_lane_allowed(ctx: PostTurnContext) -> bool:
    """Return True when the session actor may trigger Honcho extraction (owner DM lanes).

    Args:
        ctx (PostTurnContext): Turn-end hook context.

    Returns:
        bool: ``False`` for non-owner sessions when owner ids are configured.

    Examples:
        >>> import sqlite3
        >>> from unittest.mock import MagicMock
        >>> from sevn.agent.tracing.sink import NullTraceSink
        >>> from sevn.gateway.hooks.post_turn_hooks import PostTurnContext
        >>> from sevn.gateway.user.user_model_turn import _owner_lane_allowed
        >>> from sevn.storage.migrate import apply_migrations
        >>> db = sqlite3.connect(":memory:")
        >>> apply_migrations(db)
        >>> _ = db.execute(
        ...     "INSERT INTO gateway_sessions "
        ...     "(session_id, scope_key, channel, user_id, created_at, updated_at) "
        ...     "VALUES ('s', 'telegram:1', 'telegram', '1', 'now', 'now')"
        ... )
        >>> db.commit()
        >>> router = MagicMock()
        >>> router._owner_ids = frozenset({"1"})
        >>> ctx = PostTurnContext(
        ...     router=router,
        ...     conn=db,
        ...     trace=NullTraceSink(),
        ...     session_id="s",
        ...     correlation_id="t",
        ...     terminal_status="ok",
        ...     turn_wall_ns=1,
        ... )
        >>> _owner_lane_allowed(ctx)
        True
    """
    sess = load_session_row(ctx.conn, ctx.session_id)
    if sess is None:
        return False
    owner_ids = getattr(ctx.router, "_owner_ids", None)
    if not owner_ids:
        return True
    return sess.user_id in owner_ids


def _merge_action(
    before: UserProfile,
    delta: InferredFact,
    *,
    deny_topics: list[str],
) -> MergeAction | None:
    """Classify how one delta would change the profile (for ``user_model.update`` spans).

    Args:
        before (UserProfile): Profile snapshot before merge.
        delta (InferredFact): Candidate fact from the extractor.
        deny_topics (list[str]): Deny patterns applied before merge.

    Returns:
        MergeAction | None: Predicted action, or ``None`` when the delta is suppressed.

    Examples:
        >>> from datetime import UTC, datetime
        >>> from sevn.memory.user_model.models import InferredFact, UserProfile
        >>> from sevn.gateway.user.user_model_turn import _merge_action
        >>> prof = UserProfile(workspace_id="w", updated_at=datetime.now(tz=UTC), facts=[])
        >>> d = InferredFact(
        ...     id="1",
        ...     topic="theme",
        ...     value="dark",
        ...     confidence="high",
        ...     last_observed_at=datetime.now(tz=UTC),
        ... )
        >>> _merge_action(prof, d, deny_topics=[])
        'append'
    """
    from sevn.memory.user_model.deny_topics import topic_denied

    if topic_denied(delta.topic, deny_topics):
        return None
    active = [f for f in before.facts if f.superseded_by_id is None]
    same_topic = [f for f in active if f.topic == delta.topic]
    if not same_topic:
        return "append"
    exact = next((f for f in same_topic if f.value.strip() == delta.value.strip()), None)
    if exact is not None:
        return "bump"
    return "supersede"


async def _emit_user_model_span(
    trace: TraceSink,
    *,
    session_id: str,
    turn_id: str,
    tier: str | None,
    kind: str,
    attrs: dict[str, object],
) -> None:
    """Emit one Honcho trace row (`specs/32-memory-honcho.md` §7).

    Args:
        trace (TraceSink): Active gateway trace sink.
        session_id (str): Owning session id.
        turn_id (str): Turn correlation id.
        tier (str | None): Executor tier label when known.
        kind (str): Span kind (``user_model.extract`` / ``user_model.update``).
        attrs (dict[str, object]): Redaction-safe attribute payload.

    Examples:
        >>> import asyncio
        >>> from sevn.agent.tracing.sink import NullTraceSink
        >>> from sevn.gateway.user.user_model_turn import _emit_user_model_span
        >>> asyncio.run(
        ...     _emit_user_model_span(
        ...         NullTraceSink(),
        ...         session_id="s",
        ...         turn_id="t",
        ...         tier="B",
        ...         kind="user_model.extract",
        ...         attrs={"fact_count": 0},
        ...     )
        ... ) is None
        True
    """
    now = time.time_ns()
    await trace.emit(
        TraceEvent(
            kind=kind,
            span_id=str(uuid.uuid4()),
            parent_span_id=None,
            session_id=session_id,
            turn_id=turn_id,
            tier=tier,
            ts_start_ns=now,
            ts_end_ns=now,
            status="ok",
            attrs=attrs,
        ),
    )


async def _run_extraction_job(
    *,
    trace: TraceSink,
    session_id: str,
    turn_id: str,
    tier: str | None,
    workspace: WorkspaceConfig,
    content_root: str,
    turn_user_text: str,
    model_id: str,
    deny_topics: list[str],
    max_facts: int,
) -> None:
    """Extract, merge, persist, and emit observability spans for one queued job.

    Args:
        trace (TraceSink): Active gateway trace sink.
        session_id (str): Owning session id.
        turn_id (str): Turn correlation id.
        tier (str | None): Executor tier label when known.
        workspace (WorkspaceConfig): Parsed workspace configuration.
        content_root (str): Workspace content root path string.
        turn_user_text (str): Sanitised user text for the turn.
        model_id (str): Resolved extractor model id.
        deny_topics (list[str]): Topic deny patterns from config.
        max_facts (int): Profile cap from config.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_run_extraction_job)
        True
    """
    providers_obj = _providers_dict(workspace)
    transport_name = resolve_transport_for_model_id(providers_obj, model_id)
    resolved_id, transport = resolve_model(model_id=model_id, transport_name=transport_name)
    extractor = UserModelExtractor(transport)
    deltas = await extractor.extract_deltas(
        workspace_root=content_root,
        turn_user_text=turn_user_text,
        active_session_id=session_id,
        model_id=resolved_id,
        deny_topic_patterns=deny_topics,
    )
    await _emit_user_model_span(
        trace,
        session_id=session_id,
        turn_id=turn_id,
        tier=tier,
        kind="user_model.extract",
        attrs={
            "turn_id": turn_id,
            "fact_count": len(deltas),
            "llm_cost_tokens": 0,
            "llm_cost_usd": 0.0,
            "extractor_model": resolved_id,
        },
    )
    if not deltas:
        return
    store = UserModelStore()
    profile = store.load(content_root)
    for delta in deltas:
        action = _merge_action(profile, delta, deny_topics=deny_topics)
        if action is None:
            continue
        await _emit_user_model_span(
            trace,
            session_id=session_id,
            turn_id=turn_id,
            tier=tier,
            kind="user_model.update",
            attrs={
                "topic": delta.topic,
                "action": action,
                "confidence": delta.confidence,
            },
        )
    merged = UserModelMerger().merge(
        profile,
        deltas,
        deny_topic_patterns=deny_topics,
        max_facts=max_facts,
    )
    store.save(content_root, merged)


async def maybe_schedule_user_model_extraction_after_turn(ctx: PostTurnContext) -> None:
    """Schedule async user-model extraction when gates pass (`specs/32-memory-honcho.md` §2.7).

    Args:
        ctx (PostTurnContext): Turn-end state from ``run_post_turn_hooks``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(maybe_schedule_user_model_extraction_after_turn)
        True
    """
    if ctx.terminal_status != "ok":
        return
    router = ctx.router
    workspace = getattr(router, "_workspace", None)
    content_root = getattr(router, "_content_root", None)
    if workspace is None or content_root is None:
        return
    if not user_model_extraction_enabled(workspace):
        return
    if not _owner_lane_allowed(ctx):
        return
    meta = load_turn_metadata(ctx.conn, ctx.correlation_id)
    if meta is None:
        return
    tier = str(meta.tier or "").strip().upper()
    um_cfg = workspace.memory.user_model if workspace.memory is not None else None
    trigger_tiers = {
        str(t).strip().upper()
        for t in (um_cfg.trigger_tiers if um_cfg is not None else ("B", "C", "D"))
    }
    if tier not in trigger_tiers:
        return
    user_text = lookup_user_text_for_turn(
        ctx.conn,
        session_id=ctx.session_id,
        turn_id=ctx.correlation_id,
    )
    if not user_text:
        return
    try:
        model_id = resolve_model_slot(workspace, ModelSlot.user_model_extractor)
    except Exception:
        logger.exception(
            "user_model_extractor_model_unresolved session_id={} turn_id={}",
            ctx.session_id,
            ctx.correlation_id,
        )
        return
    workspace_key = str(content_root)
    deny_topics = list(um_cfg.deny_topics if um_cfg is not None else [])
    max_facts = int(um_cfg.max_facts if um_cfg is not None else 64)

    async def _job() -> None:
        await _run_extraction_job(
            trace=ctx.trace,
            session_id=ctx.session_id,
            turn_id=ctx.correlation_id,
            tier=meta.tier,
            workspace=workspace,
            content_root=workspace_key,
            turn_user_text=user_text,
            model_id=model_id,
            deny_topics=deny_topics,
            max_facts=max_facts,
        )

    await schedule_user_model_extraction(workspace_key, _job)


__all__ = [
    "lookup_user_text_for_turn",
    "maybe_schedule_user_model_extraction_after_turn",
]
