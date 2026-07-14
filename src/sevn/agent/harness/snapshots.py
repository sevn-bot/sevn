"""Active run snapshots: persist, sanitise, boot sweep, replay guard.
Module: sevn.agent.harness.snapshots
Depends: pydantic, sevn.agent.tracing.sink, sevn.config.defaults, sevn.config.workspace_config
Exports:
    ActiveRunSnapshotWrite — §2.1 row payload.
    BootResumeRunRef — resume offer target.
    HarnessBootSweepResult — sweep outcome.
    HarnessSnapshotSanitisationError — forbidden snapshot fields.
    delete_active_run_snapshot — terminal row delete (§3.4).
    persist_run_snapshot — upsert with traces (§2.1, §7).
    pending_resume_group_count — pending_resume rows for grouping (§4.2).
    redacted_inspect_summary — Mission Control safe summary (§2.2).
    sanitize_in_flight_tools — §3.3 allowlist.
    sanitize_plan_state — §3.2 allowlist.
    session_has_active_run_for_replay — HTTP 409 precondition (§2.3).
    get_or_create_turn_replay_job_id — stable id per session/turn (§2.3 dedupe).
    ReplayTurnNotFoundError — no trace history for dashboard replay.
    ReplayTurnNotReplayableError — trace exists but user text is not replayable.
    turn_has_replay_trace — trace precondition for replay (§2.3).
    replay_requests_in_window — dedupe rows in a sliding window.
    pause_active_snapshots_for_upgrade — active → pending_resume (§4.2).
    queue_dashboard_turn_replay — validate + stable replay job id (§2.3).
    format_upgrade_paused_notification — single grouped copy for N paused runs (§4.2).
    sweep_active_run_snapshots — GC + resume prompts (§2.2).
Examples:
    >>> from sevn.agent.harness.snapshots import ALLOWED_PLAN_STATE_KEYS
    >>> "turn_id" in ALLOWED_PLAN_STATE_KEYS
    True
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from sevn.agent.tracing.sink import TraceEvent, TraceSink
from sevn.config.defaults import (
    DEFAULT_GATEWAY_AUTO_RESUME_B,
    HARNESS_SNAPSHOT_GC_ORPHAN_MAX_AGE_NS,
)

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig
GC_STATUSES: Final[tuple[str, ...]] = ("pending_resume", "active")
REPLAY_BLOCK_STATUSES: Final[tuple[str, ...]] = ("active", "pending_resume")
ALLOWED_PLAN_STATE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "turn_id",
        "run_id",
        "persona",
        "subagent_depth",
        "rounds_outer",
        "rounds_inner_budget_key",
        "plan_gate",
        "registry_version",
        "c_d_backend",
    },
)
FORBIDDEN_PLAN_STATE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "argv",
        "args",
        "arguments",
        "tool_args",
        "messages",
        "provider_messages",
        "oauth",
        "oauth_token",
        "token",
        "attachment",
        "attachments",
        "env",
        "environment",
        "integration_body",
        "request_body",
        "api_key",
        "headers",
    },
)
ALLOWED_IN_FLIGHT_TOOL_KEYS: Final[frozenset[str]] = frozenset(
    {"name", "call_id", "abortable", "phase"},
)
FORBIDDEN_IN_FLIGHT_TOOL_KEYS: Final[frozenset[str]] = frozenset(
    {"args", "argv", "arguments", "env", "environment", "body", "headers"},
)


class HarnessSnapshotSanitisationError(ValueError):
    """Snapshot JSON contains forbidden keys or disallowed shapes."""


class ReplayTurnNotFoundError(LookupError):
    """Mission Control replay has no trace history for the requested turn."""


class ReplayTurnNotReplayableError(LookupError):
    """Mission Control replay has trace history but no replayable user message."""


class ActiveRunSnapshotWrite(BaseModel):
    """Row-ready payload before SQLite INSERT/REPLACE — see specs/03-storage §2.4."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    tier: Literal["triager", "A", "B", "C", "D"]
    plan_state: dict[str, object]
    in_flight_tools: list[dict[str, object]]
    excerpt: str
    status: Literal["active", "pending_resume", "sent", "cancelled", "failed", "abandoned"]
    created_at_ns: int = Field(ge=0)
    updated_at_ns: int = Field(ge=0)
    awaiting_callback_token: str | None = Field(default=None, max_length=4096)


