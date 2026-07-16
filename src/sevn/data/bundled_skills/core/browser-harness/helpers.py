"""CDP harness helpers for the bundled ``browser-harness`` skill.

Module: sevn.data.bundled_skills.core.browser-harness.helpers
Depends: asyncio, json, os, urllib.request, websockets

Exports:
    default_cdp_url — resolve ``SEVN_CDP_URL``.
    cdp_http_json — GET a CDP HTTP JSON endpoint.
    browser_cdp — raw Chrome DevTools Protocol call over WebSocket.

Examples:
    >>> default_cdp_url().startswith("http")
    True
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any, Final
from urllib import error as urlerror
from urllib import request as urlrequest

# Match ``sevn.browser.cdp.connection`` — DOM/screenshot payloads exceed 1 MiB default.
_MAX_WS_SIZE: Final[int] = 256 * 1024 * 1024


def default_cdp_url() -> str:
    """Return the configured CDP HTTP base URL.

    Returns:
        str: Normalised CDP endpoint without trailing slash.

    Examples:
        >>> default_cdp_url().endswith("9222")
        True
    """
    return os.environ.get("SEVN_CDP_URL", "http://127.0.0.1:9222").rstrip("/")


def cdp_http_json(path: str, *, timeout: float = 3.0) -> Any:
    """Fetch JSON from a CDP HTTP path such as ``/json/version``.

    Args:
        path (str): Path suffix (leading ``/`` optional).
        timeout (float): HTTP timeout in seconds.

    Returns:
        Any: Parsed JSON value (object or list).

    Raises:
        RuntimeError: When the endpoint is unreachable or returns invalid JSON.

    Examples:
        >>> isinstance(cdp_http_json.__name__, str)
        True
    """
    suffix = path if path.startswith("/") else f"/{path}"
    url = f"{default_cdp_url()}{suffix}"
    try:
        with urlrequest.urlopen(url, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urlerror.URLError, OSError, json.JSONDecodeError, ValueError) as exc:
        msg = f"CDP HTTP request failed for {url}: {exc}"
        raise RuntimeError(msg) from exc
    return payload


def cdp_http_object(path: str, *, timeout: float = 3.0) -> dict[str, Any]:
    """Like :func:`cdp_http_json` but require a JSON object response.

    Args:
        path (str): Path suffix (leading ``/`` optional).
        timeout (float): HTTP timeout in seconds.

    Returns:
        dict[str, Any]: Parsed JSON object.

    Raises:
        RuntimeError: When the payload is not a JSON object.

    Examples:
        >>> isinstance(cdp_http_object.__name__, str)
        True
    """
    payload = cdp_http_json(path, timeout=timeout)
    if not isinstance(payload, dict):
        msg = f"CDP HTTP response was not a JSON object: {path}"
        raise RuntimeError(msg)
    return payload


def _ws_debugger_url() -> str:
    data = cdp_http_object("/json/version")
    ws = data.get("webSocketDebuggerUrl")
    if not isinstance(ws, str) or not ws.strip():
        msg = "CDP /json/version missing webSocketDebuggerUrl"
        raise RuntimeError(msg)
    return ws.strip()


def _pick_page_target() -> str:
    listing = cdp_http_json("/json/list")
    if isinstance(listing, list):
        for row in listing:
            if isinstance(row, dict) and row.get("type") == "page":
                tid = row.get("id")
                if isinstance(tid, str) and tid.strip():
                    return tid.strip()
    version = cdp_http_object("/json/version")
    tid = version.get("id")
    if isinstance(tid, str) and tid.strip():
        return tid.strip()
    msg = "no CDP page target available"
    raise RuntimeError(msg)


def browser_cdp(
    method: str,
    params: dict[str, Any] | None = None,
    *,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Dispatch a raw CDP method over the harness WebSocket.

    Args:
        method (str): CDP method name (for example ``Page.captureScreenshot``).
        params (dict[str, Any] | None): Optional CDP params mapping.
        session_id (str | None): Optional attached session id for target-scoped calls.

    Returns:
        dict[str, Any]: Parsed CDP result object (``result`` field when present).

    Raises:
        RuntimeError: When the WebSocket call fails or CDP returns an error.

    Examples:
        >>> isinstance(browser_cdp.__name__, str)
        True
    """
    try:
        import websockets
    except ImportError as exc:
        msg = "websockets not installed — run: uv sync --extra browser-cdp"
        raise RuntimeError(msg) from exc

    ws_url = _ws_debugger_url()
    target_id = _pick_page_target()

    async def _call() -> dict[str, Any]:
        msg_id = 1
        async with websockets.connect(ws_url, open_timeout=15, max_size=_MAX_WS_SIZE) as conn:
            attach = {
                "id": msg_id,
                "method": "Target.attachToTarget",
                "params": {"targetId": target_id, "flatten": True},
            }
            msg_id += 1
            await conn.send(json.dumps(attach))
            attach_resp = json.loads(await conn.recv())
            if attach_resp.get("error"):
                err = attach_resp["error"]
                raise RuntimeError(f"Target.attachToTarget failed: {err}")
            attached_session = attach_resp.get("result", {}).get("sessionId")
            active_session = session_id or attached_session
            if not isinstance(active_session, str) or not active_session.strip():
                raise RuntimeError("CDP attach did not return sessionId")

            payload: dict[str, Any] = {
                "id": msg_id,
                "method": method,
                "params": dict(params or {}),
                "sessionId": active_session,
            }
            await conn.send(json.dumps(payload))
            raw = json.loads(await conn.recv())
            if raw.get("error"):
                raise RuntimeError(f"CDP error for {method}: {raw['error']}")
            result = raw.get("result")
            return result if isinstance(result, dict) else {"value": result}

    return asyncio.run(_call())
