"""Loopback HTTP: health, login cookie, WebSocket, and the static SPA (D7-D9, D19)."""

from __future__ import annotations

import asyncio
import hmac
import os
import secrets
import webbrowser
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from fastapi import FastAPI
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.responses import PlainTextResponse, RedirectResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocket

import sevn.api.agents as agent_api
import sevn.api.bots as bot_api
import sevn.api.messages as message_api
import sevn.api.models as model_api
import sevn.api.pending as pending_api
import sevn.system as system
from sevn import __version__
from sevn.config import Settings
from sevn.log import logger
from sevn.paths import Paths
from sevn.protocol.hub import Hub
from sevn.protocol.session import Session
from sevn.runtime.recovery import recover
from sevn.runtime.worker import Worker, bind
from sevn.secrets.registry import register
from sevn.store.db import upgrade
from sevn.store.oplog import OpLog
from sevn.store.outbox import Outbox
from sevn.transports.ws import WsConnection

# Importing these modules registers their protocol methods.
_REGISTERED = (
    system.system_info,
    system.system_ping,
    system.sync_since,
    bot_api.bots_create,
    bot_api.bots_list,
    bot_api.bots_get,
    bot_api.bots_update,
    bot_api.bots_delete,
    agent_api.agents_list,
    agent_api.agents_get,
    model_api.models_list,
    message_api.messages_send,
    message_api.messages_list,
    message_api.turns_snapshot,
    message_api.turns_cancel,
    pending_api.pending_list,
    pending_api.pending_answer,
)

CSP = (
    "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'"
)
_FORBIDDEN_ORIGIN = "forbidden origin"
_FORBIDDEN_HOST = "forbidden host"
_DEV_ORIGIN = "http://localhost:5173"
_DEV_HOST = "localhost:5173"

type _Asgi = Callable[[Scope, Receive, Send], Awaitable[None]]


@dataclass
class Runtime:
    """Bind address the guard and ``--open`` share with the server."""

    host: str
    port: int
    open_browser: bool = False


@dataclass
class AppState:
    settings: Settings
    runtime: Runtime
    token: str = ""
    hub: Hub | None = None
    outbox: Outbox | None = None
    oplog: OpLog | None = None


def check_credentials(presented: str, expected: str) -> bool:
    """Return whether ``presented`` is the current loopback token.

    The Origin/Host guard must not call this. A foreign request is refused
    before any credential lookup (D8).
    """
    if presented == "" or expected == "":
        return False
    left = presented.encode()
    right = expected.encode()
    if len(left) != len(right):
        return False
    return hmac.compare_digest(left, right)


def web_dist_path() -> Path:
    """SPA directory: ``SEVN_WEB_DIST`` or the packaged ``sevn/_web`` tree."""
    raw = os.environ.get("SEVN_WEB_DIST")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parent / "_web"


def create_app(settings: Settings) -> ASGIApp:
    """Build the FastAPI app. The lifespan opens the store and writes the token."""
    if not _REGISTERED:
        raise RuntimeError("system methods are not registered")
    state = AppState(
        settings=settings,
        runtime=Runtime(host=settings.http.host, port=settings.http.port),
    )
    app = FastAPI(lifespan=_lifespan)
    app.state.sevn = state
    app.add_middleware(OriginGuard, state=state)

    @app.get("/health")
    async def health() -> dict[str, str]:
        hub = _require_hub(state)
        return {"status": "ok", "version": __version__, "host_id": hub.identity.host_id}

    @app.get("/auth/login")
    async def login(token: str = "") -> Response:
        if not check_credentials(token, state.token):
            return PlainTextResponse("unauthorized", status_code=401)
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(
            "sevn_session",
            token,
            path="/",
            httponly=True,
            samesite="strict",
        )
        return response

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await _serve_socket(websocket, state)

    dist = web_dist_path()
    if dist.is_dir():
        app.mount("/", _Spa(directory=str(dist)), name="spa")
    return app


@asynccontextmanager
async def _lifespan(app: ASGIApp) -> AsyncGenerator[None]:
    state = _state(app)
    paths = Paths.from_env()
    url = f"sqlite+aiosqlite:///{paths.db}"
    await upgrade(url)
    outbox = Outbox(url)
    oplog = OpLog(url)
    state.outbox = outbox
    state.oplog = oplog
    browser: asyncio.Task[None] | None = None
    worker: Worker | None = None
    try:
        state.hub = Hub(outbox, oplog)
        await recover()
        worker = bind(state.hub)
        state.token = await asyncio.to_thread(_write_token, paths.run / "token")
        await asyncio.to_thread(
            _write_bind,
            paths.run / "bind",
            state.runtime.host,
            state.runtime.port,
        )
        register("loopback/token", state.token)
        if state.runtime.open_browser:
            browser = asyncio.create_task(_open_browser(state))
        yield
    finally:
        if browser is not None:
            browser.cancel()
            with suppress(asyncio.CancelledError):
                await browser
        if worker is not None:
            await worker.aclose()
        await outbox.aclose()
        await oplog.aclose()


