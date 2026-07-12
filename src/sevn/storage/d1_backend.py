"""Cloudflare D1 optional backend (`specs/03-storage.md` §3.3).

Exports:
    D1BackendConfig — connection parameters from workspace/env.
    D1StorageBackend — HTTP client for Cloudflare D1 query API.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import httpx

_D1_QUERY_URL = (
    "https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{database_id}/query"
)


@dataclass(frozen=True, slots=True)
class D1BackendConfig:
    """D1 worker endpoint configuration.

    Attributes:
        account_id (str): Cloudflare account id.
        database_id (str): D1 database id.
        api_token (str): API token with D1 SQL permissions.

    Examples:
        >>> D1BackendConfig(account_id="a", database_id="d", api_token="t").database_id
        'd'
    """

    account_id: str
    database_id: str
    api_token: str


class D1StorageBackend:
    """Cloudflare D1 SQL via the REST query API.

    Args:
        config (D1BackendConfig): Parsed D1 connection parameters.

    Examples:
        >>> D1StorageBackend(D1BackendConfig("a", "d", "t")).ping()
        'd1:configured'
    """

    def __init__(self, config: D1BackendConfig) -> None:
        """Store D1 connection parameters.

        Args:
            config (D1BackendConfig): Parsed D1 connection parameters.

        Examples:
            >>> D1StorageBackend(D1BackendConfig("a", "d", "t"))._config.database_id
            'd'
        """
        self._config = config

    def ping(self) -> str:
        """Return a stable readiness string for doctor checks.

        Returns:
            str: ``d1:configured`` when ids are non-empty.

        Examples:
            >>> D1StorageBackend(D1BackendConfig("a", "d", "t")).ping()
            'd1:configured'
        """
        if not self._config.database_id.strip():
            return "d1:missing_database_id"
        if not self._config.account_id.strip() or not self._config.api_token.strip():
            return "d1:missing_credentials"
        return "d1:configured"

    def _post_sql(self, sql: str, params: tuple[object, ...] = ()) -> dict[str, Any]:
        """POST one SQL statement batch to the D1 query API.

        Args:
            sql (str): SQL text.
            params (tuple[object, ...], optional): Bind parameters. Defaults to ().

        Returns:
            dict[str, Any]: Parsed JSON ``result`` object.

        Raises:
            RuntimeError: When HTTP fails or Cloudflare returns ``success: false``.

        Examples:
            >>> D1StorageBackend._post_sql.__name__
            '_post_sql'
        """
        url = _D1_QUERY_URL.format(
            account_id=self._config.account_id.strip(),
            database_id=self._config.database_id.strip(),
        )
        headers = {
            "Authorization": f"Bearer {self._config.api_token.strip()}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {"sql": sql}
        if params:
            body["params"] = list(params)
        with httpx.Client(timeout=60.0) as client:
            response = client.post(url, headers=headers, json=body)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not payload.get("success"):
            msg = f"d1 query failed: {payload!r}"
            raise RuntimeError(msg)
        result = payload.get("result")
        if not isinstance(result, list) or not result:
            msg = f"d1 query empty result: {payload!r}"
            raise RuntimeError(msg)
        first = result[0]
        if not isinstance(first, dict):
            msg = f"d1 query malformed result: {first!r}"
            raise RuntimeError(msg)
        return cast("dict[str, Any]", first)

    def apply_migration(self, version: int, sql: str) -> None:
        """Apply one migration statement batch.

        Args:
            version (int): Migration version number (recorded in SQL by caller).
            sql (str): D1-compatible SQL.

        Returns:
            None: Always.

        Examples:
            >>> D1StorageBackend.apply_migration.__name__
            'apply_migration'
        """
        _ = version
        self._post_sql(sql)

    def query(self, sql: str, params: tuple[object, ...] = ()) -> list[dict[str, object]]:
        """Run a read query and return row dicts.

        Args:
            sql (str): Parameterised SQL.
            params (tuple[object, ...], optional): Bind parameters.

        Returns:
            list[dict[str, object]]: Row dicts from the first result set.

        Examples:
            >>> D1StorageBackend.query.__name__
            'query'
        """
        block = self._post_sql(sql, params)
        rows = block.get("results")
        if not isinstance(rows, list):
            return []
        out: list[dict[str, object]] = []
        for row in rows:
            if isinstance(row, dict):
                out.append(cast("dict[str, object]", row))
        return out


__all__ = ["D1BackendConfig", "D1StorageBackend"]
