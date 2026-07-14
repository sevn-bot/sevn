"""Durable gateway sessions + message rows (`specs/17-gateway.md` §2.5, §3.1).
Module: sevn.gateway.session_manager
Depends: sqlite3, asyncio, `gateway_*` tables (`specs/03-storage.md` migration 3).
Exports:
    SessionRow — diagnostics projection of ``gateway_sessions`` rows.
    SessionManager — messages, unanswered tail, assistant two-phase commits,
        per-session single-consumer dispatch queue (`specs/16-harness-discipline.md` §4.3);
        ``rotate_session`` archives prior scope row and mints a new ``session_id``.
    load_session_row — read-only session metadata fetch for tests/admin.
    get_tts_mode_override — session-level TTS mode override reader.
    set_tts_mode_override — session-level TTS mode override writer.
    format_lcm_status_lines — LCM ingest/compaction hints for ``/status``.
    latest_messages — message-row dump helper for assertions.
    unanswered_tail_message_id — read ``unanswered_tail_message_id`` for tests.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sqlite3
import time
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from sevn.config.defaults import DEFAULT_GATEWAY_SESSION_MESSAGE_CAP_DM
from sevn.config.workspace_config import LcmWorkspaceConfig, WorkspaceConfig
from sevn.gateway.browser.browser_lifecycle import close_browser_for_rotate
from sevn.gateway.queue.queue_multi import MultiDispatchHooks, MultiSpawnOutcome
from sevn.gateway.session.session_mirror import mark_session_superseded, mirror_gateway_message

DispatchFn = Callable[[str, str], Coroutine[Any, Any, None]]

# Generous global cap on concurrently executing turns across *all* sessions.
# Per-session ordering is already enforced by the per-session queue; this is a
# safety valve so a burst of distinct sessions cannot spawn unbounded
# concurrent LLM turns. Default is intentionally large — it only bites under
# pathological fan-out (`specs/17-gateway.md` §4.3, plan D9/W2.4).
DEFAULT_MAX_CONCURRENT_TURNS = 16


def _utc_now_iso() -> str:
    """Return a local-aware timestamp suitable for SQLite text columns.

    Carries the host's local UTC offset (e.g. ``+02:00``) so session-file
    message ``ts`` values line up with the service logs, which default to
    host-local time (``SEVN_LOG_TZ=local``; see
    :func:`sevn.logging.setup.resolve_service_log_timezone`). The offset is
    always explicit, so downstream renderers (:func:`sevn.gateway.util.timestamps.
    to_user_tz`) still convert into the user's zone without ambiguity, and
    pre-existing UTC (``+00:00``) rows continue to parse unchanged.

    Returns:
        str: ISO-8601 string with an explicit local UTC offset.

    Examples:
        >>> from datetime import datetime
        >>> datetime.fromisoformat(_utc_now_iso()).tzinfo is not None
        True
    """
    return datetime.now().astimezone().isoformat()


def _validate_user_id(channel: str, user_id: str) -> None:
    """Warn when a ``user_id`` looks truncated for the channel (`PROBLEMS.md` §3).

    Telegram user ids are numeric and almost always 8+ digits in practice; a 2-digit
    value (``"37"``) is the prefix/suffix of a longer id and indicates an upstream
    truncation. This guard logs it; it doesn't reject the write — the session would
    still get created so the user isn't blocked, but the operator sees the issue.

    Args:
        channel (str): Channel key.
        user_id (str): Channel-specific user id.

    Examples:
        >>> _validate_user_id("telegram", "8484033337") is None
        True
        >>> _validate_user_id("telegram", "37") is None  # warns, doesn't raise
        True
    """
    if channel == "telegram" and user_id.isdigit() and len(user_id) < 5:
        logger.warning(
            "session_user_id_truncated channel={} user_id={} len={} "
            "(telegram user ids are typically 8+ digits — upstream truncation?)",
            channel,
            user_id,
            len(user_id),
        )


def _validate_scope_key(scope_key: str) -> None:
    """Warn when a ``scope_key`` doesn't match a known shape (`PROBLEMS.md` §5).

    Expected shapes:

    - ``telegram:<chat_id>`` (DM, no topic)
    - ``telegram:<chat_id>:general`` (forum General topic)
    - ``telegram:<chat_id>:topic:<topic_id>`` (forum sub-topic)
    - ``webchat:<sub>``
    - Anything ending in ``::archived::<session_id>`` (rotation sentinel).

    Args:
        scope_key (str): Scope key about to be persisted.

    Examples:
        >>> _validate_scope_key("telegram:42:general") is None
        True
        >>> _validate_scope_key("telegram:42:gen") is None  # logged, not raised
        True
    """
    if "::archived::" in scope_key:
        return
    parts = scope_key.split(":")
    if scope_key.startswith("telegram:"):
        ok = (
            len(parts) == 2  # telegram:<chat>
            or (len(parts) == 3 and parts[2] == "general")
            or (len(parts) == 4 and parts[2] == "topic")
        )
        if not ok:
            logger.warning(
                "session_scope_key_malformed scope_key={} expected_shapes="
                "[telegram:<chat>, telegram:<chat>:general, telegram:<chat>:topic:<id>]",
                scope_key,
            )
        return
    if scope_key.startswith("webchat:"):
        if len(parts) < 2 or not parts[1]:
            logger.warning(
                "session_scope_key_malformed scope_key={} expected=webchat:<sub>",
                scope_key,
            )
        return
    # Unknown channel — just verify the channel:rest shape.
    if ":" not in scope_key:
        logger.warning(
            "session_scope_key_malformed scope_key={} missing channel:rest separator",
            scope_key,
        )


@dataclass(frozen=True)
class SessionRow:
    """Minimal projection for diagnostics/tests."""

    session_id: str
    scope_key: str
    channel: str
    user_id: str


class SessionManager:
    """Façade over ``gateway_sessions`` / ``gateway_messages``."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        message_cap: int | None = None,
        content_root: Path | None = None,
        workspace: WorkspaceConfig | None = None,
    ) -> None:
        """Bind the manager to a SQLite handle and per-session message cap.
        Args:
            conn (sqlite3.Connection): Open ``sevn.db`` handle (migration >=3).
            message_cap (int | None): Override max rows per session before
                FIFO trim; ``None`` uses :data:`DEFAULT_GATEWAY_SESSION_MESSAGE_CAP_DM`.
            content_root (Path | None): Workspace content root for JSONL mirror.
            workspace (WorkspaceConfig | None): Workspace config for mirror toggle.
        Examples:
            >>> import inspect
            >>> "conn" in inspect.signature(SessionManager).parameters
            True
        """
        self._conn = conn
        self._message_cap = message_cap or DEFAULT_GATEWAY_SESSION_MESSAGE_CAP_DM
        self._mirror_content_root = content_root
        self._mirror_workspace = workspace
        self._lock = asyncio.Lock()
        self._registry_lock = asyncio.Lock()
        self._per_session_enqueue_locks: dict[str, asyncio.Lock] = {}
        self._queues: dict[str, asyncio.Queue[str]] = {}
        self._worker_tasks: dict[str, asyncio.Task[None]] = {}
        self._active_dispatch_task: dict[str, asyncio.Task[None]] = {}
        self._dispatch_fn: DispatchFn | None = None
        self._drain_requested = False
        # Wave 3 (CONVERSATION_REVIEW_2026-05-28.md §A15 + §A16): one-shot
        # override for the next ``_run_turn`` to (a) use a specific user
        # message text + turn_id instead of the most recent pending user line,
        # and (b) reuse the assistant message being regenerated as the
        # ``edit_message_id`` anchor for the new turn so the user does not see
        # an extra triager opener stacked on top of the prior reply.
        # Value: ``(user_text, origin_turn_id, edit_message_id | None, suggested_tier | None)``.
        self._regen_target_for_session: dict[str, tuple[str, str, int | None, str | None]] = {}
        # Dashboard replay (`specs/16-harness-discipline.md` §4.4): one-shot
        # override for the next ``_run_turn`` using historical user text.
        # Value: ``(user_text, origin_turn_id, replay_job_id)``.
        self._replay_target_for_session: dict[str, tuple[str, str, str]] = {}
        # Terminal WS fan-out metadata keyed by session until post-turn hook runs.
        self._replay_terminal_for_session: dict[str, tuple[str, str]] = {}
        # Global concurrent-turn cap (plan D9/W2.4). Acquired by
        # ``_session_worker`` around each ``dispatch`` invocation only — never
        # held across ``enqueue_dispatch`` or the cancel path, so it cannot
        # stall the poll loop or block cancellation.
        self._turn_semaphore = asyncio.Semaphore(DEFAULT_MAX_CONCURRENT_TURNS)
        # P9: monotonic timestamp when cancel-mode superseded an in-flight turn.
        self._cancel_superseded_at: dict[str, float] = {}
        # W4: per-session queued task summaries for ``multi`` relatedness prompts.
        self._multi_queued_summaries: dict[str, list[str]] = {}

    @property
    def connection(self) -> sqlite3.Connection:
        """Return the bound SQLite handle for gateway+LCM glue.

        Returns:
            sqlite3.Connection: Open ``sevn.db`` connection.

        Examples:
            >>> import sqlite3
            >>> sm = SessionManager(sqlite3.connect(":memory:"))
            >>> sm.connection is sm._conn
            True
        """
        return self._conn

    def get_tts_mode_override(self, session_id: str) -> str | None:
        """Return per-session TTS override stored in ``metadata_json``.

        Args:
            session_id (str): Gateway session id.

        Returns:
            str | None: ``off`` / ``all`` / ``when_asked`` when set.

        Examples:
            >>> import sqlite3
            >>> from sevn.storage.migrate import apply_migrations
            >>> c = sqlite3.connect(":memory:")
            >>> apply_migrations(c)
            >>> sm = SessionManager(c)
            >>> sm.get_tts_mode_override("s") is None
            True
        """
        return get_tts_mode_override(self._conn, session_id)

    def set_tts_mode_override(self, session_id: str, mode: str | None) -> None:
        """Persist or clear per-session TTS override.

        Args:
            session_id (str): Gateway session id.
            mode (str | None): Override value, or ``None`` to reset.

        Examples:
            >>> import sqlite3
            >>> sm = SessionManager(sqlite3.connect(":memory:"))
            >>> sm.set_tts_mode_override("s", "all")  # doctest: +SKIP
        """
        set_tts_mode_override(self._conn, session_id, mode)

    def set_regen_target(
        self,
        session_id: str,
        *,
        user_text: str,
        origin_turn_id: str,
        edit_message_id: int | None = None,
        suggested_tier: str | None = None,
    ) -> None:
        """Stage a one-shot override for the next ``_run_turn`` on ``session_id``.

        Wave 3 (`CONVERSATION_REVIEW_2026-05-28.md` §A15 + §A16): quick-action
        regen calls this with the user message that ORIGINALLY produced the
        assistant message the user tapped regen on, plus the platform message
        id to edit so the regen turn reuses that bubble for its opener +
        finalized answer instead of stacking a fresh ack on top.

        Args:
            session_id (str): Target session id.
            user_text (str): Original user text to re-ask.
            origin_turn_id (str): Gateway turn id of the original user message.
            edit_message_id (int | None): Platform message id of the assistant
                bubble to edit (Telegram message_id); ``None`` to send fresh.
            suggested_tier (str | None): When regen follows an escalated turn,
                carry ``C``/``D`` so the replacement dispatch does not drop back
                to tier B (P12).

        Returns:
            None.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(SessionManager.set_regen_target)
            True
        """
        self._regen_target_for_session[session_id] = (
            user_text,
            origin_turn_id,
            edit_message_id,
            suggested_tier,
        )

    def take_regen_target(
        self,
        session_id: str,
    ) -> tuple[str, str, int | None, str | None] | None:
        """Return + clear the one-shot regen target staged by :meth:`set_regen_target`.

        Args:
            session_id (str): Target session id.

        Returns:
            tuple[str, str, int | None, str | None] | None: ``(user_text,
            origin_turn_id, edit_message_id, suggested_tier)`` or ``None``.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(SessionManager.take_regen_target)
            True
        """
        return self._regen_target_for_session.pop(session_id, None)

    def set_replay_target(
        self,
        session_id: str,
        *,
        user_text: str,
        origin_turn_id: str,
        replay_job_id: str,
    ) -> None:
        """Stage a one-shot dashboard replay override for the next ``_run_turn``.

        Args:
            session_id (str): Target session id.
            user_text (str): Historical user text to re-ask.
            origin_turn_id (str): Original user turn id being replayed.
            replay_job_id (str): Stable replay job identifier for WS fan-out.

        Returns:
            None.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(SessionManager.set_replay_target)
            True
        """
        self._replay_target_for_session[session_id] = (
            user_text,
            origin_turn_id,
            replay_job_id,
        )
        self._replay_terminal_for_session[session_id] = (replay_job_id, origin_turn_id)

    def take_replay_target(
        self,
        session_id: str,
    ) -> tuple[str, str, str] | None:
        """Return + clear the one-shot replay target staged by :meth:`set_replay_target`.

        Args:
            session_id (str): Target session id.

        Returns:
            tuple[str, str, str] | None: ``(user_text, origin_turn_id, replay_job_id)`` or ``None``.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(SessionManager.take_replay_target)
            True
        """
        return self._replay_target_for_session.pop(session_id, None)

    def pop_replay_terminal(self, session_id: str) -> tuple[str, str] | None:
        """Return + clear pending replay terminal metadata for ``session_id``.

        Args:
            session_id (str): Target session id.

        Returns:
            tuple[str, str] | None: ``(replay_job_id, origin_turn_id)`` or ``None``.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(SessionManager.pop_replay_terminal)
            True
        """
        return self._replay_terminal_for_session.pop(session_id, None)

    def _enqueue_lock(self, session_id: str) -> asyncio.Lock:
        """Return a stable asyncio lock for ``session_id`` queue mutations.
        Args:
            session_id (str): Target session id.
        Returns:
            asyncio.Lock: Lazily created lock shared per session.
        Examples:
            >>> import inspect
            >>> inspect.isfunction(SessionManager._enqueue_lock)
            True
        """
        lock = self._per_session_enqueue_locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._per_session_enqueue_locks[session_id] = lock
        return lock

    def _trim_session_messages(self, session_id: str) -> None:
        """Drop oldest rows when a session exceeds ``message_cap``.
        Args:
            session_id (str): Session whose row count is being bounded.
        Examples:
            >>> import inspect
            >>> inspect.isfunction(SessionManager._trim_session_messages)
            True
        """
        row = self._conn.execute(
            "SELECT COUNT(*) FROM gateway_messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        count = int(row[0]) if row else 0
        over = count - self._message_cap
        if over <= 0:
            return
        to_drop = self._conn.execute(
            """
            SELECT id FROM gateway_messages
            WHERE session_id = ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (session_id, over),
        ).fetchall()
        for (mid,) in to_drop:
            self._conn.execute(
                "DELETE FROM gateway_messages WHERE id = ?",
                (int(mid),),
            )

    async def ensure_session(self, *, scope_key: str, channel: str, user_id: str) -> str:
        """Create or return ``session_id`` for a stable scope key.
        Args:
            scope_key (str): Stable session scope (``channel:user_id`` by default).
            channel (str): Channel name (``telegram``, ``webchat``, ...).
            user_id (str): Channel-specific user identifier.
        Returns:
            str: Persistent session id (UUID hex).
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SessionManager.ensure_session)
            True
        """
        _validate_scope_key(scope_key)
        _validate_user_id(channel, user_id)
        async with self._lock:
            row = self._conn.execute(
                "SELECT session_id FROM gateway_sessions WHERE scope_key = ?",
                (scope_key,),
            ).fetchone()
            if row:
                return str(row[0])
            sid = uuid.uuid4().hex
            now = _utc_now_iso()
            self._conn.execute(
                """
                INSERT INTO gateway_sessions (
                    session_id, scope_key, channel, user_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (sid, scope_key, channel, user_id, now, now),
            )
            self._conn.commit()
            return sid

    async def rotate_session(
        self,
        session_id: str,
        *,
        content_root: Path | None = None,
    ) -> str:
        """Archive the active scope row and mint a new ``session_id`` for ``/new``.

        Relocates the prior row's ``scope_key`` to ``{scope}::archived::{session_id}``
        so the live ``scope_key`` stays unique without a schema migration. When
        ``content_root`` is set and bootstrap is incomplete, clears cached
        ``intro_state`` for the operator scope so intro can re-run.

        Args:
            session_id (str): Session id to rotate away from.
            content_root (Path | None): Workspace content root for bootstrap /
                mirror side effects; defaults to the manager's mirror root.

        Returns:
            str: New session id for the same logical scope.

        Raises:
            ValueError: When ``session_id`` is unknown.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SessionManager.rotate_session)
            True
        """
        mirror_root = content_root if content_root is not None else self._mirror_content_root
        async with self._lock:
            row = self._conn.execute(
                """
                SELECT scope_key, channel, user_id
                FROM gateway_sessions WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            if row is None:
                msg = f"unknown session_id {session_id!r}"
                raise ValueError(msg)
            scope_key, channel, user_id = str(row[0]), str(row[1]), str(row[2])
            now = _utc_now_iso()
            archived_scope = f"{scope_key}::archived::{session_id}"
            self._conn.execute(
                """
                UPDATE gateway_sessions
                SET scope_key = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (archived_scope, now, session_id),
            )
            new_sid = uuid.uuid4().hex
            self._conn.execute(
                """
                INSERT INTO gateway_sessions (
                    session_id, scope_key, channel, user_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (new_sid, scope_key, channel, user_id, now, now),
            )
            if mirror_root is not None:
                from sevn.gateway.bootstrap.bootstrap_state import bootstrap_completion_state

                if bootstrap_completion_state(mirror_root, agent_name="Sevn") != "complete":
                    scope_rows = self._conn.execute(
                        """
                        SELECT session_id, metadata_json FROM gateway_sessions
                        WHERE channel = ? AND user_id = ?
                        """,
                        (channel, user_id),
                    ).fetchall()
                    for sid, meta_raw in scope_rows:
                        meta: dict[str, Any]
                        if meta_raw:
                            try:
                                parsed = json.loads(str(meta_raw))
                            except json.JSONDecodeError:
                                parsed = {}
                            meta = parsed if isinstance(parsed, dict) else {}
                        else:
                            meta = {}
                        meta.pop("intro_state", None)
                        self._conn.execute(
                            """
                            UPDATE gateway_sessions
                            SET metadata_json = ?, updated_at = ?
                            WHERE session_id = ?
                            """,
                            (
                                json.dumps(meta, sort_keys=True) if meta else None,
                                now,
                                str(sid),
                            ),
                        )
            self._conn.commit()
        if mirror_root is not None:
            try:
                result = await asyncio.to_thread(
                    close_browser_for_rotate,
                    mirror_root,
                    session_id,
                )
                if not result.ok and result.code != "NOT_FOUND":
                    logger.warning(
                        "rotate_browser_close_failed session_id={} code={} message={}",
                        session_id,
                        result.code,
                        result.message,
                    )
            except Exception:
                logger.warning(
                    "rotate_browser_close_failed session_id={}",
                    session_id,
                    exc_info=True,
                )
            await asyncio.to_thread(
                mark_session_superseded,
                content_root=mirror_root,
                old_session_id=session_id,
                new_session_id=new_sid,
            )
        self._queues.pop(session_id, None)
        self._active_dispatch_task.pop(session_id, None)
        self._per_session_enqueue_locks.pop(session_id, None)
        old_worker = self._worker_tasks.pop(session_id, None)
        if old_worker is not None and not old_worker.done():
            old_worker.cancel()
        return new_sid

    async def add_message(
        self,
        session_id: str,
        *,
        role: str,
        kind: str,
        content: str,
        visible_to_llm: int,
        status: str,
        turn_id: str,
        metadata_blob: str | None = None,
    ) -> int:
        """Append one history row; returns ``gateway_messages.id``.
        Args:
            session_id (str): Owning session id.
            role (str): ``user`` / ``assistant`` / ``system`` etc.
            kind (str): Row classification (``message``, ``command``, ...).
            content (str): Stored text body (already redacted upstream).
            visible_to_llm (int): ``1`` to include in LLM history, ``0`` to hide.
            status (str): Delivery state (``sent`` / ``pending`` / ``failed``).
            turn_id (str): Turn correlation id; must be non-empty. Use
                ``SYSTEM_TURN_ID`` ('-') for rows that do not belong to a turn
                (lifecycle events, system commands). All rows produced by the
                same user turn share the same value so the placeholder/answer
                finalizer can find its target (`PROBLEMS.md` §V3b, Priority 2).
            metadata_blob (str | None): Optional JSON-encoded extras blob.
        Returns:
            int: Auto-incremented ``gateway_messages.id`` for the new row.
        Raises:
            RuntimeError: When SQLite fails to provide ``lastrowid``.
            ValueError: When ``turn_id`` is empty (caller must supply ``'-'``).
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SessionManager.add_message)
            True
        """
        if not turn_id:
            msg = (
                "SessionManager.add_message: turn_id must be non-empty; "
                "use SYSTEM_TURN_ID ('-') for non-turn rows"
            )
            raise ValueError(msg)
        async with self._lock:
            now = _utc_now_iso()
            cur = self._conn.execute(
                """
                INSERT INTO gateway_messages (
                    session_id, role, kind, content, visible_to_llm, status,
                    extras_json, created_at, turn_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    role,
                    kind,
                    content,
                    visible_to_llm,
                    status,
                    metadata_blob,
                    now,
                    turn_id,
                ),
            )
            lid = cur.lastrowid
            if lid is None:
                msg = "sqlite lastrowid unavailable after message INSERT"
                raise RuntimeError(msg)
            mid = int(lid)
            self._trim_session_messages(session_id)
            self._conn.commit()
            if self._mirror_content_root is not None and self._mirror_workspace is not None:
                row = self._conn.execute(
                    "SELECT scope_key, channel, user_id FROM gateway_sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                if row is not None:
                    await asyncio.to_thread(
                        mirror_gateway_message,
                        content_root=self._mirror_content_root,
                        workspace=self._mirror_workspace,
                        message_id=mid,
                        session_id=session_id,
                        scope_key=str(row[0]),
                        channel=str(row[1]),
                        user_id=str(row[2]),
                        role=role,
                        kind=kind,
                        content=content,
                        visible_to_llm=visible_to_llm,
                        status=status,
                        created_at=now,
                        extras_json=metadata_blob,
                        turn_id=turn_id,
                    )
            return mid

    async def set_unanswered_tail(self, session_id: str, message_id: int | None) -> None:
        """Persist ``unanswered_tail`` pointer.
        Args:
            session_id (str): Target session id.
            message_id (int | None): Latest unanswered user message id or
                ``None`` to clear the tail.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SessionManager.set_unanswered_tail)
            True
        """
        async with self._lock:
            self._conn.execute(
                """
                UPDATE gateway_sessions
                SET updated_at = ?, unanswered_tail_message_id = ?
                WHERE session_id = ?
                """,
                (_utc_now_iso(), message_id, session_id),
            )
            self._conn.commit()

    async def enqueue_dispatch(
        self,
        session_id: str,
        *,
        correlation_id: str,
        queue_mode: str,
        dispatch: DispatchFn,
        multi_hooks: MultiDispatchHooks | None = None,
        new_message_text: str = "",
        task_summary: str = "",
        in_flight_task_summary: str = "",
    ) -> None:
        """Serialize ``dispatch(session_id, correlation_id)`` per ``session_id`` (`specs/17-gateway.md` §4.3).
        ``queue_mode`` ``cancel`` aborts an in-flight dispatch task for the session,
        drains queued correlation ids, then enqueues the latest id only.
        ``queue_mode`` ``multi`` classifies busy-session arrivals (D6) into steer,
        cancel, or a concurrent level-1 tier-B spawn.
        Args:
            session_id (str): Target session id.
            correlation_id (str): Per-turn correlation id for tracing.
            queue_mode (str): ``cancel``, ``steer``, ``queue``, or ``multi`` policy.
            dispatch (DispatchFn): Stable callable invoked per turn (must be
                identical across calls).
            multi_hooks (MultiDispatchHooks | None): Classify/spawn/notify hooks for
                ``multi`` when sub-agents are wired.
            new_message_text (str): Raw inbound text for ``multi`` classification.
            task_summary (str): Short summary for the new message (queued-task ledger).
            in_flight_task_summary (str): Active L1 tier-B summary for classification.
        Raises:
            RuntimeError: When ``dispatch`` differs between calls.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SessionManager.enqueue_dispatch)
            True
        """
        if self._dispatch_fn is None:
            self._dispatch_fn = dispatch
        elif self._dispatch_fn is not dispatch:
            msg = "SessionManager.enqueue_dispatch requires a stable dispatch callable"
            raise RuntimeError(msg)
        effective_mode = queue_mode
        notice_line: str | None = None
        if queue_mode == "multi" and multi_hooks is not None:
            in_flight = self._active_dispatch_task.get(session_id)
            busy = in_flight is not None and not in_flight.done()
            if busy:
                queued = tuple(self._multi_queued_summaries.get(session_id, ()))
                label, classifier_fallback = await multi_hooks.classify_busy(
                    in_flight_task_summary,
                    queued,
                    new_message_text,
                )
                if classifier_fallback:
                    notice_line = (
                        "Queue classifier timed out — steering this message into "
                        "the in-flight task instead."
                    )
                if label == "supersede_cancel":
                    effective_mode = "cancel"
                    self._multi_queued_summaries.pop(session_id, None)
                elif label == "new_task":
                    spawn_outcome = await multi_hooks.spawn_new_task(session_id, correlation_id)
                    if spawn_outcome == MultiSpawnOutcome.SPAWNED:
                        logger.info(
                            "gateway.queue_multi_spawned session_id={} correlation_id={}",
                            session_id,
                            correlation_id,
                        )
                        return
                    effective_mode = "steer"
                    notice_line = (
                        "Sub-agent limit reached — steering this message into the "
                        "in-flight task instead."
                    )
                else:
                    effective_mode = "steer"
        q = self._queues.setdefault(session_id, asyncio.Queue())
        lock = self._enqueue_lock(session_id)
        async with lock:
            if effective_mode == "cancel":
                existing = self._active_dispatch_task.get(session_id)
                if existing is not None and not existing.done():
                    # Fire-and-forget cancel: never ``await existing`` here. This
                    # runs inside the serial channel poll loop while holding the
                    # per-session enqueue lock, so awaiting the full old-turn
                    # unwind (aborting a multi-second LLM call + ``finally``
                    # cleanup) would stall the poll loop and queue menu taps
                    # behind it. ``_session_worker`` reaps the ``CancelledError``
                    # and runs cleanup in the background (`specs/17-gateway.md`
                    # §4.3).
                    existing.cancel()
                    self._cancel_superseded_at[session_id] = time.monotonic()
                while True:
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    else:
                        q.task_done()
                self._multi_queued_summaries.pop(session_id, None)
            await q.put(correlation_id)
            if effective_mode != "cancel":
                in_flight = self._active_dispatch_task.get(session_id)
                if in_flight is not None and not in_flight.done() and q.qsize() >= 1:
                    # Steer/queue observability — TE-8 Playwright greps this
                    # via `/logs` (`specs/17-gateway.md` §2.9).
                    logger.info(
                        "gateway.queue_steer_queued session_id={} depth={}",
                        session_id,
                        q.qsize(),
                    )
                if task_summary.strip():
                    ledger = self._multi_queued_summaries.setdefault(session_id, [])
                    ledger.append(task_summary.strip())
        if notice_line and multi_hooks is not None:
            await multi_hooks.notify_operator(session_id, notice_line)
        self._ensure_worker(session_id)

    def was_cancel_superseded_recently(
        self,
        session_id: str,
        *,
        within_s: float = 5.0,
    ) -> bool:
        """Whether cancel-mode superseded an in-flight turn within ``within_s`` (P9).

        Args:
            session_id (str): Target session id.
            within_s (float): Recency window in seconds.

        Returns:
            bool: ``True`` when a replacement dispatch was enqueued recently.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(SessionManager.was_cancel_superseded_recently)
            True
        """
        ts = self._cancel_superseded_at.get(session_id)
        if ts is None:
            return False
        return (time.monotonic() - ts) <= within_s

    def consume_cancel_supersession(
        self,
        session_id: str,
        *,
        within_s: float = 5.0,
    ) -> bool:
        """Pop and return whether a recent cancel supersession occurred (P9).

        Args:
            session_id (str): Target session id.
            within_s (float): Recency window in seconds.

        Returns:
            bool: ``True`` when supersession was recent; clears the marker.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(SessionManager.consume_cancel_supersession)
            True
        """
        ts = self._cancel_superseded_at.pop(session_id, None)
        if ts is None:
            return False
        return (time.monotonic() - ts) <= within_s

    def dispatch_queue_snapshot(self, session_id: str) -> tuple[int, bool]:
        """Return ``(queued_correlation_ids, has_in_flight_dispatch)`` for tests.
        Args:
            session_id (str): Target session id.
        Returns:
            tuple[int, bool]: Queue depth and whether a dispatch task is live.
        Examples:
            >>> import inspect
            >>> inspect.isfunction(SessionManager.dispatch_queue_snapshot)
            True
        """
        q = self._queues.get(session_id)
        depth = q.qsize() if q is not None else 0
        t = self._active_dispatch_task.get(session_id)
        running = t is not None and not t.done()
        return depth, running

    def _ensure_worker(self, session_id: str) -> None:
        """Start the per-session worker task when one is not already running.
        Args:
            session_id (str): Target session id.
        Raises:
            RuntimeError: When :meth:`enqueue_dispatch` has not bound a callable.
        Examples:
            >>> import inspect
            >>> inspect.isfunction(SessionManager._ensure_worker)
            True
        """
        if self._dispatch_fn is None:
            msg = "enqueue_dispatch must run before worker start"
            raise RuntimeError(msg)
        existing = self._worker_tasks.get(session_id)
        if existing is not None and not existing.done():
            return
        dispatch = self._dispatch_fn
        self._worker_tasks[session_id] = asyncio.create_task(
            self._session_worker(session_id, dispatch),
        )

    async def _session_worker(self, session_id: str, dispatch: DispatchFn) -> None:
        """Drain the per-session queue, invoking ``dispatch`` once per item.
        Args:
            session_id (str): Owning session id.
            dispatch (DispatchFn): Per-turn callable.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SessionManager._session_worker)
            True
        """
        q = self._queues[session_id]
        try:
            while True:
                cid = await q.get()
                ledger = self._multi_queued_summaries.get(session_id)
                if ledger:
                    ledger.pop(0)
                    if not ledger:
                        self._multi_queued_summaries.pop(session_id, None)
                # Global concurrent-turn cap (plan D9/W2.4). Acquired per turn and
                # released in ``finally`` — never held across the cancel reap or
                # the request path, so it never stalls the poll loop. Acquisition
                # blocks here in the per-session worker, not in ``enqueue_dispatch``.
                await self._turn_semaphore.acquire()
                semaphore_held = True
                run_task: asyncio.Task[None] = asyncio.create_task(dispatch(session_id, cid))
                self._active_dispatch_task[session_id] = run_task
                try:
                    await run_task
                except asyncio.CancelledError:
                    if self._drain_requested:
                        with contextlib.suppress(asyncio.CancelledError):
                            if not run_task.done():
                                run_task.cancel()
                                await run_task
                        self._turn_semaphore.release()
                        semaphore_held = False
                        raise
                    with contextlib.suppress(asyncio.CancelledError):
                        if not run_task.done():
                            run_task.cancel()
                            await run_task
                except Exception:
                    logger.exception("session_dispatch_failed session_id={}", session_id)
                finally:
                    self._active_dispatch_task.pop(session_id, None)
                    if semaphore_held:
                        self._turn_semaphore.release()
                    q.task_done()
        except asyncio.CancelledError:
            return

    async def set_message_status(self, message_id: int, status: str) -> None:
        """Update assistant delivery state (``pending`` / ``sent`` / ``failed``).
        Args:
            message_id (int): Row id from :meth:`add_message`.
            status (str): New delivery status string.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SessionManager.set_message_status)
            True
        """
        async with self._lock:
            self._conn.execute(
                "UPDATE gateway_messages SET status = ? WHERE id = ?",
                (status, message_id),
            )
            self._conn.commit()

    async def clear_unanswered_tail_on_final(
        self,
        *,
        session_id: str,
        assistant_row_id: int,
    ) -> None:
        """Advance last-final pointer and clear unanswered tail.
        Args:
            session_id (str): Target session id.
            assistant_row_id (int): Row id of the final assistant message.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SessionManager.clear_unanswered_tail_on_final)
            True
        """
        async with self._lock:
            self._conn.execute(
                """
                UPDATE gateway_sessions SET
                    unanswered_tail_message_id = NULL,
                    last_final_assistant_message_id = ?,
                    updated_at = ?
                WHERE session_id = ?
                """,
                (assistant_row_id, _utc_now_iso(), session_id),
            )
            self._conn.commit()

    async def cancel_active_dispatch(self, session_id: str) -> bool:
        """Cancel an in-flight dispatch worker task for *session_id*.

        Args:
            session_id (str): Target session id.

        Returns:
            bool: ``True`` when a running task was cancelled.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SessionManager.cancel_active_dispatch)
            True
        """
        task = self._active_dispatch_task.get(session_id)
        if task is None or task.done():
            return False
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        return True

    async def drain(self, grace_period_s: float | None = None) -> None:
        """Cancel per-session workers; best-effort drain before shutdown.
        Args:
            grace_period_s (float | None): Reserved for future graceful drain;
                currently unused (cancel-only path).
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SessionManager.drain)
            True
        """
        _ = grace_period_s
        async with self._registry_lock:
            self._drain_requested = True
            try:
                for _sid, task in list(self._worker_tasks.items()):
                    if not task.done():
                        task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await task
                self._worker_tasks.clear()
                self._queues.clear()
                self._active_dispatch_task.clear()
                self._per_session_enqueue_locks.clear()
            finally:
                self._drain_requested = False


def _effective_lcm_cfg(workspace: WorkspaceConfig | None) -> LcmWorkspaceConfig:
    """Return the effective LCM config subtree.

    Args:
        workspace (WorkspaceConfig | None): Parsed workspace or ``None``.

    Returns:
        LcmWorkspaceConfig: Live subtree or defaults.

    Examples:
        >>> _effective_lcm_cfg(None).enabled is True
        True
    """
    if workspace is not None and workspace.lcm is not None:
        return workspace.lcm
    return LcmWorkspaceConfig()


def format_lcm_status_lines(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    workspace: WorkspaceConfig | None = None,
) -> list[str]:
    """Build LCM status lines for ``/status``.

    Args:
        conn (sqlite3.Connection): Open SQLite handle (LCM + gateway tables).
        session_id (str): Active gateway session id (LCM ``session_key``).
        workspace (WorkspaceConfig | None): Parsed workspace for ``lcm.enabled``.

    Returns:
        list[str]: Zero or more lines to append after session/model/voice.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> format_lcm_status_lines(c, "missing")[0].startswith("LCM:")
        True
    """
    lcm = _effective_lcm_cfg(workspace)
    enabled = bool(lcm.enabled)
    lines = [f"LCM: {'on' if enabled else 'off'}"]
    if not enabled:
        return lines
    msg_row = conn.execute(
        """
        SELECT COUNT(*)
        FROM lcm_messages m
        JOIN lcm_conversations c ON c.id = m.conversation_id
        WHERE c.session_key = ?
        """,
        (session_id,),
    ).fetchone()
    msg_count = int(msg_row[0]) if msg_row else 0
    lines.append(f"LCM messages ingested: {msg_count}")
    sum_row = conn.execute(
        """
        SELECT MAX(s.created_at)
        FROM lcm_summaries s
        JOIN lcm_conversations c ON c.id = s.conversation_id
        WHERE c.session_key = ?
          AND s.summary_kind = 'compaction'
          AND s.subsumed_by IS NULL
        """,
        (session_id,),
    ).fetchone()
    last_compact = str(sum_row[0]) if sum_row and sum_row[0] else "never"
    lines.append(f"LCM last compaction: {last_compact}")
    if lcm.autocompact_disabled:
        lines.append("LCM autocompact: disabled")
    return lines


_TTS_MODE_OVERRIDE_KEY = "tts_mode_override"
_VALID_TTS_MODES = frozenset({"off", "all", "when_asked"})


def _load_session_metadata(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    """Parse ``gateway_sessions.metadata_json`` for one session.

    Args:
        conn (sqlite3.Connection): Open SQLite handle.
        session_id (str): Target session id.

    Returns:
        dict[str, Any]: Metadata dict (empty when unset or invalid JSON).

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> _load_session_metadata(c, "missing")
        {}
    """
    row = conn.execute(
        "SELECT metadata_json FROM gateway_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row is None or not row[0]:
        return {}
    try:
        parsed = json.loads(str(row[0]))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _save_session_metadata(
    conn: sqlite3.Connection,
    session_id: str,
    metadata: dict[str, Any],
) -> None:
    """Persist ``gateway_sessions.metadata_json`` for one session.

    Args:
        conn (sqlite3.Connection): Open SQLite handle.
        session_id (str): Target session id.
        metadata (dict[str, Any]): Metadata to store (empty clears the column).

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> _ = c.execute(
        ...     "INSERT INTO gateway_sessions(session_id, scope_key, channel, user_id, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        ...     ("s", "k", "telegram", "1", "t", "t"),
        ... )
        >>> c.commit()
        >>> _save_session_metadata(c, "s", {})
    """
    blob = json.dumps(metadata, sort_keys=True) if metadata else None
    conn.execute(
        """
        UPDATE gateway_sessions
        SET metadata_json = ?, updated_at = ?
        WHERE session_id = ?
        """,
        (blob, _utc_now_iso(), session_id),
    )
    conn.commit()


def get_tts_mode_override(conn: sqlite3.Connection, session_id: str) -> str | None:
    """Return session-level TTS override when set (`specs/20-voice.md` D3).

    Args:
        conn (sqlite3.Connection): Open SQLite handle.
        session_id (str): Target session id.

    Returns:
        str | None: ``off`` / ``all`` / ``when_asked`` or ``None`` when unset.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> get_tts_mode_override(c, "s") is None
        True
    """
    raw = _load_session_metadata(conn, session_id).get(_TTS_MODE_OVERRIDE_KEY)
    if isinstance(raw, str) and raw.strip().casefold() in _VALID_TTS_MODES:
        return raw.strip().casefold()
    return None


def set_tts_mode_override(
    conn: sqlite3.Connection,
    session_id: str,
    mode: str | None,
) -> None:
    """Set or clear session TTS override (`/voice` per-chat prefs).

    Args:
        conn (sqlite3.Connection): Open SQLite handle.
        session_id (str): Target session id.
        mode (str | None): Override mode, or ``None`` to clear (``reset``).

    Raises:
        ValueError: When ``mode`` is not a valid enum.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> _ = c.execute(
        ...     "INSERT INTO gateway_sessions(session_id, scope_key, channel, user_id, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        ...     ("s", "k", "telegram", "1", "t", "t"),
        ... )
        >>> c.commit()
        >>> set_tts_mode_override(c, "s", "all")
        >>> get_tts_mode_override(c, "s")
        'all'
    """
    meta = _load_session_metadata(conn, session_id)
    if mode is None:
        meta.pop(_TTS_MODE_OVERRIDE_KEY, None)
    else:
        normalized = mode.strip().casefold()
        if normalized not in _VALID_TTS_MODES:
            msg = f"invalid tts_mode_override {mode!r}"
            raise ValueError(msg)
        meta[_TTS_MODE_OVERRIDE_KEY] = normalized
    _save_session_metadata(conn, session_id, meta)


def load_session_row(conn: sqlite3.Connection, session_id: str) -> SessionRow | None:
    """Load gateway session metadata (tests / admin).
    Args:
        conn (sqlite3.Connection): Open SQLite handle.
        session_id (str): Session id to look up.
    Returns:
        SessionRow | None: Projection dataclass or ``None`` when not found.
    Examples:
        >>> import inspect
        >>> inspect.isfunction(load_session_row)
        True
    """
    row = conn.execute(
        """
        SELECT session_id, scope_key, channel, user_id
        FROM gateway_sessions WHERE session_id = ?
        """,
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    return SessionRow(
        session_id=str(row[0]),
        scope_key=str(row[1]),
        channel=str(row[2]),
        user_id=str(row[3]),
    )


def latest_messages(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    """Return message rows for assertions (tests).
    Args:
        conn (sqlite3.Connection): Open SQLite handle.
        session_id (str): Owning session id.
    Returns:
        list[dict[str, Any]]: Ordered list of row projections suitable for
            test assertions.
    Examples:
        >>> import inspect
        >>> inspect.isfunction(latest_messages)
        True
    """
    cur = conn.execute(
        """
        SELECT id, role, kind, content, status FROM gateway_messages
        WHERE session_id = ?
        ORDER BY id ASC
        """,
        (session_id,),
    )
    out: list[dict[str, Any]] = []
    for r in cur.fetchall():
        out.append(
            {
                "id": int(r[0]),
                "role": str(r[1]),
                "kind": str(r[2]),
                "content": str(r[3]),
                "status": str(r[4]),
            },
        )
    return out


def unanswered_tail_message_id(conn: sqlite3.Connection, session_id: str) -> int | None:
    """Return ``unanswered_tail_message_id`` for assertions.
    Args:
        conn (sqlite3.Connection): Open SQLite handle.
        session_id (str): Owning session id.
    Returns:
        int | None: Pointer to the latest unanswered user row, or ``None``.
    Examples:
        >>> import inspect
        >>> inspect.isfunction(unanswered_tail_message_id)
        True
    """
    row = conn.execute(
        "SELECT unanswered_tail_message_id FROM gateway_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return int(row[0])
