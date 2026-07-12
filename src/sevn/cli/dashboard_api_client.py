"""Thin Mission Control ``/api/v1`` reads for CLI command groups.

Module: sevn.cli.dashboard_api_client
Depends: httpx, sevn.cli.gateway_client, sevn.cli.json_util

Exports:
    dashboard_api_get — ``GET /api/v1/...`` with gateway transport + JSON parse.
    dashboard_api_post — ``POST /api/v1/...`` with gateway transport + JSON parse.
    dashboard_http_failure — map non-success responses to CLI exit ``4``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NoReturn

import typer

if TYPE_CHECKING:
    import httpx

from sevn.cli.gateway_client import gateway_json_request
from sevn.cli.json_util import emit_json_failure
from sevn.config.settings import ProcessSettings
from sevn.config.workspace_config import WorkspaceConfig


def _detail_from_response(response: httpx.Response) -> dict[str, Any]:
    """Extract error detail dict from a gateway HTTP response.

    Args:
        response (httpx.Response): Non-success response.

    Returns:
        dict[str, Any]: Parsed JSON detail or fallback wrapper.

    Examples:
        >>> import httpx
        >>> _detail_from_response(httpx.Response(401, json={"detail": "unauthorized"}))
        {'message': 'unauthorized'}
    """
    try:
        body = response.json()
    except ValueError:
        return {"message": response.text or response.reason_phrase}
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, dict):
            return detail
        if isinstance(detail, str):
            return {"message": detail}
        return body
    return {"message": response.text or response.reason_phrase}


def dashboard_http_failure(
    *,
    command: str,
    response: httpx.Response,
    json_out: bool,
    default_code: str = "DASHBOARD_API_ERROR",
) -> NoReturn:
    """Map dashboard API HTTP errors to CLI exit ``4``.

    Args:
        command (str): Command label for envelopes.
        response (httpx.Response): Non-success gateway response.
        json_out (bool): Whether to emit JSON failure envelope.
        default_code (str): Fallback ``error_code``.

    Returns:
        NoReturn: Always raises ``typer.Exit(4)``.

    Examples:
        >>> import httpx
        >>> import typer
        >>> try:
        ...     dashboard_http_failure(
        ...         command="t",
        ...         response=httpx.Response(401, json={"detail": "unauthorized"}),
        ...         json_out=False,
        ...     )
        ... except typer.Exit as exc:
        ...     exc.exit_code == 4
        ... else:
        ...     False
        True
    """
    detail = _detail_from_response(response)
    code = str(detail.get("error_code", default_code))
    message = str(detail.get("message", detail.get("detail", response.text or code)))
    extra = {k: v for k, v in detail.items() if k not in ("error_code", "message", "detail")}
    if json_out:
        emit_json_failure(
            command=command,
            error_code=code,
            message=message,
            exit_code=4,
            details=extra or None,
        )
    else:
        typer.secho(message, err=True)
    raise typer.Exit(4)


def dashboard_api_get(
    path: str,
    *,
    command: str,
    workspace: WorkspaceConfig,
    process: ProcessSettings | None = None,
    json_out: bool = False,
    transport: httpx.BaseTransport | None = None,
    require_token: bool = False,
) -> dict[str, Any]:
    """Perform one dashboard ``GET`` and return the JSON object body.

    Loopback ``dashboard.local_open`` sessions do not require a bearer token; when
    ``require_token`` is False the CLI may call Mission Control without
    ``SEVN_GATEWAY_TOKEN``.

    Args:
        path (str): Path under gateway origin (e.g. ``/api/v1/agent/config``).
        command (str): Invoked CLI command for error envelopes.
        workspace (WorkspaceConfig): Bound workspace config.
        process (ProcessSettings | None): Optional env overrides.
        json_out (bool): Emit JSON failure envelopes on error.
        transport (httpx.BaseTransport | None): Optional httpx transport for tests.
        require_token (bool): Fail before I/O when gateway token is missing.

    Returns:
        dict[str, Any]: Parsed JSON response body.

    Raises:
        typer.Exit: Exit code ``4`` on HTTP or transport errors.

    Examples:
        >>> from unittest.mock import patch
        >>> import httpx
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> t = httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True}, request=r))
        >>> with patch("sevn.cli.gateway_client.resolve_gateway_token", return_value="tok"):
        ...     dashboard_api_get(
        ...         "/api/v1/agent/config",
        ...         command="t",
        ...         workspace=WorkspaceConfig.minimal(),
        ...         transport=t,
        ...     )["ok"]
        True
    """
    api_path = path if path.startswith("/api/v1/") else f"/api/v1/{path.lstrip('/')}"
    response = gateway_json_request(
        "GET",
        api_path,
        process=process,
        workspace=workspace,
        require_token=require_token,
        transport=transport,
    )
    if response.status_code >= 400:
        dashboard_http_failure(command=command, response=response, json_out=json_out)
    try:
        body = response.json()
    except ValueError as exc:
        if json_out:
            emit_json_failure(
                command=command,
                error_code="DASHBOARD_API_ERROR",
                message=f"invalid JSON from {api_path}",
                exit_code=4,
            )
        else:
            typer.secho(f"invalid JSON from {api_path}", err=True)
        raise typer.Exit(4) from exc
    if not isinstance(body, dict):
        if json_out:
            emit_json_failure(
                command=command,
                error_code="DASHBOARD_API_ERROR",
                message=f"unexpected JSON type from {api_path}",
                exit_code=4,
            )
        else:
            typer.secho(f"unexpected JSON type from {api_path}", err=True)
        raise typer.Exit(4)
    return body


def dashboard_api_post(
    path: str,
    *,
    command: str,
    workspace: WorkspaceConfig,
    process: ProcessSettings | None = None,
    json_out: bool = False,
    transport: httpx.BaseTransport | None = None,
    require_token: bool = False,
) -> dict[str, Any]:
    """Perform one dashboard ``POST`` and return the JSON object body.

    Args:
        path (str): Path under gateway origin (e.g. ``/api/v1/mission/subagents/x/kill``).
        command (str): Invoked CLI command for error envelopes.
        workspace (WorkspaceConfig): Bound workspace config.
        process (ProcessSettings | None): Optional env overrides.
        json_out (bool): Emit JSON failure envelopes on error.
        transport (httpx.BaseTransport | None): Optional httpx transport for tests.
        require_token (bool): Fail before I/O when gateway token is missing.

    Returns:
        dict[str, Any]: Parsed JSON response body.

    Raises:
        typer.Exit: Exit code ``4`` on HTTP or transport errors.

    Examples:
        >>> from unittest.mock import patch
        >>> import httpx
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> t = httpx.MockTransport(lambda r: httpx.Response(200, json={"killed": True}, request=r))
        >>> with patch("sevn.cli.gateway_client.resolve_gateway_token", return_value="tok"):
        ...     dashboard_api_post(
        ...         "/api/v1/mission/subagents/a1/kill",
        ...         command="t",
        ...         workspace=WorkspaceConfig.minimal(),
        ...         transport=t,
        ...     )["killed"]
        True
    """
    api_path = path if path.startswith("/api/v1/") else f"/api/v1/{path.lstrip('/')}"
    response = gateway_json_request(
        "POST",
        api_path,
        process=process,
        workspace=workspace,
        require_token=require_token,
        transport=transport,
    )
    if response.status_code >= 400:
        dashboard_http_failure(command=command, response=response, json_out=json_out)
    try:
        body = response.json()
    except ValueError as exc:
        if json_out:
            emit_json_failure(
                command=command,
                error_code="DASHBOARD_API_ERROR",
                message=f"invalid JSON from {api_path}",
                exit_code=4,
            )
        else:
            typer.secho(f"invalid JSON from {api_path}", err=True)
        raise typer.Exit(4) from exc
    if not isinstance(body, dict):
        if json_out:
            emit_json_failure(
                command=command,
                error_code="DASHBOARD_API_ERROR",
                message=f"unexpected JSON type from {api_path}",
                exit_code=4,
            )
        else:
            typer.secho(f"unexpected JSON type from {api_path}", err=True)
        raise typer.Exit(4)
    return body


__all__ = ["dashboard_api_get", "dashboard_api_post", "dashboard_http_failure"]
