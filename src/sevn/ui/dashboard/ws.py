"""Dashboard WebSocket endpoint and in-process pub/sub hub.

Module: sevn.ui.dashboard.ws
Depends: asyncio, json, fastapi

Exports:
    DashboardHub — in-process asyncio pub/sub hub.
    dashboard_ws_endpoint — ``/ws/dashboard`` handler.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket  # noqa: TC002
from starlette.websockets import WebSocketDisconnect

from sevn.config.workspace_config import WorkspaceConfig
from sevn.ui.dashboard.services.auth import (
    DashboardAuthService,
    local_open_effective,
)


@dataclass
class DashboardHub:
    """In-process pub/sub for dashboard events."""

    _queues: set[asyncio.Queue[dict[str, Any]]] = field(default_factory=set)

    async def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """Register one subscriber queue.

        Returns:
            asyncio.Queue[dict[str, Any]]: Queue receiving future events.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(DashboardHub.subscribe)
            True
        """

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._queues.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Remove one subscriber queue.

        Args:
            queue (asyncio.Queue[dict[str, Any]]): Queue returned by :meth:`subscribe`.

        Returns:
            None: Side-effect only.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(DashboardHub.unsubscribe)
            True
        """

        self._queues.discard(queue)

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        """Publish one typed event to all current subscribers.

        Args:
            topic (str): Topic name such as ``proxy.health``.
            payload (dict[str, Any]): JSON-serializable payload.

        Returns:
            None: Side-effect only.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(DashboardHub.publish)
            True
        """

        event = {"type": "event", "topic": topic, "payload": payload}
        stale: list[asyncio.Queue[dict[str, Any]]] = []
        for queue in list(self._queues):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                stale.append(queue)
        for queue in stale:
            self._queues.discard(queue)


async def _receive_loop(websocket: WebSocket, topics: set[str]) -> None:
    """Read client control frames (ping, subscription) on the WebSocket.

    Args:
        websocket (WebSocket): Open WebSocket connection.
        topics (set[str]): Active topic filter; updated in place on subscribe.

    Returns:
        None: Loops until disconnect.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_receive_loop)
        True
    """

    while True:
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
        frame_type = frame.get("type")
        if frame_type == "ping":
            await websocket.send_text(json.dumps({"type": "pong"}, ensure_ascii=False))
        elif frame_type == "subscribe":
            raw_topics = frame.get("topics")
            if isinstance(raw_topics, list):
                topics.clear()
                topics.update(str(item) for item in raw_topics if isinstance(item, str) and item)
            await websocket.send_text(
                json.dumps({"type": "subscribed", "topics": sorted(topics)}, ensure_ascii=False),
            )


async def _send_loop(
    websocket: WebSocket,
    queue: asyncio.Queue[dict[str, Any]],
    topics: set[str],
) -> None:
    """Forward hub events to the WebSocket, honouring the topic filter.

    Args:
        websocket (WebSocket): Open WebSocket connection.
        queue (asyncio.Queue[dict[str, Any]]): Hub event queue.
        topics (set[str]): Active topic filter; empty means all topics.

    Returns:
        None: Loops until disconnect or send failure.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_send_loop)
        True
    """

    while True:
        event = await queue.get()
        topic = str(event.get("topic", ""))
        if topics and topic not in topics:
            continue
        await websocket.send_text(json.dumps(event, ensure_ascii=False))


async def dashboard_ws_endpoint(websocket: WebSocket) -> None:
    """Handle ``GET /ws/dashboard`` with first-message JWT auth.

    Args:
        websocket (WebSocket): FastAPI WebSocket object.

    Returns:
        None: Runs until disconnect or auth failure.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(dashboard_ws_endpoint)
        True
    """

    await websocket.accept()
    workspace: WorkspaceConfig = websocket.app.state.workspace
    service: DashboardAuthService = websocket.app.state.dashboard_auth_service
    hub: DashboardHub = websocket.app.state.dashboard_hub
    if not local_open_effective(workspace, websocket):
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
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
        if not isinstance(token, str) or service.verify_dashboard_jwt(token) is None:
            await websocket.close(code=4401)
            return

    topics: set[str] = set()
    queue = await hub.subscribe()
    await websocket.send_text(json.dumps({"type": "ready", "aud": "dashboard"}, ensure_ascii=False))
    receiver = asyncio.create_task(_receive_loop(websocket, topics))
    sender = asyncio.create_task(_send_loop(websocket, queue, topics))
    done, pending = await asyncio.wait(
        {receiver, sender},
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
    for task in done:
        with contextlib.suppress(WebSocketDisconnect):
            task.result()
    await hub.unsubscribe(queue)
