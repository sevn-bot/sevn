"""Open a sevn ASGI app against a temporary home.

Product imports are inside the context manager so pytest can collect the suite
before `sevn.http` exists.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

INDEX_HTML = "<!doctype html><title>sevn</title>\n"
CSP = (
    "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'"
)


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
    from starlette.testclient import TestClient

    client = TestClient(app, base_url=base_url, follow_redirects=False, timeout=5)
    client.__enter__()
    try:
        token = (tmp_path / "run" / "token").read_text(encoding="utf-8").strip()
        yield app, token, client
    finally:
        client.__exit__(None, None, None)