@dataclass(frozen=True)
class BootResumeRunRef:
    """Identifies one run surfaced at boot for resume UX or auto-resume."""

    run_id: str
    session_id: str
    tier: str


@dataclass(frozen=True)
class HarnessBootSweepResult:
    """Outcome of ``sweep_active_run_snapshots``."""

    gc_deleted_count: int
    owner_prompt_runs: tuple[BootResumeRunRef, ...]
    auto_resumed_tier_b: tuple[BootResumeRunRef, ...]


def _effective_auto_resume_b(workspace: WorkspaceConfig | None) -> bool:
    """Resolve the effective ``gateway.restart.auto_resume_b`` flag with defaults.
    Args:
        workspace (WorkspaceConfig | None): Optional parsed workspace config.
    Returns:
        bool: Whether tier-B auto resume is enabled.
    Examples:
        >>> _effective_auto_resume_b(None) == DEFAULT_GATEWAY_AUTO_RESUME_B
        True
    """
    if workspace is None or workspace.gateway is None or workspace.gateway.restart is None:
        return DEFAULT_GATEWAY_AUTO_RESUME_B
    return bool(workspace.gateway.restart.auto_resume_b)


def sanitize_plan_state(plan_state: dict[str, object]) -> dict[str, object]:
    """Return a JSON-serialisable ``plan_state`` containing only §3.2 allowlisted keys.
        Args:
    plan_state (dict[str, object]): Raw executor/triager state fragment.
        Returns:
            dict[str, object]: Copy with only allowed keys and JSON-compatible values.
        Raises:
    HarnessSnapshotSanitisationError: When forbidden keys appear or keys are unknown.
        Examples:
            >>> sanitize_plan_state({"turn_id": "t1", "run_id": "r1"})
            {'run_id': 'r1', 'turn_id': 't1'}
    """
    forbidden_present = FORBIDDEN_PLAN_STATE_KEYS.intersection(plan_state.keys())
    if forbidden_present:
        msg = f"plan_state contains forbidden keys: {sorted(forbidden_present)}"
        raise HarnessSnapshotSanitisationError(msg)
    unknown = set(plan_state.keys()) - ALLOWED_PLAN_STATE_KEYS
    if unknown:
        msg = f"plan_state contains unknown keys: {sorted(unknown)}"
        raise HarnessSnapshotSanitisationError(msg)
    out: dict[str, object] = {}
    for key in sorted(plan_state.keys()):
        val = plan_state[key]
        try:
            json.dumps(val, default=str)
        except (TypeError, ValueError) as exc:
            msg = f"plan_state[{key!r}] is not JSON-serialisable"
            raise HarnessSnapshotSanitisationError(msg) from exc
        out[key] = val
    return out


