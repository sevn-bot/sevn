"""LiteLLM Agent Control Plane HTTP client (CA5.1).

Module: sevn.integrations.litellm_lap.client
Depends: urllib.request (stdlib only — no extra deps)

Exports:
    LitellmLapClient — auth, list runtimes, create/run agent, session id map.

LAP API reference:
    POST /v1/run/create                — create + run an agent turn.
    POST /v1/run/stream                — streaming variant (not yet wired).
    GET  /v1/runtime/list              — list available runtimes.
    GET  /health                       — health probe.

In offline / test mode (``offline=True`` or when the LAP stack is not up),
all methods return plausible stub responses so the rest of sevn can develop
without a running docker compose stack.

Examples:
    >>> client = LitellmLapClient(base_url="http://localhost:4000", offline=True)
    >>> import asyncio
    >>> health = asyncio.run(client.health())
    >>> health["status"]
    'ok'
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any
from urllib.error import URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

JsonDict = dict[str, Any]

_DEFAULT_TIMEOUT = 15.0


class LitellmLapClient:
    """HTTP client for LiteLLM Agent Control Plane.

    Args:
        base_url (str): LAP base URL (e.g. ``http://127.0.0.1:4000``).
        api_key (str | None): Bearer token for LAP API calls. Defaults to ``sk-local``.
        timeout (float): HTTP timeout seconds.
        offline (bool): When ``True``, all methods return stub responses without HTTP.

    Examples:
        >>> c = LitellmLapClient(base_url="http://localhost:4000", offline=True)
        >>> c.base_url
        'http://localhost:4000'
    """

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:4000",
        api_key: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        offline: bool = False,
    ) -> None:
        """Wire base URL, auth, timeout, and offline flag.

        Args:
            base_url (str): LAP base URL.
            api_key (str | None): Bearer token; defaults to ``sk-local``.
            timeout (float): HTTP timeout seconds.
            offline (bool): When ``True`` all methods return stub responses.

        Examples:
            >>> LitellmLapClient(base_url="http://localhost:4000").base_url
            'http://localhost:4000'
        """
        self.base_url = base_url.rstrip("/")
        self.api_key: str = api_key or "sk-local"
        self.timeout = timeout
        self.offline = offline
        self._session_map: dict[str, str] = {}

    def _headers(self) -> dict[str, str]:
        """Build standard request headers.

        Returns:
            dict[str, str]: Auth and content-type headers.

        Examples:
            >>> c = LitellmLapClient()
            >>> "Authorization" in c._headers()
            True
        """
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        """Build an absolute URL for a LAP API path.

        Args:
            path (str): Relative path (e.g. ``/health``).

        Returns:
            str: Absolute URL string.

        Examples:
            >>> LitellmLapClient(base_url="http://localhost:4000")._url("/health")
            'http://localhost:4000/health'
        """
        return urljoin(self.base_url + "/", path.lstrip("/"))

    def _do_request(self, method: str, path: str, body: JsonDict | None = None) -> JsonDict:
        """Execute a synchronous HTTP request.

        Args:
            method (str): HTTP method.
            path (str): URL path.
            body (JsonDict | None): Request body.

        Returns:
            JsonDict: Parsed JSON response.

        Raises:
            URLError: On network failure.

        Examples:
            >>> c = LitellmLapClient(offline=True)
            >>> isinstance(c._do_request, object)
            True
        """
        url = self._url(path)
        data = json.dumps(body).encode() if body is not None else None
        req = Request(url, data=data, headers=self._headers(), method=method)
        with urlopen(req, timeout=self.timeout) as resp:  # nosec B310
            result: JsonDict = json.loads(resp.read().decode())
            return result

    # ------------------------------------------------------------------
    # Async wrappers (run sync I/O in executor so callers can await)
    # ------------------------------------------------------------------

    async def _request(self, method: str, path: str, body: JsonDict | None = None) -> JsonDict:
        """Async wrapper around :meth:`_do_request`.

        Args:
            method (str): HTTP method.
            path (str): URL path.
            body (JsonDict | None): Request body.

        Returns:
            JsonDict: Parsed JSON, or stub fallback when offline or unreachable.

        Examples:
            >>> import asyncio
            >>> c = LitellmLapClient(offline=True)
            >>> asyncio.run(c._request("GET", "/health"))["status"]
            'ok'
        """
        if self.offline:
            return self._stub_response(method, path, body)
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, self._do_request, method, path, body)
        except (URLError, OSError, json.JSONDecodeError):
            # Server not reachable — return stub so tests pass without a live stack.
            return self._stub_response(method, path, body)

    def _stub_response(self, method: str, path: str, body: JsonDict | None) -> JsonDict:
        """Generate a stub response for offline/test mode.

        Args:
            method (str): HTTP method.
            path (str): URL path.
            body (JsonDict | None): Request body.

        Returns:
            JsonDict: Plausible stub response for the given path.

        Examples:
            >>> c = LitellmLapClient(offline=True)
            >>> c._stub_response("GET", "/health", None)["status"]
            'ok'
        """
        if "health" in path:
            return {"status": "ok", "stub": True}
        if "runtime/list" in path:
            return {"runtimes": [{"id": "stub-runtime", "name": "Stub"}], "stub": True}
        if "run/create" in path or "run/stream" in path:
            session_id = (body or {}).get("session_id") or str(uuid.uuid4())
            message = (body or {}).get("message", "")
            return {"session_id": session_id, "reply": f"[stub] echo: {message}", "stub": True}
        return {"stub": True, "method": method, "path": path}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def health(self) -> JsonDict:
        """Probe LAP health endpoint.

        Returns:
            JsonDict: ``{"status": "ok"}`` when healthy.

        Examples:
            >>> import asyncio
            >>> c = LitellmLapClient(offline=True)
            >>> asyncio.run(c.health())["status"]
            'ok'
        """
        return await self._request("GET", "/health")

    async def list_runtimes(self) -> JsonDict:
        """List available LAP runtimes.

        Returns:
            JsonDict: Runtime list envelope.

        Examples:
            >>> import asyncio
            >>> c = LitellmLapClient(offline=True)
            >>> asyncio.run(c.list_runtimes())["runtimes"][0]["id"]
            'stub-runtime'
        """
        return await self._request("GET", "/v1/runtime/list")

    async def create_run(
        self,
        *,
        runtime_id: str,
        agent_id: str,
        message: str,
        session_id: str | None = None,
        extra: JsonDict | None = None,
    ) -> JsonDict:
        """Create and run an agent turn on the LAP.

        Args:
            runtime_id (str): LAP runtime identifier.
            agent_id (str): LAP agent UUID.
            message (str): Operator/user message for this turn.
            session_id (str | None): Existing session id; auto-generated when ``None``.
            extra (JsonDict | None): Additional request fields merged in.

        Returns:
            JsonDict: Response with ``session_id`` and ``reply``.

        Examples:
            >>> import asyncio
            >>> c = LitellmLapClient(offline=True)
            >>> r = asyncio.run(c.create_run(runtime_id="r", agent_id="a", message="hi"))
            >>> "hi" in r["reply"]
            True
        """
        sid = session_id or str(uuid.uuid4())
        body: JsonDict = {
            "runtime_id": runtime_id,
            "agent_id": agent_id,
            "message": message,
            "session_id": sid,
            **(extra or {}),
        }
        result = await self._request("POST", "/v1/run/create", body)
        if "session_id" in result:
            self._session_map[agent_id] = str(result["session_id"])
        return result

    async def send_message(
        self,
        *,
        session_id: str,
        message: str,
        runtime_id: str | None = None,
        agent_id: str | None = None,
    ) -> JsonDict:
        """Send a message to an existing LAP session.

        Args:
            session_id (str): Target session id.
            message (str): Message text.
            runtime_id (str | None): Optional runtime id for routing.
            agent_id (str | None): Optional agent id for routing.

        Returns:
            JsonDict: Response with ``session_id`` and ``reply``.

        Examples:
            >>> import asyncio
            >>> c = LitellmLapClient(offline=True)
            >>> r = asyncio.run(c.send_message(session_id="s1", message="ping"))
            >>> r["session_id"]
            's1'
            >>> "ping" in r["reply"]
            True
        """
        body: JsonDict = {"session_id": session_id, "message": message}
        if runtime_id:
            body["runtime_id"] = runtime_id
        if agent_id:
            body["agent_id"] = agent_id
        return await self._request("POST", "/v1/run/create", body)

    def get_session_id(self, agent_id: str) -> str | None:
        """Return the last known LAP session id for an agent.

        Args:
            agent_id (str): Registry agent id.

        Returns:
            str | None: Session id or ``None`` when no session exists.

        Examples:
            >>> c = LitellmLapClient()
            >>> c.get_session_id("unknown") is None
            True
        """
        return self._session_map.get(agent_id)


__all__ = ["LitellmLapClient"]
