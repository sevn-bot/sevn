"""Gateway-delegated ``sevn secrets`` HTTP client (`specs/23-cli.md` §8).

Module: sevn.cli.secrets_gateway_client
Depends: httpx, sevn.cli.gateway_client, sevn.cli.workspace, sevn.config.workspace_config

Exports:
    secrets_list — ``GET /api/v1/admin/secrets``.
    secrets_put — ``PUT /api/v1/admin/secrets/{alias}``.
    secrets_delete — ``DELETE /api/v1/admin/secrets/{alias}``.
    http_error_detail — parse gateway error JSON for CLI envelopes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    import httpx

from sevn.cli.gateway_client import gateway_json_request
from sevn.cli.workspace import BoundWorkspace


def _detail_dict(response: httpx.Response) -> dict[str, Any]:
    """Parse FastAPI error ``detail`` when JSON.

    Args:
        response (httpx.Response): Gateway error response.

    Returns:
        dict[str, Any]: Parsed detail or wrapped message dict.

    Examples:
        >>> import httpx
        >>> _detail_dict(httpx.Response(400, json={"detail": "x"})).get("message", "x") == "x"
        True
    """
    try:
        body = response.json()
    except ValueError:
        return {"message": response.text}
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, dict):
            return detail
        if isinstance(detail, str):
            return {"message": detail}
        return body
    return {"message": str(body)}


def secrets_list(
    bw: BoundWorkspace,
    *,
    transport: httpx.BaseTransport | None = None,
) -> list[dict[str, str]]:
    """List logical secret aliases via the gateway admin API.

    Args:
        bw (BoundWorkspace): Bound workspace for URL resolution.
        transport (httpx.BaseTransport | None): Optional httpx transport for tests.

    Returns:
        list[dict[str, str]]: Rows with ``alias`` and ``fingerprint_sha256_hex``.

    Raises:
        httpx.HTTPStatusError: When status is not success (caller maps exit codes).

    Examples:
        >>> import httpx
        >>> from unittest.mock import MagicMock
        >>> t = httpx.MockTransport(
        ...     lambda r: httpx.Response(200, json={"entries": []}, request=r),
        ... )
        >>> secrets_list(MagicMock(config=MagicMock()), transport=t)
        []
    """
    response = gateway_json_request(
        "GET",
        "/api/v1/admin/secrets",
        workspace=bw.config,
        transport=transport,
        require_token=transport is None,
        content_root=bw.layout.content_root,
    )
    response.raise_for_status()
    payload = response.json()
    entries = payload.get("entries", [])
    if not isinstance(entries, list):
        return []
    rows: list[dict[str, str]] = []
    for item in entries:
        if isinstance(item, dict):
            rows.append(
                {
                    "alias": str(item.get("alias", "")),
                    "fingerprint_sha256_hex": str(item.get("fingerprint_sha256_hex", "")),
                },
            )
    return rows


def secrets_put(
    bw: BoundWorkspace,
    *,
    alias: str,
    plaintext: str,
    confirm_fingerprint: str | None,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Store or replace a logical secret via the gateway admin API.

    Args:
        bw (BoundWorkspace): Bound workspace for URL resolution.
        alias (str): Logical secret id.
        plaintext (str): Secret value.
        confirm_fingerprint (str | None): Required when overwriting.
        transport (httpx.BaseTransport | None): Optional httpx transport for tests.

    Returns:
        dict[str, Any]: Gateway JSON body on success.

    Raises:
        httpx.HTTPStatusError: On non-success HTTP status.

    Examples:
        >>> import httpx
        >>> from unittest.mock import MagicMock
        >>> t = httpx.MockTransport(
        ...     lambda r: httpx.Response(
        ...         200,
        ...         json={"alias": "k", "fingerprint_sha256_hex": "ab", "overwritten": False},
        ...         request=r,
        ...     ),
        ... )
        >>> secrets_put(
        ...     MagicMock(config=MagicMock()),
        ...     alias="k",
        ...     plaintext="v",
        ...     confirm_fingerprint=None,
        ...     transport=t,
        ... )["alias"]
        'k'
    """
    body: dict[str, object] = {"plaintext": plaintext}
    if confirm_fingerprint is not None:
        body["confirm_fingerprint"] = confirm_fingerprint
    response = gateway_json_request(
        "PUT",
        f"/api/v1/admin/secrets/{alias}",
        workspace=bw.config,
        json_body=body,
        transport=transport,
        require_token=transport is None,
        content_root=bw.layout.content_root,
    )
    if response.status_code >= 400:
        response.raise_for_status()
    return cast("dict[str, Any]", response.json())


def secrets_delete(
    bw: BoundWorkspace,
    *,
    alias: str,
    confirm_alias: str,
    confirm_fingerprint: str,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Delete a logical secret via the gateway admin API.

    Args:
        bw (BoundWorkspace): Bound workspace for URL resolution.
        alias (str): Logical secret id.
        confirm_alias (str): Anti-fat-finger confirmation.
        confirm_fingerprint (str): Fingerprint confirmation.
        transport (httpx.BaseTransport | None): Optional httpx transport for tests.

    Returns:
        dict[str, Any]: Gateway JSON body on success.

    Raises:
        httpx.HTTPStatusError: On non-success HTTP status.

    Examples:
        >>> import httpx
        >>> from unittest.mock import MagicMock
        >>> t = httpx.MockTransport(
        ...     lambda r: httpx.Response(200, json={"alias": "k", "deleted": True}, request=r),
        ... )
        >>> secrets_delete(
        ...     MagicMock(config=MagicMock()),
        ...     alias="k",
        ...     confirm_alias="k",
        ...     confirm_fingerprint="ab",
        ...     transport=t,
        ... )["deleted"]
        True
    """
    response = gateway_json_request(
        "DELETE",
        f"/api/v1/admin/secrets/{alias}",
        workspace=bw.config,
        json_body={
            "confirm_alias": confirm_alias,
            "confirm_fingerprint": confirm_fingerprint,
        },
        transport=transport,
        require_token=transport is None,
        content_root=bw.layout.content_root,
    )
    if response.status_code >= 400:
        response.raise_for_status()
    return cast("dict[str, Any]", response.json())


def http_error_detail(response: httpx.Response) -> dict[str, Any]:
    """Expose parsed gateway error detail for CLI envelopes.

    Args:
        response (httpx.Response): Failed gateway response.

    Returns:
        dict[str, Any]: Structured detail for ``emit_json_failure``.

    Examples:
        >>> import httpx
        >>> http_error_detail(httpx.Response(400, json={"detail": "bad"}))
        {'message': 'bad'}
    """
    return _detail_dict(response)