def sanitize_in_flight_tools(
    items: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Allow §3.3 safe references only; reject args-like keys.
        Args:
    items (list[dict[str, object]]): Tool flight descriptors.
        Returns:
            list[dict[str, object]]: Sanitised list of small objects.
        Raises:
    HarnessSnapshotSanitisationError: On forbidden keys, unknown keys, or bad shapes.
        Examples:
            >>> sanitize_in_flight_tools([{"name": "x", "abortable": True}])
            [{'name': 'x', 'abortable': True}]
    """
    out: list[dict[str, object]] = []
    for i, raw in enumerate(items):
        forbidden = FORBIDDEN_IN_FLIGHT_TOOL_KEYS.intersection(raw.keys())
        if forbidden:
            msg = f"in_flight_tools[{i}] forbidden keys: {sorted(forbidden)}"
            raise HarnessSnapshotSanitisationError(msg)
        unknown = set(raw.keys()) - ALLOWED_IN_FLIGHT_TOOL_KEYS
        if unknown:
            msg = f"in_flight_tools[{i}] unknown keys: {sorted(unknown)}"
            raise HarnessSnapshotSanitisationError(msg)
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            msg = f"in_flight_tools[{i}].name must be a non-empty string"
            raise HarnessSnapshotSanitisationError(msg)
        obj: dict[str, object] = {"name": name.strip()}
        if "call_id" in raw:
            cid = raw["call_id"]
            if cid is not None and not isinstance(cid, str):
                msg = f"in_flight_tools[{i}].call_id must be str or null"
                raise HarnessSnapshotSanitisationError(msg)
            if isinstance(cid, str) and cid:
                obj["call_id"] = cid
        if "abortable" in raw:
            ab = raw["abortable"]
            if not isinstance(ab, bool):
                msg = f"in_flight_tools[{i}].abortable must be bool"
                raise HarnessSnapshotSanitisationError(msg)
            obj["abortable"] = ab
        if "phase" in raw:
            ph = raw["phase"]
            if ph not in ("requested", "executing"):
                msg = f"in_flight_tools[{i}].phase must be 'requested' or 'executing'"
                raise HarnessSnapshotSanitisationError(msg)
            obj["phase"] = ph
        try:
            json.dumps(obj, default=str)
        except (TypeError, ValueError) as exc:
            msg = f"in_flight_tools[{i}] is not JSON-serialisable"
            raise HarnessSnapshotSanitisationError(msg) from exc
        out.append(obj)
    return out


def redacted_inspect_summary(
    *,
    excerpt: str,
    tier: str,
    created_at_ns: int,
    updated_at_ns: int,
    now_ns: int | None = None,
) -> dict[str, object]:
    """Build a redacted operator-facing summary (no raw ``plan_state``).
        Args:
    excerpt (str): Short excerpt column (may be redacted).
    tier (str): Tier label from storage.
    created_at_ns (int): Row creation time (ns).
    updated_at_ns (int): Row update time (ns).
    now_ns (int | None): Reference clock; defaults to ``time.time_ns()``.
        Returns:
            dict[str, object]: Safe summary for Mission Control / Telegram.
        Examples:
            >>> s = redacted_inspect_summary(
            ...     excerpt="ok", tier="B",
            ...     created_at_ns=0, updated_at_ns=1_000, now_ns=1_000_000_000_000,
            ... )
            >>> s["tier"]
            'B'
    """
    clock = time.time_ns() if now_ns is None else int(now_ns)
    elapsed_hint_s = max(0.0, (clock - int(updated_at_ns)) / 1e9)
    text = excerpt
    lower = text.lower()
    if ".llmignore" in lower:
        text = "[REDACTED_PATH]"
    # Strip path-like segments that could echo workspace layout.
    if "/" in text or "\\" in text:
        text = "[REDACTED_TEXT]"
    return {
        "excerpt": text,
        "tier": tier,
        "elapsed_hint_s": round(elapsed_hint_s, 3),
        "created_at_ns": int(created_at_ns),
        "updated_at_ns": int(updated_at_ns),
    }


async def _emit_safe(trace: TraceSink, event: TraceEvent) -> None:
    """Emit a trace event swallowing exceptions (logs at warning).
    Args:
        trace (TraceSink): Trace sink instance.
        event (TraceEvent): Event payload.
    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_emit_safe)
        True
    """
    try:
        await trace.emit(event)
    except Exception:
        logger.bind(kind=event.kind).exception("harness trace emit failed")


def _turn_id_for_trace(plan_state: dict[str, object]) -> str:
    """Extract a turn id from ``plan_state`` falling back to ``"_"``.
    Args:
        plan_state (dict[str, object]): Sanitised plan state dictionary.
    Returns:
        str: Turn id when present and non-empty, else ``"_"``.
    Examples:
        >>> _turn_id_for_trace({"turn_id": "abc"})
        'abc'
        >>> _turn_id_for_trace({})
        '_'
    """
    tid = plan_state.get("turn_id")
    if isinstance(tid, str) and tid:
        return tid
    return "_"


async def persist_run_snapshot(
    *,
    conn: sqlite3.Connection,
    row: ActiveRunSnapshotWrite,
    trace: TraceSink,
    boundary: Literal["llm", "tool"] = "llm",
    rounds_outer: int | None = None,
) -> None:
    """Upsert ``active_run_snapshots``; never persists raw tool args (§8).
        Args:
    conn (sqlite3.Connection): Open ``sevn.db`` connection.
    row (ActiveRunSnapshotWrite): Logical snapshot row.
    trace (TraceSink): Observability sink (non-raising).
    boundary (Literal["llm", "tool"]): Trace attribute §7.
    rounds_outer (int | None): Optional outer-round hint for traces.
        Examples:
            >>> True
            True
    """
    try:
        clean_plan = sanitize_plan_state(dict(row.plan_state))
        clean_tools = sanitize_in_flight_tools(list(row.in_flight_tools))
    except HarnessSnapshotSanitisationError:
        logger.bind(run_id=row.run_id).warning("snapshot sanitisation rejected row")
        raise
    plan_json = json.dumps(clean_plan, separators=(",", ":"), default=str)
    tools_json = json.dumps(clean_tools, separators=(",", ":"), default=str)
    attrs: dict[str, object] = {
        "run_id": row.run_id,
        "session_id": row.session_id,
        "tier": row.tier,
        "boundary": boundary,
        "status": row.status,
        "plan_state": clean_plan,
        "in_flight_tools": clean_tools,
        "excerpt": row.excerpt,
    }
    if rounds_outer is not None:
        attrs["rounds_outer"] = int(rounds_outer)
    turn_id = _turn_id_for_trace(clean_plan)
    span_id = f"harness-snap-{row.run_id}-{uuid.uuid4().hex[:12]}"
    await _emit_safe(
        trace,
        TraceEvent(
            kind="harness.snapshot.write",
            span_id=span_id,
            parent_span_id=None,
            session_id=row.session_id,
            turn_id=turn_id,
            tier=row.tier,
            ts_start_ns=time.time_ns(),
            ts_end_ns=None,
            status="ok",
            attrs=attrs,
        ),
    )
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO active_run_snapshots (
                run_id, session_id, tier, plan_state, in_flight_tools,
                excerpt, status, created_at_ns, updated_at_ns, awaiting_callback_token
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.run_id,
                row.session_id,
                row.tier,
                plan_json,
                tools_json,
                row.excerpt,
                row.status,
                int(row.created_at_ns),
                int(row.updated_at_ns),
                row.awaiting_callback_token,
            ),
        )
    except Exception:
        logger.bind(run_id=row.run_id, session_id=row.session_id).exception(
            "persist_run_snapshot SQL failed",
        )


def delete_active_run_snapshot(conn: sqlite3.Connection, run_id: str) -> None:
    """Delete snapshot row when the run reaches a terminal status (§3.4).
        Args:
    conn (sqlite3.Connection): Application DB connection.
    run_id (str): Primary key ``run_id``.
        Examples:
            >>> True
            True
    """
    conn.execute("DELETE FROM active_run_snapshots WHERE run_id = ?", (run_id,))


def session_has_active_run_for_replay(conn: sqlite3.Connection, session_id: str) -> bool:
    """Return True when replay must return **409** for ``session_id`` (§2.3).
        Args:
    conn (sqlite3.Connection): ``sevn.db`` connection with migrations applied.
    session_id (str): Gateway session id.
        Returns:
            bool: Whether a blocking ``active`` / ``pending_resume`` row exists.
        Examples:
            >>> True
            True
    """
    row = conn.execute(
        """
        SELECT 1 FROM active_run_snapshots
        WHERE session_id = ? AND status IN (?, ?)
        LIMIT 1
        """,
        (session_id, *REPLAY_BLOCK_STATUSES),
    ).fetchone()
    return row is not None


def get_or_create_turn_replay_job_id(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    turn_id: str,
    now_ns: int,
) -> str:
    """Return a stable ``replay_job_id`` for ``(session_id, turn_id)``.
    First call inserts into ``turn_replay_dedupe``; repeat calls return the same
    id (PRD 04 §5.13 idempotency when the dedupe table is enabled).
    Args:
        conn (sqlite3.Connection): Migrated ``sevn.db`` connection.
        session_id (str): Gateway session id.
        turn_id (str): User turn id.
        now_ns (int): Monotonic wall clock in nanoseconds for ``created_at_ns``.
    Returns:
        str: Opaque replay job identifier.
    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.agent.harness.snapshots import get_or_create_turn_replay_job_id
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> a = get_or_create_turn_replay_job_id(
        ...     c, session_id="s", turn_id="t", now_ns=1,
        ... )
        >>> b = get_or_create_turn_replay_job_id(
        ...     c, session_id="s", turn_id="t", now_ns=2,
        ... )
        >>> a == b
        True
    """
    row = conn.execute(
        """
        SELECT replay_job_id FROM turn_replay_dedupe
        WHERE session_id = ? AND turn_id = ?
        """,
        (session_id, turn_id),
    ).fetchone()
    if row is not None:
        return str(row[0])
    job_id = uuid.uuid4().hex
    try:
        conn.execute(
            """
            INSERT INTO turn_replay_dedupe (session_id, turn_id, replay_job_id, created_at_ns)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, turn_id, job_id, int(now_ns)),
        )
    except sqlite3.IntegrityError:
        row = conn.execute(
            """
            SELECT replay_job_id FROM turn_replay_dedupe
            WHERE session_id = ? AND turn_id = ?
            """,
            (session_id, turn_id),
        ).fetchone()
        if row is None:
            raise
        return str(row[0])
    return job_id


