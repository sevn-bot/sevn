"""Open a sevn ASGI app against a temporary home.

Product imports are inside the context manager so pytest can collect the suite
before `sevn.http` exists.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
import pytest
from starlette.testclient import TestClient, WebSocketTestSession

INDEX_HTML = "<!doctype html><title>sevn</title>\n"
CSP = (
    "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'"
)


class _LoopbackClient(TestClient):
    """WebSocket dials the same host ``base_url`` used for the session cookie.

    Starlette 1.8 rejects ``timeout=`` on ``TestClient``. The 5s bound is set on
    the httpx client. ``websocket_connect`` otherwise always uses ``ws://testserver``,
    and httpx will not send the ``sevn_session`` cookie stored for ``127.0.0.1``.
    """

    def websocket_connect(
        self,
        url: str,
        subprotocols: Sequence[str] | None = None,
        **kwargs: Any,
    ) -> WebSocketTestSession:
        if not url.startswith(("ws://", "wss://")):
            url = urljoin(_websocket_base(str(self.base_url)), url)
        return super().websocket_connect(url, subprotocols, **kwargs)


def _websocket_base(base_url: str) -> str:
    scheme, rest = base_url.split("://", 1)
    ws_scheme = "wss" if scheme == "https" else "ws"
    return f"{ws_scheme}://{rest}"


@contextmanager
def running_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    dev: str | None = None,
    allowed_hosts: str | None = None,
    base_url: str = "http://127.0.0.1:8787",
) -> Iterator[tuple[object, str, object]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    monkeypatch.setenv("SEVN_SECRETS__BACKEND", "age-file")
    if dev is None:
        monkeypatch.delenv("SEVN_DEV", raising=False)
    else:
        monkeypatch.setenv("SEVN_DEV", dev)
    if allowed_hosts is None:
        monkeypatch.delenv("SEVN_ALLOWED_HOSTS", raising=False)
    else:
        monkeypatch.setenv("SEVN_ALLOWED_HOSTS", allowed_hosts)

    dist = tmp_path / "webdist"
    dist.mkdir(parents=True, exist_ok=True)
    index = dist / "index.html"
    if not index.exists():
        index.write_text(INDEX_HTML, encoding="utf-8")
    monkeypatch.setenv("SEVN_WEB_DIST", str(dist))

    config = tmp_path / "config.toml"
    if not config.exists():
        config.write_text(
            '[secrets]\nbackend = "age-file"\n\n[http]\nhost = "127.0.0.1"\nport = 8787\n',
            encoding="utf-8",
        )

    from sevn.config import Settings
    from sevn.http import create_app

    app = create_app(Settings(home=tmp_path))
    client = _LoopbackClient(app, base_url=base_url, follow_redirects=False)
    client.timeout = httpx.Timeout(5.0)
    client.__enter__()
    try:
        token = (tmp_path / "run" / "token").read_text(encoding="utf-8").strip()
        yield app, token, client
    finally:
        client.__exit__(None, None, None)
