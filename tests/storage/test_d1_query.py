"""D1 REST query client (`specs/03-storage.md` §3.3)."""

from __future__ import annotations

import httpx

from sevn.storage.d1_backend import D1BackendConfig, D1StorageBackend


def test_d1_query_parses_rows(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        assert "query" in request.url.path
        return httpx.Response(
            200,
            json={
                "success": True,
                "result": [{"results": [{"id": 1, "name": "a"}]}],
            },
        )

    transport = httpx.MockTransport(handler)
    real = httpx.Client

    def _client(*args: object, **kwargs: object) -> httpx.Client:
        kwargs["transport"] = transport
        kwargs.setdefault("timeout", 60.0)
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", _client)
    backend = D1StorageBackend(D1BackendConfig("acct", "db-id", "token"))
    rows = backend.query("SELECT * FROM t")
    assert rows == [{"id": 1, "name": "a"}]