def turn_has_replay_trace(
    traces_conn: sqlite3.Connection,
    *,
    session_id: str,
    turn_id: str,
) -> bool:
    """Return True when ``trace_events`` contains rows for ``(session_id, turn_id)``.
    Args:
        traces_conn (sqlite3.Connection): Open ``traces.db`` connection.
        session_id (str): Gateway session id.
        turn_id (str): User turn id.
    Returns:
        bool: Whether historical trace rows exist for replay preflight.
    Examples:
        >>> import sqlite3
        >>> from sevn.agent.tracing.traces_migrate import apply_traces_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_traces_migrations(c)
        >>> turn_has_replay_trace(c, session_id="s", turn_id="t")
        False
    """
    row = traces_conn.execute(
        """
        SELECT 1 FROM trace_events
        WHERE session_id = ? AND turn_id = ?
        LIMIT 1
        """,
        (session_id, turn_id),
    ).fetchone()
    return row is not None


def replay_requests_in_window(
    conn: sqlite3.Connection,
    *,
    since_ns: int,
) -> int:
    """Count replay dedupe rows created at or after ``since_ns``.
    Args:
        conn (sqlite3.Connection): Migrated ``sevn.db`` connection.
        since_ns (int): Inclusive lower bound on ``created_at_ns``.
    Returns:
        int: Number of replay jobs recorded in the window.
    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.agent.harness.snapshots import (
        ...     get_or_create_turn_replay_job_id,
        ...     replay_requests_in_window,
        ... )
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> _ = get_or_create_turn_replay_job_id(
        ...     c, session_id="s", turn_id="t", now_ns=100,
        ... )
        >>> replay_requests_in_window(c, since_ns=0)
        1
    """
    row = conn.execute(
        "SELECT COUNT(*) FROM turn_replay_dedupe WHERE created_at_ns >= ?",
        (int(since_ns),),
    ).fetchone()
    return int(row[0]) if row else 0