class OriginGuard:
    """Refuse foreign Origin or Host on ``/ws`` and ``/auth/*`` before auth (D8)."""

    def __init__(self, app: _Asgi, state: AppState) -> None:
        self._app = app
        self._state = state

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self._app(scope, receive, send)
            return
        path = scope.get("path")
        if not isinstance(path, str) or not _guarded(path):
            await self._app(scope, receive, send)
            return
        message = refusal(
            Headers(scope=scope),
            self._state.runtime.port,
            server=scope.get("server"),
        )
        if message is None:
            await self._app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await _reject_websocket(send, message)
            return
        response = PlainTextResponse(message, status_code=403)
        await response(scope, receive, send)


class _Spa(StaticFiles):
    def __init__(self, directory: str) -> None:
        super().__init__(directory=directory, html=True)

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            # A missing file raises. It is not a response whose status is 404.
            if exc.status_code != 404 or not _client_route(path):
                raise
            response = await super().get_response("index.html", scope)
        if response.status_code == 404 and _client_route(path):
            response = await super().get_response("index.html", scope)
        response.headers["Content-Security-Policy"] = CSP
        return response


def _client_route(path: str) -> bool:
    """App paths such as ``bots/<id>`` fall back to the SPA. Asset files do not."""
    name = path.rsplit("/", 1)[-1]
    return "." not in name


def refusal(headers: Headers, port: int, *, server: object = None) -> str | None:
    """Return a 403 body, or ``None`` when the request may proceed.

    Host is checked first. This function does not read tokens or cookies.
    """
    host = headers.get("host")
    presented = host.strip() if host is not None else ""
    if presented not in _allowed_hosts(port) and not _testclient_socket(presented, server):
        return _FORBIDDEN_HOST
    origin = headers.get("origin")
    if origin is None or origin.strip() == "":
        return None
    origin = origin.strip()
    allowed = {f"http://{item}" for item in _allowed_hosts(port)}
    if os.environ.get("SEVN_DEV") == "1":
        allowed.add(_DEV_ORIGIN)
    if origin not in allowed:
        return _FORBIDDEN_ORIGIN
    return None


def _allowed_hosts(port: int) -> set[str]:
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
    # Vite forwards the browser Host. D8 already allows this origin when SEVN_DEV=1.
    if os.environ.get("SEVN_DEV") == "1":
        hosts.add(_DEV_HOST)
    extra = os.environ.get("SEVN_ALLOWED_HOSTS", "")
    for item in extra.split(","):
        cleaned = item.strip()
        if cleaned:
            hosts.add(cleaned)
    return hosts


def _testclient_socket(host: str, server: object) -> bool:
    """Starlette's TestClient opens WebSockets at ``ws://testserver`` (port 80).

    ``scope["server"]`` is set by the ASGI server, not the client. Uvicorn reports
    the real bind address, so a browser cannot claim this socket.
    """
    if host != "testserver":
        return False
    if isinstance(server, list):
        items = cast("list[object]", server)
    elif isinstance(server, tuple):
        items = list(cast("tuple[object, ...]", server))
    else:
        return False
    if len(items) != 2:
        return False
    name, bound = items
    return name == "testserver" and bound == 80


def _guarded(path: str) -> bool:
    return path == "/ws" or path == "/auth" or path.startswith("/auth/")


def _require_hub(state: AppState) -> Hub:
    if state.hub is None:
        raise RuntimeError("hub is not started")
    return state.hub


def _state(app: ASGIApp) -> AppState:
    sevn_state = getattr(app, "state", None)
    found = getattr(sevn_state, "sevn", None)
    if not isinstance(found, AppState):
        raise RuntimeError("sevn app state is missing")
    return found


async def _serve_socket(websocket: WebSocket, state: AppState) -> None:
    hub = _require_hub(state)
    await websocket.accept()
    raw_cookie = websocket.cookies.get("sevn_session")
    cookie = raw_cookie if raw_cookie else None
    session = Session(
        WsConnection(websocket),
        hub,
        token=state.token,
        queue_limit=state.settings.protocol.session_queue_limit,
        cookie=cookie,
    )
    await session.run()


async def _reject_websocket(send: Send, message: str) -> None:
    body = message.encode("utf-8")
    await send(
        {
            "type": "websocket.http.response.start",
            "status": 403,
            "headers": [(b"content-type", b"text/plain; charset=utf-8")],
        }
    )
    await send({"type": "websocket.http.response.body", "body": body})


def _write_bind(path: Path, host: str, port: int) -> None:
    """Publish the address this process bound so the probe does not dial config."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{host}\n{port}\n", encoding="ascii")


def _write_token(path: Path) -> str:
    token = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(descriptor, (token + "\n").encode("ascii"))
    finally:
        os.close(descriptor)
    os.chmod(path, 0o600)
    return token


async def _open_browser(state: AppState) -> None:
    """Open the login URL once the port accepts connections. The URL is not logged."""
    host = state.runtime.host
    if host in {"0.0.0.0", "::"}:  # noqa: S104
        host = "127.0.0.1"
    url = f"http://{host}:{state.runtime.port}/auth/login?token={state.token}"
    try:
        deadline = asyncio.get_running_loop().time() + 10
        while asyncio.get_running_loop().time() < deadline:
            if await asyncio.to_thread(_port_open, host, state.runtime.port):
                await asyncio.to_thread(webbrowser.open, url)
                return
            await asyncio.sleep(0.05)
    except OSError:
        logger.error("could not open the browser")
        return
    logger.error("could not open the browser")


def _port_open(host: str, port: int) -> bool:
    import socket

    try:
        with socket.create_connection((host, port), timeout=0.2):
            return True
    except OSError:
        return False
