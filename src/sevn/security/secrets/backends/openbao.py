"""OpenBao / Vault OSS KV v2 read path (``specs/06-secrets.md`` §3.2).

Module: sevn.security.secrets.backends.openbao
Depends: httpx

Exports:
    OpenBaoBackend — optional KV backend; **HashiCorp Vault Enterprise is not supported**.

Values are stored as KV v2 at ``mount/data/{prefix}/{key}`` with a JSON body
``{"value": "<secret>"}`` (``data.data.value``).
"""

from __future__ import annotations

import os
from urllib.parse import quote

import httpx


class OpenBaoBackend:
    """Minimal read/write against OSS KV v2."""

    def __init__(
        self,
        *,
        address: str,
        mount: str,
        prefix: str = "",
        token: str | None = None,
        namespace: str | None = None,
    ) -> None:
        """Configure the OpenBao client.

        Args:
            address (str): Base URL of the OpenBao server.
            mount (str): KV v2 mount path.
            prefix (str): Optional path prefix prepended to logical keys. Defaults to "".
            token (str | None): API token; ``None`` falls back to ``SEVN_OPENBAO_TOKEN``.
            namespace (str | None): Optional Vault-namespace header value.

        Examples:
            >>> b = OpenBaoBackend(address="https://bao.example", mount="secret")
            >>> b.__class__.__name__
            'OpenBaoBackend'
        """
        self._address = address.rstrip("/")
        self._mount = mount.strip("/")
        self._prefix = prefix.strip("/")
        self._token = token
        self._namespace = namespace

    def _resolve_token_sync(self) -> str | None:
        """Return a Vault token from config, env token, or AppRole login.

        Returns:
            str | None: Token for ``X-Vault-Token``, or ``None`` when unset.

        Examples:
            >>> b = OpenBaoBackend(address="https://bao.example", mount="secret", token="t")
            >>> b._resolve_token_sync()
            't'
        """
        if self._token:
            return self._token
        env_token = os.environ.get("SEVN_OPENBAO_TOKEN")
        if env_token:
            return env_token
        role_id = os.environ.get("SEVN_OPENBAO_ROLE_ID", "").strip()
        secret_id = os.environ.get("SEVN_OPENBAO_SECRET_ID", "").strip()
        if not role_id or not secret_id:
            return None
        url = f"{self._address}/v1/auth/approle/login"
        body = {"role_id": role_id, "secret_id": secret_id}
        with httpx.Client(timeout=30.0) as client:
            r = client.post(url, json=body)
        r.raise_for_status()
        payload = r.json()
        auth = payload.get("auth")
        if isinstance(auth, dict):
            client_token = auth.get("client_token")
            if isinstance(client_token, str) and client_token.strip():
                return client_token.strip()
        return None

    def _path_url(self, key: str) -> str:
        """Build the KV v2 data URL for ``key`` under mount + prefix.

        Args:
            key (str): Logical secret id (URL-quoted with ``.`` allowed).

        Returns:
            str: Full URL to ``mount/data/{prefix}/{key}``.

        Examples:
            >>> b = OpenBaoBackend(address="https://bao.example", mount="secret")
            >>> b._path_url("k").endswith("/v1/secret/data/k")
            True
        """
        safe = quote(key, safe=".")
        p = f"{self._prefix}/{safe}" if self._prefix else safe
        return f"{self._address}/v1/{self._mount}/data/{p}"

    def _headers(self) -> dict[str, str]:
        """Build the request headers (token + optional namespace).

        Returns:
            dict[str, str]: HTTP headers for OpenBao requests.

        Examples:
            >>> b = OpenBaoBackend(address="https://bao.example", mount="secret", token="t")
            >>> b._headers().get("X-Vault-Token")
            't'
        """
        h: dict[str, str] = {}
        token = self._resolve_token_sync()
        if token:
            h["X-Vault-Token"] = token
        if self._namespace:
            h["X-Vault-Namespace"] = self._namespace
        return h

    async def get(self, key: str) -> str | None:
        """Return plaintext for ``key`` from KV v2 ``data.data.value``.

        Args:
            key (str): Logical secret id.

        Returns:
            str | None: Plaintext on hit, ``None`` if missing or no token configured.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(OpenBaoBackend.get)
            True
        """
        if not self._resolve_token_sync():
            return None
        url = self._path_url(key)
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url, headers=self._headers())
        if r.status_code == 404:
            return None
        r.raise_for_status()
        payload = r.json()
        inner = payload.get("data", {}).get("data")
        if not isinstance(inner, dict):
            return None
        val = inner.get("value")
        if isinstance(val, str):
            return val
        return None

    async def set(self, key: str, value: str) -> None:
        """Write ``{"value": value}`` to KV v2 at ``mount/data/{prefix}/{key}``.

        Args:
            key (str): Logical secret id.
            value (str): UTF-8 plaintext to store under ``data.value``.

        Raises:
            NotImplementedError: If no token is configured.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(OpenBaoBackend.set)
            True
        """
        if not self._resolve_token_sync():
            msg = (
                "OpenBaoBackend requires SEVN_OPENBAO_TOKEN, token in config, "
                "or SEVN_OPENBAO_ROLE_ID + SEVN_OPENBAO_SECRET_ID AppRole pair"
            )
            raise NotImplementedError(msg)
        url = self._path_url(key)
        body = {"data": {"value": value}}
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, headers=self._headers(), json=body)
        r.raise_for_status()

    async def delete(self, key: str) -> None:
        """Delete the metadata (and all versions) for ``key`` (idempotent).

        Args:
            key (str): Logical secret id.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(OpenBaoBackend.delete)
            True
        """
        if not self._resolve_token_sync():
            return
        safe = quote(key, safe=".")
        p = f"{self._prefix}/{safe}" if self._prefix else safe
        del_url = f"{self._address}/v1/{self._mount}/metadata/{p}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.delete(del_url, headers=self._headers())
        if r.status_code not in (200, 204, 404):
            r.raise_for_status()
