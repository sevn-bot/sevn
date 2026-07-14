"""Dashboard session REST router.

Module: sevn.ui.dashboard.api.sessions
Depends: csv, io, fastapi, sevn.ui.dashboard.query

Exports:
    sessions — session list endpoint.
    session_api_calls — provider-call list endpoint.
    session_api_calls_csv — provider-call CSV export endpoint.
    replay_turn — harness-backed turn replay endpoint.
"""

from __future__ import annotations

import csv
import io
import sqlite3
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

import sevn.gateway.replay.replay_worker_hooks  # noqa: F401 — Batch D lane #5 boot + post-turn hooks
from sevn.agent.harness.snapshots import (
    ReplayTurnNotFoundError,
    ReplayTurnNotReplayableError,
    queue_dashboard_turn_replay,
    replay_requests_in_window,
    session_has_active_run_for_replay,
)
from sevn.agent.tracing.sink_factory import trace_redaction_policy_for
from sevn.config.defaults import DEFAULT_DASHBOARD_TRACE_LIMIT_MAX, DEFAULT_REPLAY_MAX_PER_DAY
from sevn.storage.paths import traces_sqlite_path
from sevn.ui.dashboard.api.deps import require_dashboard_csrf, require_dashboard_owner
from sevn.ui.dashboard.query import (
    clamp_limit,
    ensure_trace_connection,
    list_gateway_sessions,
    list_provider_calls,
)
from sevn.ui.dashboard.services.auth import DashboardClaims

router = APIRouter(prefix="/sessions", tags=["dashboard-sessions"])


@router.get("")
async def sessions(
    request: Request,
    limit: int | None = None,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """List gateway sessions with active-run indicators.

    Args:
        request (Request): FastAPI request with app state.
        limit (int | None): Optional page size.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Cursor page.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(sessions)
        True
    """

    conn: sqlite3.Connection = request.app.state.sqlite_conn
    return list_gateway_sessions(conn, limit=clamp_limit(limit, default=50, maximum=500))


@router.get("/{session_id}/api-calls")
async def session_api_calls(
    session_id: str,
    request: Request,
    cursor: str | None = None,
    limit: int | None = None,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """List ``provider.call`` trace rows for one session.

    Args:
        session_id (str): Session id path parameter.
        request (Request): FastAPI request with app state.
        cursor (str | None): Optional trace cursor.
        limit (int | None): Optional page size.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Cursor page.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(session_api_calls)
        True
    """

    ly = request.app.state.layout
    policy = trace_redaction_policy_for(request.app.state.workspace)
    conn = ensure_trace_connection(traces_sqlite_path(ly.dot_sevn))
    try:
        return list_provider_calls(
            conn,
            session_id=session_id,
            limit=clamp_limit(limit, default=50, maximum=DEFAULT_DASHBOARD_TRACE_LIMIT_MAX),
            policy=policy,
            cursor=cursor,
        )
    finally:
        conn.close()


@router.get("/{session_id}/api-calls/export.csv")
async def session_api_calls_csv(
    session_id: str,
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> StreamingResponse:
    """Export provider-call rows as CSV.

    Args:
        session_id (str): Session id path parameter.
        request (Request): FastAPI request with app state.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        StreamingResponse: CSV response with content-disposition.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(session_api_calls_csv)
        True
    """

    ly = request.app.state.layout
    policy = trace_redaction_policy_for(request.app.state.workspace)
    conn = ensure_trace_connection(traces_sqlite_path(ly.dot_sevn))
    try:
        page = list_provider_calls(
            conn,
            session_id=session_id,
            limit=DEFAULT_DASHBOARD_TRACE_LIMIT_MAX,
            policy=policy,
        )
    finally:
        conn.close()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "ts_start_ns",
            "span_id",
            "parent_span_id",
            "session_id",
            "turn_id",
            "tier",
            "kind",
            "status",
        ],
    )
    raw_items = page["items"]
    items_iter: list[object] = raw_items if isinstance(raw_items, list) else []
    for item in items_iter:
        if isinstance(item, dict):
            writer.writerow(
                [
                    item.get("ts_start_ns"),
                    item.get("span_id"),
                    item.get("parent_span_id"),
                    item.get("session_id"),
                    item.get("turn_id"),
                    item.get("tier"),
                    item.get("kind"),
                    item.get("status"),
                ],
            )
    response = StreamingResponse(iter([buf.getvalue()]), media_type="text/csv")
    response.headers["Content-Disposition"] = (
        f'attachment; filename="session-{session_id}-api-calls.csv"'
    )
    return response


@router.post("/{session_id}/turns/{turn_id}/replay")
async def replay_turn(
    session_id: str,
    turn_id: str,
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Queue a dashboard replay job unless an active run blocks it.

    Args:
        session_id (str): Session id path parameter.
        turn_id (str): Turn id path parameter.
        request (Request): FastAPI request with app state.
        _claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        JSONResponse: ``409`` for active sessions or a stable replay job id.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(replay_turn)
        True
    """

    ws = request.app.state.workspace
    max_per_day = DEFAULT_REPLAY_MAX_PER_DAY
    if ws is not None and ws.replay is not None:
        max_per_day = int(ws.replay.max_per_day)

    now_ns = time.time_ns()
    window_ns = 24 * 60 * 60 * 1_000_000_000
    conn: sqlite3.Connection = request.app.state.sqlite_conn
    if replay_requests_in_window(conn, since_ns=now_ns - window_ns) >= max_per_day:
        return JSONResponse(
            status_code=429,
            content={
                "error": {
                    "code": "replay_daily_cap",
                    "message": "turn replay daily cap exceeded",
                    "details": {"max_per_day": max_per_day},
                },
            },
            headers={"Retry-After": "86400"},
        )

    if session_has_active_run_for_replay(conn, session_id):
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": "active_run_conflict",
                    "message": "session has an active run; replay is blocked",
                    "details": {"session_id": session_id, "turn_id": turn_id},
                },
            },
        )

    ly = request.app.state.layout
    traces_conn = ensure_trace_connection(traces_sqlite_path(ly.dot_sevn))
    try:
        try:
            replay_job_id = queue_dashboard_turn_replay(
                conn,
                traces_conn,
                session_id=session_id,
                turn_id=turn_id,
                now_ns=now_ns,
            )
        except ReplayTurnNotFoundError:
            return JSONResponse(
                status_code=404,
                content={
                    "error": {
                        "code": "turn_snapshot_not_found",
                        "message": "no trace history for this turn",
                        "details": {"session_id": session_id, "turn_id": turn_id},
                    },
                },
            )
        except ReplayTurnNotReplayableError:
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "code": "turn_not_replayable",
                        "message": "turn has no replayable user message",
                        "details": {"session_id": session_id, "turn_id": turn_id},
                    },
                },
            )
        except RuntimeError:
            return JSONResponse(
                status_code=409,
                content={
                    "error": {
                        "code": "active_run_conflict",
                        "message": "session has an active run; replay is blocked",
                        "details": {"session_id": session_id, "turn_id": turn_id},
                    },
                },
            )
    finally:
        traces_conn.close()

    conn.commit()
    worker = getattr(request.app.state, "replay_worker", None)
    if worker is not None:
        worker.schedule(
            replay_job_id,
            session_id=session_id,
            turn_id=turn_id,
        )
    return JSONResponse(
        status_code=202,
        content={
            "replay_job_id": replay_job_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "status": "queued",
        },
    )
