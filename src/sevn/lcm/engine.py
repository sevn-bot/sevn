"""LCM engine façade — ingest, assemble, compaction, search (`specs/15-memory-lcm.md` §2).

Module: sevn.lcm.engine
Depends: sevn.config.workspace_config, sevn.agent.providers.transport, sevn.agent.tracing.sink

Exports:
    Classes:
        SessionView — gateway session scope ids.
        InboundLcmMessage — one persisted inbound row shape.
        SessionSummaryHit — keyword hit row.
        LcmEngine — public orchestrator.

Examples:
    >>> LcmEngine.__name__
    'LcmEngine'
"""

from __future__ import annotations

import json
import sqlite3  # noqa: TC003 — type hints + doctest examples
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003 — ``workspace_root`` normalization uses ``Path`` at runtime
from time import time_ns
from typing import TYPE_CHECKING, Literal, cast

from sevn.agent.tracing.sink import TraceEvent, TraceSink
from sevn.config.defaults import (
    DEFAULT_LCM_UNCACHED_SUFFIX_CEILING_TOKENS,
    DEFAULT_LCM_UNCACHED_SUFFIX_FLOOR_TOKENS,
)
from sevn.config.workspace_config import (
    LcmWorkspaceConfig,
    MemoryPreCompactionFlushWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.lcm.assembler import AssembledContext, LcmAssembler
from sevn.lcm.compaction import CompactionResult, CompactionScheduler
from sevn.lcm.flush import MemoryWrites  # noqa: TC001 — forward-ref only; keep visible for readers
from sevn.lcm.large_files import maybe_spill_large_payload
from sevn.lcm.search import search_session_summaries as search_summaries_sql

if TYPE_CHECKING:
    from sevn.agent.providers.transport import Transport

LcmMessageKind = Literal["message", "command", "blocked"]
LcmMessageStatus = Literal["pending", "sent", "failed"]
SummarySearchScope = Literal["workspace", "conversation", "same_telegram_topic"]


@dataclass(frozen=True)
class SessionView:
    """Read-only LCM session scope (`specs/15-memory-lcm.md` §2.1)."""

    session_key: str
    conversation_id: int
    channel: str
    group_name: str | None = None
    topic: str | None = None


@dataclass(frozen=True)
class InboundLcmMessage:
    """Inbound row prior to persistence (`specs/15-memory-lcm.md` §2.1)."""

    role: str
    content: str
    kind: LcmMessageKind
    visible_to_llm: bool
    status: LcmMessageStatus
    message_parts: dict[str, object] | list[object] | None = None
    token_estimate: int | None = None


@dataclass(frozen=True)
class SessionSummaryHit:
    """Keyword hit against ``session_end`` summaries (`specs/15-memory-lcm.md` §3.3)."""

    summary_id: str
    conversation_id: int
    excerpt: str
    session_key: str
    channel: str
    created_at: str


def _effective_lcm(workspace_cfg: WorkspaceConfig | None) -> LcmWorkspaceConfig:
    """Return the effective LCM subtree (defaults when missing).

    Args:
        workspace_cfg (WorkspaceConfig | None): Parsed workspace config or ``None``.

    Returns:
        LcmWorkspaceConfig: Live subtree when present, else a fresh defaults instance.

    Examples:
        >>> _effective_lcm(None).__class__.__name__
        'LcmWorkspaceConfig'
    """
    return workspace_cfg.lcm if workspace_cfg and workspace_cfg.lcm else LcmWorkspaceConfig()


def _effective_flush_cfg(
    workspace_cfg: WorkspaceConfig | None,
) -> MemoryPreCompactionFlushWorkspaceConfig:
    """Return the effective pre-compaction flush subtree (defaults when missing).

    Args:
        workspace_cfg (WorkspaceConfig | None): Parsed workspace config or ``None``.

    Returns:
        MemoryPreCompactionFlushWorkspaceConfig: Live subtree when present, else defaults.

    Examples:
        >>> _effective_flush_cfg(None).__class__.__name__
        'MemoryPreCompactionFlushWorkspaceConfig'
    """
    if workspace_cfg and workspace_cfg.memory and workspace_cfg.memory.pre_compaction_flush:
        return workspace_cfg.memory.pre_compaction_flush
    return MemoryPreCompactionFlushWorkspaceConfig()


def _utc_day_tuple() -> tuple[int, int, int]:
    """Return today's UTC calendar day as a ``(year, month, day)`` tuple.

    Returns:
        tuple[int, int, int]: Current UTC ``(year, month, day)``.

    Examples:
        >>> y, m, d = _utc_day_tuple()
        >>> y >= 2024 and 1 <= m <= 12 and 1 <= d <= 31
        True
    """
    now = datetime.now(UTC).timetuple()
    return (now.tm_year, now.tm_mon, now.tm_mday)


def _json_safe_attrs(attrs: dict[str, object]) -> dict[str, object]:
    """Coerce non-scalar values to ``str`` so the dict is JSON-encodable.

    Args:
        attrs (dict[str, object]): Trace attributes (mixed scalar/object values).

    Returns:
        dict[str, object]: Same keys with non-scalar values replaced by ``str(v)``.

    Examples:
        >>> _json_safe_attrs({"a": 1, "b": object()})["a"]
        1
        >>> isinstance(_json_safe_attrs({"b": object()})["b"], str)
        True
    """
    from sevn.agent.tracing.attrs import json_safe_trace_attrs

    return json_safe_trace_attrs(attrs)


async def _emit_trace(
    sink: TraceSink | None,
    *,
    session_key: str,
    turn_id: str,
    kind: str,
    status: str,
    attrs: dict[str, object],
) -> None:
    """Emit one ``TraceEvent`` when ``sink`` is wired; no-op otherwise.

    Args:
        sink (TraceSink | None): Optional trace sink (`specs/04-tracing.md`).
        session_key (str): Logical session id for the event.
        turn_id (str): Gateway turn correlation id when known, else ``"lcm"``.
        kind (str): Event kind label (e.g. ``"lcm.ingest"``).
        status (str): Event status (``"ok"``, ``"error"``, ``"skipped"``).
        attrs (dict[str, object]): Attributes; coerced via :func:`_json_safe_attrs`.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_emit_trace)
        True
    """
    if sink is None:
        return
    now = time_ns()
    await sink.emit(
        TraceEvent(
            kind=kind,
            span_id=str(uuid.uuid4()),
            parent_span_id=None,
            session_id=session_key,
            turn_id=turn_id,
            tier=None,
            ts_start_ns=now,
            ts_end_ns=now,
            status=status,
            attrs=_json_safe_attrs(attrs),
        ),
    )


class LcmEngine:
    """Lossless context: ingest, assemble, compact, search summaries."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        workspace_root: Path,
        workspace_cfg: WorkspaceConfig | None = None,
        trace_sink: TraceSink | None = None,
        transport: Transport | None = None,
    ) -> None:
        """Create an engine bound to ``sevn.db``.

        Args:
            conn (sqlite3.Connection): Migrated workspace SQLite connection.
            workspace_root (Path): Content root for flush filesystem writes (gateway-owned).
            workspace_cfg (WorkspaceConfig | None, optional): Parsed ``sevn.json`` subtree
                access. Defaults to ``None``.
            trace_sink (TraceSink | None, optional): Optional tracer (`specs/04-tracing.md`).
                Defaults to ``None``.
            transport (Transport | None, optional): Proxy-backed LLM transport for
                compaction. Defaults to ``None``.

        Examples:
            >>> import sqlite3
            >>> from pathlib import Path
            >>> eng = LcmEngine(sqlite3.connect(":memory:"), workspace_root=Path("."))
            >>> isinstance(eng, LcmEngine)
            True
        """
        self._conn = conn
        self._workspace_root = workspace_root
        self._workspace_cfg = workspace_cfg
        self._trace_sink = trace_sink
        self._transport = transport
        self._assembler = LcmAssembler(conn)
        self._scheduler = CompactionScheduler(conn)

    async def ingest(
        self,
        session: SessionView,
        msg: InboundLcmMessage,
        *,
        turn_id: str = "lcm",
    ) -> int:
        """Persist ``msg``; maintain ``lcm_context_items``; return ``lcm_messages.id``.

        Args:
            session (SessionView): Gateway session scope used for conversation upsert.
            msg (InboundLcmMessage): Inbound row prior to persistence.
            turn_id (str): Gateway turn correlation id for trace export (default ``lcm``).

        Returns:
            int: ``lcm_messages.id`` of the newly inserted row.

        Raises:
            RuntimeError: When ``lcm_enabled`` is disabled in workspace config.
            ValueError: When ``blocked`` rows violate stub shape (`specs/15-memory-lcm.md` §6).

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LcmEngine.ingest)
            True
        """
        lcm = _effective_lcm(self._workspace_cfg)
        if not lcm.enabled:
            msg_obj = "LCM disabled (specs/15-memory-lcm.md §5 lcm_enabled)"
            raise RuntimeError(msg_obj)

        if msg.kind == "blocked" and ".llmignore" not in msg.content:
            msg_obj = "blocked lcm_messages must reference .llmignore stub storage (specs/15-memory-lcm.md §3.1)"
            raise ValueError(msg_obj)

        now = datetime.now(UTC).isoformat(timespec="seconds")
        cid = self._upsert_conversation(session, now)

        spill = maybe_spill_large_payload(
            conn=self._conn,
            conversation_id=cid,
            token_estimate=int(msg.token_estimate or max(1, len(msg.content) // 4)),
            threshold=lcm.large_file_token_threshold,
            content=msg.content,
            file_name=None,
            mime_type=None,
        )
        body = spill.stub_content if spill else msg.content

        seq_row = self._conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM lcm_messages WHERE conversation_id = ?",
            (cid,),
        ).fetchone()
        seq = int(seq_row[0])
        parts_json = json.dumps(msg.message_parts) if msg.message_parts is not None else None
        tok = int(msg.token_estimate) if msg.token_estimate else max(1, len(body) // 4)

        cur = self._conn.execute(
            """
            INSERT INTO lcm_messages (
                conversation_id, seq, role, content, token_count, message_parts,
                kind, visible_to_llm, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cid,
                seq,
                msg.role,
                body,
                tok,
                parts_json,
                msg.kind,
                1 if msg.visible_to_llm else 0,
                msg.status,
                now,
            ),
        )
        mid = int(cast("int", cur.lastrowid))

        ord_row = self._conn.execute(
            "SELECT COALESCE(MAX(ordinal), -1) FROM lcm_context_items WHERE conversation_id = ?",
            (cid,),
        ).fetchone()
        next_ord = int(ord_row[0]) + 1 if ord_row else 0
        self._conn.execute(
            """
            INSERT INTO lcm_context_items (
                conversation_id, ordinal, item_type, message_id, summary_id
            ) VALUES (?, ?, 'message', ?, NULL)
            """,
            (cid, next_ord, mid),
        )

        await _emit_trace(
            self._trace_sink,
            session_key=session.session_key,
            turn_id=turn_id,
            kind="lcm.ingest",
            status="ok",
            attrs={
                "conversation_id": cid,
                "message_id": mid,
                "seq": seq,
                "role": msg.role,
                "content": body,
                "token_count": tok,
                "message_parts": msg.message_parts,
                "kind": msg.kind,
                "visible_to_llm": bool(msg.visible_to_llm),
                "status": msg.status,
            },
        )
        return mid

    def _upsert_conversation(self, session: SessionView, now_iso: str) -> int:
        """Insert or touch ``lcm_conversations`` row; return id.

        Args:
            session (SessionView): Gateway session scope with channel/group/topic.
            now_iso (str): ISO-8601 UTC timestamp written to ``created_at`` / ``updated_at``.

        Returns:
            int: ``lcm_conversations.id`` of the existing or freshly inserted row.

        Examples:
            >>> LcmEngine._upsert_conversation.__name__
            '_upsert_conversation'
        """
        row = self._conn.execute(
            "SELECT id FROM lcm_conversations WHERE session_key = ?",
            (session.session_key,),
        ).fetchone()
        if row:
            cid = int(row[0])
            self._conn.execute(
                """
                UPDATE lcm_conversations
                SET channel = ?, group_name = ?, topic = ?, updated_at = ?
                WHERE id = ?
                """,
                (session.channel, session.group_name, session.topic, now_iso, cid),
            )
            return cid
        cur = self._conn.execute(
            """
            INSERT INTO lcm_conversations (
                session_key, channel, group_name, topic, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session.session_key,
                session.channel,
                session.group_name,
                session.topic,
                now_iso,
                now_iso,
            ),
        )
        return int(cast("int", cur.lastrowid))

    async def assemble(
        self,
        *,
        session: SessionView,
        system_prompt: str | None,
        token_budget: int,
    ) -> AssembledContext:
        """Build messages within ``token_budget`` (`specs/15-memory-lcm.md` §4).

        Args:
            session (SessionView): Conversation scope (``conversation_id`` is read).
            system_prompt (str | None): Optional system instruction prepended when set.
            token_budget (int): Approximate token cap for assembled body (ex-system).

        Returns:
            AssembledContext: Ordered chat messages plus telemetry integers.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LcmEngine.assemble)
            True
        """
        lcm = _effective_lcm(self._workspace_cfg)
        ctx = await self._assembler.assemble(
            conversation_id=session.conversation_id,
            token_budget=token_budget,
            fresh_tail_count=lcm.fresh_tail_count,
            system_prompt=system_prompt,
        )
        await _emit_trace(
            self._trace_sink,
            session_key=session.session_key,
            turn_id="lcm",
            kind="lcm.assemble",
            status="ok",
            attrs={
                "budget": token_budget,
                "used": ctx.tokens_used,
                "fresh_tail_n": ctx.fresh_tail_n,
                "summary_nodes": ctx.summary_nodes,
            },
        )
        return ctx

    async def after_turn(
        self,
        *,
        session: SessionView,
        summary_model_id: str,
    ) -> CompactionResult | None:
        """Run incremental compaction when thresholds permit (`specs/15-memory-lcm.md` §2).

        Args:
            session (SessionView): Conversation scope to compact.
            summary_model_id (str): Provider-rooted model id used for summarisation.

        Returns:
            CompactionResult | None: Telemetry on success; ``None`` when LCM/auto-compaction
                is disabled in workspace config.

        Raises:
            NotImplementedError: When ``transport`` is unset but compaction is requested.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LcmEngine.after_turn)
            True
        """
        lcm = _effective_lcm(self._workspace_cfg)
        if not lcm.enabled or lcm.autocompact_disabled:
            return None
        if self._transport is None:
            msg = (
                "LcmEngine.transport is unset — cannot run auto-compaction "
                "(specs/15-memory-lcm.md §4; wire Transport via specs/05-llm-transports.md)."
            )
            raise NotImplementedError(msg)
        return await self._run_compaction(session, summary_model_id, lcm=lcm)

    async def compact(
        self,
        *,
        session: SessionView,
        summary_model_id: str,
    ) -> CompactionResult:
        """Operator-triggered compaction.

        Args:
            session (SessionView): Conversation scope to compact.
            summary_model_id (str): Provider-rooted model id used for summarisation.

        Returns:
            CompactionResult: Telemetry from this manual compaction pass.

        Raises:
            NotImplementedError: When ``transport`` is unset (no proxy wiring).

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LcmEngine.compact)
            True
        """
        lcm = _effective_lcm(self._workspace_cfg)
        if self._transport is None:
            msg = (
                "LcmEngine.transport is unset — manual compaction requires Transport "
                "(specs/15-memory-lcm.md §2 `compact`)."
            )
            raise NotImplementedError(msg)
        return await self._run_compaction(session, summary_model_id, lcm=lcm)

    async def _run_compaction(
        self,
        session: SessionView,
        summary_model_id: str,
        *,
        lcm: LcmWorkspaceConfig,
    ) -> CompactionResult:
        """Shared scheduler driver used by ``after_turn`` and ``compact``.

        Args:
            session (SessionView): Conversation scope to compact.
            summary_model_id (str): Provider-rooted model id used for summarisation.
            lcm (LcmWorkspaceConfig): Resolved LCM workspace subtree.

        Returns:
            CompactionResult: Scheduler telemetry for this pass.

        Raises:
            RuntimeError: When the invariant ``transport is not None`` is violated.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LcmEngine._run_compaction)
            True
        """
        if self._transport is None:
            raise RuntimeError("LcmEngine.transport is unset — internal compaction invariant")
        result = await self._scheduler.run_incremental(
            conversation_id=session.conversation_id,
            fresh_tail_count=lcm.fresh_tail_count,
            incremental_max_depth=lcm.incremental_max_depth,
            transport=self._transport,
            model_id=summary_model_id,
            leaf_min_fanout=lcm.leaf_min_fanout,
            leaf_chunk_tokens=lcm.leaf_chunk_tokens,
            condensed_min_fanout=lcm.condensed_min_fanout,
            leaf_target_chars=max(256, lcm.leaf_target_tokens // 2),
            condensed_target_chars=max(256, lcm.condensed_target_tokens // 2),
            dedup_overlap_threshold=lcm.dedup_overlap_threshold,
            smart_collapse_enabled=lcm.smart_collapse_enabled,
            summary_language=lcm.summary_language,
            content_root=self._workspace_root,
        )
        await _emit_trace(
            self._trace_sink,
            session_key=session.session_key,
            turn_id="lcm",
            kind="lcm.compaction",
            status="ok",
            attrs={
                "depth": result.depth_created_max,
                "nodes": result.summaries_created,
                "model_id": result.model_id,
                "tokens_in": result.tokens_in,
                "tokens_out": result.tokens_out,
            },
        )
        return result

    async def search_session_summaries(
        self,
        *,
        query: str,
        date_from: str | None,
        date_to: str | None,
        limit: int = 10,
        scope: SummarySearchScope | None = None,
        scope_session: SessionView | None = None,
    ) -> list[SessionSummaryHit]:
        """Keyword search over ``session_end`` rows (`specs/15-memory-lcm.md` §3.3).

        Args:
            query (str): Substring matched against ``lcm_summaries.content``.
            date_from (str | None): Inclusive lower bound on ``created_at`` (ISO text).
            date_to (str | None): Inclusive upper bound on ``created_at`` (ISO text).
            limit (int, optional): Maximum hits to return. Defaults to ``10``.
            scope (SummarySearchScope | None, optional): Fan-out selector — ``"workspace"``
                (default), ``"conversation"``, or ``"same_telegram_topic"``.
            scope_session (SessionView | None, optional): Required when ``scope`` is
                ``"conversation"`` or ``"same_telegram_topic"``.

        Returns:
            list[SessionSummaryHit]: Newest-first hits, each carrying a 512-char excerpt.

        Raises:
            ValueError: When ``scope`` requires ``scope_session`` and it is missing.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LcmEngine.search_session_summaries)
            True
        """
        lcm = _effective_lcm(self._workspace_cfg)
        conv_filter: list[int] | None = None
        scope_eff = scope or "workspace"
        if scope_eff == "conversation":
            if scope_session is None:
                msg = "scope_session required when scope='conversation'"
                raise ValueError(msg)
            conv_filter = [scope_session.conversation_id]
        elif scope_eff == "same_telegram_topic":
            if scope_session is None:
                msg = "scope_session required when scope='same_telegram_topic'"
                raise ValueError(msg)
            cap = lcm.topic_search_max_sessions
            gn = scope_session.group_name or ""
            tp = scope_session.topic or ""
            rows = self._conn.execute(
                """
                SELECT id FROM lcm_conversations
                WHERE COALESCE(group_name, '') = ?
                  AND COALESCE(topic, '') = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (gn, tp, cap),
            ).fetchall()
            conv_filter = [int(r[0]) for r in rows]

        rows = search_summaries_sql(
            self._conn,
            query=query,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            conversation_ids_filter=conv_filter,
        )
        hits: list[SessionSummaryHit] = []
        for r in rows:
            excerpt = str(r["content"])[:512]
            hits.append(
                SessionSummaryHit(
                    summary_id=str(r["summary_id"]),
                    conversation_id=int(r["conversation_id"]),
                    excerpt=excerpt,
                    session_key=str(r["session_key"]),
                    channel=str(r["channel"]),
                    created_at=str(r["created_at"]),
                ),
            )
        return hits

    def pre_compaction_flush_recommended(
        self,
        *,
        session: SessionView,
        active_context_window_tokens: int,
    ) -> bool:
        """Return True when recent visible tail approaches suffix fraction (`specs/15-memory-lcm.md` §5.3).

        Args:
            session (SessionView): Conversation scope to inspect.
            active_context_window_tokens (int): Effective model context window in tokens.

        Returns:
            bool: ``True`` when the recent visible tail meets/exceeds the suffix target;
                ``False`` if LCM or flush is disabled.

        Examples:
            >>> LcmEngine.pre_compaction_flush_recommended.__name__
            'pre_compaction_flush_recommended'
        """
        lcm = _effective_lcm(self._workspace_cfg)
        flush = _effective_flush_cfg(self._workspace_cfg)
        if not lcm.enabled or not flush.enabled:
            return False
        frac = lcm.uncached_suffix_fraction
        target = int(active_context_window_tokens * frac)
        target = max(DEFAULT_LCM_UNCACHED_SUFFIX_FLOOR_TOKENS, target)
        target = min(DEFAULT_LCM_UNCACHED_SUFFIX_CEILING_TOKENS, target)

        row = self._conn.execute(
            """
            SELECT COALESCE(SUM(token_count), 0)
            FROM (
                SELECT token_count FROM lcm_messages
                WHERE conversation_id = ?
                  AND kind = 'message'
                  AND visible_to_llm = 1
                  AND status = 'sent'
                ORDER BY seq DESC
                LIMIT ?
            )
            """,
            (session.conversation_id, lcm.fresh_tail_count),
        ).fetchone()
        recent = int(row[0]) if row else 0
        return recent >= target

    async def apply_memory_writes_to_workspace(
        self,
        batch: MemoryWrites,
        *,
        utc_flush_day: tuple[int, int, int] | None = None,
        retry_invalid_once: bool = False,
        llm_regenerator: object | None = None,
    ) -> Literal["applied", "rejected", "skipped_disabled"]:
        """Validate flush batch against allowlist; optional filesystem apply (§2.2, §6).

        ``llm_regenerator`` hook is reserved for gateway-orchestrated retry turns.

        Args:
            batch (MemoryWrites): Parsed structured batch from the small model.
            utc_flush_day (tuple[int, int, int] | None, optional): Calendar gate for
                ``memory/YYYY-MM-DD.md`` entries. Defaults to today's UTC date.
            retry_invalid_once (bool, optional): Reserved retry flag. Defaults to ``False``.
            llm_regenerator (object | None, optional): Reserved regenerator hook. Defaults
                to ``None``.

        Returns:
            Literal["applied", "rejected", "skipped_disabled"]: ``"applied"`` after writes
                land, ``"rejected"`` when validation fails, ``"skipped_disabled"`` when
                pre-compaction flush is disabled.

        Raises:
            ValueError: When any allowlisted path resolves outside ``workspace_root``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LcmEngine.apply_memory_writes_to_workspace)
            True
        """
        _ = llm_regenerator
        _ = retry_invalid_once
        flush = _effective_flush_cfg(self._workspace_cfg)
        if not flush.enabled:
            await _emit_trace(
                self._trace_sink,
                session_key="flush",
                turn_id="lcm",
                kind="lcm.pre_compaction_flush",
                status="skipped",
                attrs={
                    "writes_n": len(batch.writes),
                    "retry": False,
                    "outcome": "skipped_disabled",
                },
            )
            return "skipped_disabled"
        day = utc_flush_day or _utc_day_tuple()
        from sevn.lcm.flush import validate_memory_writes

        try:
            validate_memory_writes(batch, utc_flush_day=day)
        except ValueError:
            await _emit_trace(
                self._trace_sink,
                session_key="flush",
                turn_id="lcm",
                kind="lcm.pre_compaction_flush",
                status="error",
                attrs={"writes_n": len(batch.writes), "retry": False, "outcome": "rejected"},
            )
            return "rejected"

        root = self._workspace_root.resolve()
        for w in batch.writes:
            rel = w.path.strip().replace("\\", "/").lstrip("./")
            target = (root / rel).resolve()
            try:
                target.relative_to(root)
            except ValueError:
                msg = "flush path escapes workspace root"
                raise ValueError(msg) from None
            target.parent.mkdir(parents=True, exist_ok=True)
            if w.operation == "replace":
                target.write_text(w.content, encoding="utf-8")
            else:
                prev = target.read_text(encoding="utf-8") if target.exists() else ""
                target.write_text(prev + w.content, encoding="utf-8")

        await _emit_trace(
            self._trace_sink,
            session_key="flush",
            turn_id="lcm",
            kind="lcm.pre_compaction_flush",
            status="ok",
            attrs={"writes_n": len(batch.writes), "retry": False, "outcome": "applied"},
        )
        return "applied"
