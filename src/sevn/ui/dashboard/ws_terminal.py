"""Sandbox-confined Mission Control web terminal WebSocket (MC W8).

Module: sevn.ui.dashboard.ws_terminal
Depends: asyncio, base64, binascii, json, time, fastapi, sevn.ui.dashboard.services.sandbox_terminal

Exports:
    dashboard_terminal_ws_endpoint — ``/ws/dashboard/terminal`` handler.
    active_terminal_sessions — test hook: count of live PTY sessions.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import json
import time
import uuid
from typing import Any

from fastapi import WebSocket  # noqa: TC002
from starlette.websockets import WebSocketDisconnect

from sevn.agent.tracing.sink import SYSTEM_TURN_ID, TraceEvent, TraceSink
from sevn.config.workspace_config import WorkspaceConfig
from sevn.ui.dashboard.services.auth import (
    DASHBOARD_CSRF_COOKIE_NAME,
    DashboardAuthService,
    local_open_effective,
)
from sevn.ui.dashboard.services.sandbox_terminal import (
    SandboxTerminalError,
    SandboxTerminalSession,
    create_sandbox_terminal_session,
)
from sevn.ui.dashboard.services.terminal_registry import terminal_session_registry
from sevn.workspace.layout import WorkspaceLayout

_active: dict[str, SandboxTerminalSession] = {}


def active_terminal_sessions() -> int:
    """Return the number of live dashboard terminal PTY sessions (tests).

    Returns:
        int: Active session count.

    Examples:
        >>> isinstance(active_terminal_sessions(), int)
        True
    """
    return len(_active)


async def _emit_terminal_audit(
    websocket: WebSocket,
    *,
    kind: str,
    session_id: str,
    driver: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """Persist a mission terminal audit trace row.

    Args:
        websocket (WebSocket): Connection carrying app state.
        kind (str): Trace kind such as ``mission.terminal.session_start``.
        session_id (str): Terminal session correlation id.
        driver (str): Sandbox driver slug.
        extra (dict[str, Any] | None): Additional safe attrs.

    Returns:
        None: Side-effect only.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_emit_terminal_audit)
        True
    """
    sink: TraceSink | None = getattr(websocket.app.state, "gateway_trace", None)
    if sink is None:
        return
    attrs: dict[str, Any] = {"session_id": session_id, "driver": driver}
    if extra:
        attrs.update(extra)
    now = time.time_ns()
    await sink.emit(
        TraceEvent(
            kind=kind,
            span_id=str(uuid.uuid4()),
            parent_span_id=None,
            session_id="dashboard",
            turn_id=SYSTEM_TURN_ID,
            tier=None,
            ts_start_ns=now,
            ts_end_ns=now,
            status="ok",
            attrs=attrs,
        ),
    )


async def _pty_reader(
    websocket: WebSocket,
    session: SandboxTerminalSession,
) -> None:
    """Forward PTY stdout to the browser as base64 JSON frames.

    Args:
        websocket (WebSocket): Open terminal WebSocket.
        session (SandboxTerminalSession): Active sandbox PTY session.

    Returns:
        None: Loops until disconnect, timeout, or PTY close.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_pty_reader)
        True
    """
    while not session.expired:
        chunk = await session.read_stdout()
        if chunk:
            payload = base64.b64encode(chunk).decode("ascii")
            await websocket.send_text(
                json.dumps({"type": "stdout", "data": payload}, ensure_ascii=False),
            )
        else:
            await asyncio.sleep(0.05)
    await websocket.send_text(
        json.dumps(
            {"type": "close", "reason": "session_timeout"},
            ensure_ascii=False,
        ),
    )


async def _pty_writer(
    websocket: WebSocket,
    session: SandboxTerminalSession,
) -> None:
    """Read browser stdin frames and write to the sandbox PTY.

    Args:
        websocket (WebSocket): Open terminal WebSocket.
        session (SandboxTerminalSession): Active sandbox PTY session.

    Returns:
        None: Loops until disconnect or timeout.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_pty_writer)
        True
    """
    while not session.expired:
        raw = await websocket.receive_text()
        try:
            frame = json.loads(raw)
        except (TypeError, ValueError):
            await websocket.send_text(
                json.dumps(
                    {"type": "error", "code": "invalid_json", "message": "frame must be JSON"},
                    ensure_ascii=False,
                ),
            )
            continue
        if not isinstance(frame, dict):
            continue
        if frame.get("type") == "ping":
            await websocket.send_text(json.dumps({"type": "pong"}, ensure_ascii=False))
            continue
        if frame.get("type") != "stdin":
            continue
        data_b64 = frame.get("data")
        if not isinstance(data_b64, str):
            continue
        try:
            payload = base64.b64decode(data_b64, validate=True)
        except (ValueError, binascii.Error):
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "error",
                        "code": "invalid_data",
                        "message": "stdin data must be base64",
                    },
                    ensure_ascii=False,
                ),
            )
            continue
        try:
            rule = await session.write_stdin(payload)
        except SandboxTerminalError as exc:
            await websocket.send_text(
                json.dumps(
                    {"type": "error", "code": "pty_closed", "message": str(exc)},
                    ensure_ascii=False,
                ),
            )
            break
        if rule is not None:
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "error",
                        "code": "self_preservation",
                        "message": f"command blocked: {rule}",
                        "rule": rule,
                    },
                    ensure_ascii=False,
                ),
            )


async def dashboard_terminal_ws_endpoint(websocket: WebSocket) -> None:
    """Handle ``GET /ws/dashboard/terminal`` with owner JWT + CSRF + upgrade ticket.

    Args:
        websocket (WebSocket): FastAPI WebSocket object.

    Returns:
        None: Runs until disconnect, timeout, or policy failure.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(dashboard_terminal_ws_endpoint)
        True
    """
    await websocket.accept()
    workspace: WorkspaceConfig = websocket.app.state.workspace
    layout: WorkspaceLayout = websocket.app.state.layout
    service: DashboardAuthService = websocket.app.state.dashboard_auth_service

    if not local_open_effective(workspace, websocket):
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=15.0)
        except (TimeoutError, WebSocketDisconnect):
            await websocket.close(code=4401)
            return
        try:
            frame = json.loads(raw)
        except (TypeError, ValueError):
            await websocket.close(code=4401)
            return
        if not isinstance(frame, dict) or frame.get("type") != "auth":
            await websocket.close(code=4401)
            return
        token = frame.get("token")
        csrf = frame.get("csrf")
        session_id = frame.get("session_id")
        if (
            not isinstance(token, str)
            or not isinstance(csrf, str)
            or not isinstance(session_id, str)
        ):
            await websocket.close(code=4401)
            return
        claims = service.verify_dashboard_jwt(token)
        if claims is None:
            await websocket.close(code=4401)
            return
        cookie_csrf = websocket.cookies.get(DASHBOARD_CSRF_COOKIE_NAME)
        if not service.verify_csrf(cookie=cookie_csrf, header=csrf):
            await websocket.close(code=4403)
            return
        ticket = terminal_session_registry.consume(session_id, owner_sub=claims.sub)
        if ticket is None:
            await websocket.close(code=4403)
            return
        ws_session_id = session_id
    else:
        ws_session_id = uuid.uuid4().hex

    proxy_url = str(getattr(websocket.app.state, "proxy_public_url", "") or "")
    try:
        session = await create_sandbox_terminal_session(
            layout=layout,
            cfg=workspace,
            proxy_url=proxy_url,
        )
    except SandboxTerminalError as exc:
        await websocket.send_text(
            json.dumps(
                {"type": "error", "code": "sandbox_unavailable", "message": str(exc)},
                ensure_ascii=False,
            ),
        )
        await websocket.close(code=1011)
        return

    session.session_id = ws_session_id
    _active[ws_session_id] = session
    await _emit_terminal_audit(
        websocket,
        kind="mission.terminal.session_start",
        session_id=ws_session_id,
        driver=session.driver.value,
        extra={"cwd": str(layout.content_root)},
    )
    await websocket.send_text(
        json.dumps(
            {
                "type": "ready",
                "session_id": ws_session_id,
                "driver": session.driver.value,
                "max_lifetime_s": int(session.max_lifetime_s),
            },
            ensure_ascii=False,
        ),
    )

    reader = asyncio.create_task(_pty_reader(websocket, session))
    writer = asyncio.create_task(_pty_writer(websocket, session))
    done, pending = await asyncio.wait({reader, writer}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    for task in done:
        with contextlib.suppress(WebSocketDisconnect, asyncio.CancelledError):
            task.result()

    duration_s = int(time.monotonic() - session.started_at)
    await session.close()
    _active.pop(ws_session_id, None)
    await _emit_terminal_audit(
        websocket,
        kind="mission.terminal.session_end",
        session_id=ws_session_id,
        driver=session.driver.value,
        extra={"duration_s": duration_s},
    )


__all__ = ["active_terminal_sessions", "dashboard_terminal_ws_endpoint"]
