"""OpenBao AppRole token resolution (`specs/06-secrets.md` §11)."""

from __future__ import annotations

import httpx

from sevn.security.secrets.backends.openbao import OpenBaoBackend


def test_approle_login_uses_role_and_secret(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("SEVN_OPENBAO_ROLE_ID", "role-1")
    monkeypatch.setenv("SEVN_OPENBAO_SECRET_ID", "secret-1")
    monkeypatch.delenv("SEVN_OPENBAO_TOKEN", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/auth/approle/login"):
            return httpx.Response(
                200,
                json={"auth": {"client_token": "leased-token"}},
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def _client(*args: object, **kwargs: object) -> httpx.Client:
        kwargs["transport"] = transport
        kwargs.setdefault("timeout", 30.0)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", _client)
    backend = OpenBaoBackend(address="https://bao.test", mount="secret")
    token = backend._resolve_token_sync()
    assert token == "leased-token"