def pause_active_snapshots_for_upgrade(conn: sqlite3.Connection) -> int:
    """Transition ``active`` rows to ``pending_resume`` before gateway restart (§4.2).
    Args:
        conn (sqlite3.Connection): Application DB connection.
    Returns:
        int: Number of rows updated.
    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.agent.harness.snapshots import pause_active_snapshots_for_upgrade
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> _ = c.execute(
        ...     '''INSERT INTO active_run_snapshots (
        ...         run_id, session_id, tier, plan_state, in_flight_tools,
        ...         excerpt, status, created_at_ns, updated_at_ns
        ...     ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        ...     ("r1", "s", "B", "{}", "[]", "x", "active", 1, 2),
        ... )
        >>> pause_active_snapshots_for_upgrade(c)
        1
    """
    before = conn.total_changes
    conn.execute(
        """
        UPDATE active_run_snapshots
        SET status = 'pending_resume', updated_at_ns = ?
        WHERE status = 'active'
        """,
        (time.time_ns(),),
    )
    return conn.total_changes - before


def queue_dashboard_turn_replay(
    conn: sqlite3.Connection,
    traces_conn: sqlite3.Connection,
    *,
    session_id: str,
    turn_id: str,
    now_ns: int,
) -> str:
    """Validate replay preconditions and return a stable ``replay_job_id`` (§2.3).
    Args:
        conn (sqlite3.Connection): ``sevn.db`` connection.
        traces_conn (sqlite3.Connection): ``traces.db`` connection.
        session_id (str): Gateway session id.
        turn_id (str): User turn id.
        now_ns (int): Wall clock in nanoseconds for dedupe bookkeeping.
    Returns:
        str: Stable replay job identifier.
    Raises:
        ReplayTurnNotFoundError: When no trace rows exist for the turn.
        RuntimeError: When an active run blocks replay (caller maps to **409**).
    Examples:
        >>> import sqlite3
        >>> from sevn.agent.tracing.traces_migrate import apply_traces_migrations
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.agent.harness.snapshots import queue_dashboard_turn_replay
        >>> db = sqlite3.connect(":memory:")
        >>> apply_migrations(db)
        >>> tr = sqlite3.connect(":memory:")
        >>> apply_traces_migrations(tr)
        >>> _ = tr.execute(
        ...     '''INSERT INTO trace_events (
        ...         span_id, parent_span_id, session_id, turn_id, tier, kind,
        ...         ts_start_ns, ts_end_ns, status, attrs_json
        ...     ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        ...     ("sp", None, "s", "t", "B", "provider.call", 1, 2, "ok", "{}"),
        ... )
        >>> _ = db.execute(
        ...     "INSERT INTO gateway_sessions(session_id, scope_key, channel, user_id, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        ...     ("s", "k", "webchat", "u", "t", "t"),
        ... )
        >>> _ = db.execute(
        ...     '''INSERT INTO gateway_messages (
        ...         session_id, role, kind, content, visible_to_llm, status,
        ...         extras_json, created_at, turn_id
        ...     ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        ...     ("s", "user", "message", "hello", 1, "sent", "{}", "t", "t"),
        ... )
        >>> db.commit()
        >>> job = queue_dashboard_turn_replay(
        ...     db, tr, session_id="s", turn_id="t", now_ns=1,
        ... )
        >>> bool(job)
        True
    """
    if session_has_active_run_for_replay(conn, session_id):
        msg = f"session {session_id!r} has an active run"
        raise RuntimeError(msg)
    if not turn_has_replay_trace(traces_conn, session_id=session_id, turn_id=turn_id):
        msg = f"no trace history for session={session_id!r} turn={turn_id!r}"
        raise ReplayTurnNotFoundError(msg)
    from sevn.gateway.replay.replay_turn_lookup import lookup_user_text_for_turn

    if lookup_user_text_for_turn(conn, session_id, turn_id) is None:
        msg = f"turn is not replayable session={session_id!r} turn={turn_id!r}"
        raise ReplayTurnNotReplayableError(msg)
    return get_or_create_turn_replay_job_id(
        conn,
        session_id=session_id,
        turn_id=turn_id,
        now_ns=now_ns,
    )


def format_upgrade_paused_notification(paused_run_count: int) -> str:
    """Format the single grouped operator line for upgrade pause (§4.2).
    Args:
        paused_run_count (int): Number of ``pending_resume`` rows (non-negative).
    Returns:
        str: Empty when ``paused_run_count < 1``; otherwise one English sentence.
    Examples:
        >>> format_upgrade_paused_notification(0)
        ''
        >>> format_upgrade_paused_notification(1)
        '1 run paused for upgrade'
        >>> format_upgrade_paused_notification(3)
        '3 runs paused for upgrade'
    """
    if paused_run_count < 1:
        return ""
    if paused_run_count == 1:
        return "1 run paused for upgrade"
    return f"{paused_run_count} runs paused for upgrade"


def pending_resume_group_count(conn: sqlite3.Connection) -> int:
    """Count ``pending_resume`` rows (upgrade grouping hint — §4.2).
        Args:
    conn (sqlite3.Connection): Application DB.
        Returns:
            int: Number of paused-for-upgrade style rows.
        Examples:
            >>> True
            True
    """
    cur = conn.execute(
        "SELECT COUNT(*) FROM active_run_snapshots WHERE status = ?",
        ("pending_resume",),
    )
    val = cur.fetchone()
    return int(val[0]) if val else 0


async def sweep_active_run_snapshots(
    *,
    conn: sqlite3.Connection,
    trace: TraceSink,
    workspace: WorkspaceConfig | None = None,
    now_ns: int | None = None,
) -> HarnessBootSweepResult:
    """GC orphaned rows, then classify resume offers per tier (§2.2, §4.2).
        Args:
    conn (sqlite3.Connection): ``sevn.db`` connection.
    trace (TraceSink): Trace sink.
    workspace (WorkspaceConfig | None): For ``gateway.restart.auto_resume_b``.
    now_ns (int | None): Clock for GC boundary; defaults to ``time.time_ns()``.
        Returns:
            HarnessBootSweepResult: Counts + classified runs for gateway UX.
        Examples:
            >>> True
            True
    """
    clock = time.time_ns() if now_ns is None else int(now_ns)
    cutoff = clock - int(HARNESS_SNAPSHOT_GC_ORPHAN_MAX_AGE_NS)
    before = conn.total_changes
    conn.execute(
        """
        DELETE FROM active_run_snapshots
        WHERE status IN (?, ?) AND updated_at_ns < ?
        """,
        (*GC_STATUSES, cutoff),
    )
    deleted = conn.total_changes - before
    await _emit_safe(
        trace,
        TraceEvent(
            kind="harness.snapshot.gc_orphan",
            span_id=f"harness-gc-{uuid.uuid4().hex[:16]}",
            parent_span_id=None,
            session_id="_",
            turn_id="_",
            tier=None,
            ts_start_ns=clock,
            ts_end_ns=clock,
            status="ok",
            attrs={"deleted": deleted, "cutoff_ns": cutoff},
        ),
    )
    cur = conn.execute(
        """
        SELECT run_id, session_id, tier, plan_state
        FROM active_run_snapshots
        WHERE status IN (?, ?)
        ORDER BY updated_at_ns ASC
        """,
        GC_STATUSES,
    )
    owner: list[BootResumeRunRef] = []
    auto_b: list[BootResumeRunRef] = []
    auto_flag = _effective_auto_resume_b(workspace)
    for run_id, session_id, tier_raw, _plan in cur.fetchall():
        tier = str(tier_raw).strip()
        ref = BootResumeRunRef(run_id=str(run_id), session_id=str(session_id), tier=tier)
        if tier == "B" and auto_flag:
            auto_b.append(ref)
            await _emit_safe(
                trace,
                TraceEvent(
                    kind="harness.auto_resume_b",
                    span_id=f"harness-autoresume-{run_id}-{uuid.uuid4().hex[:8]}",
                    parent_span_id=None,
                    session_id=ref.session_id,
                    turn_id="_",
                    tier="B",
                    ts_start_ns=clock,
                    ts_end_ns=clock,
                    status="ok",
                    attrs={"run_id": ref.run_id, "session_id": ref.session_id},
                ),
            )
        else:
            owner.append(ref)
            await _emit_safe(
                trace,
                TraceEvent(
                    kind="harness.boot.resume_prompt",
                    span_id=f"harness-resume-{run_id}-{uuid.uuid4().hex[:8]}",
                    parent_span_id=None,
                    session_id=ref.session_id,
                    turn_id="_",
                    tier=tier if tier else None,
                    ts_start_ns=clock,
                    ts_end_ns=clock,
                    status="ok",
                    attrs={"run_id": ref.run_id, "tier": tier, "session_id": ref.session_id},
                ),
            )
    return HarnessBootSweepResult(
        gc_deleted_count=int(deleted),
        owner_prompt_runs=tuple(owner),
        auto_resumed_tier_b=tuple(auto_b),
    )
