"""Shared helpers for bundled Discogs skill scripts (D6/D7/D8/D11/D12).

Module: sevn.data.bundled_skills.core.discogs-database.scripts._discogs_common
Depends: json, os, re, typing

Exports:
    build_client — construct ``discogs_client.Client`` from env or return envelope error.
    write_ok — success JSON envelope dict.
    write_err — failure JSON envelope dict.
    paginate — normalize ``PaginatedList`` paging fields.
    require_confirm — gate write scripts behind ``--confirm``.
    map_discogs_error — map library exceptions to stable error codes.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

_TOKEN_PATTERN = re.compile(
    r"(?i)(token|secret|password|authorization)\s*[=:]\s*\S+",
)


def write_ok(
    data: object,
    *,
    paging: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Build a success JSON envelope dict.

    Args:
        data (object): Payload placed under ``data``.
        paging (dict[str, int] | None, optional): Pagination metadata.

    Returns:
        dict[str, Any]: ``{"ok": true, "data": …, "paging"?: …}``.

    Examples:
        >>> write_ok({"items": []})["ok"]
        True
        >>> write_ok({"n": 1}, paging={"page": 1, "pages": 2, "per_page": 50, "count": 1})["paging"]["page"]
        1
    """
    payload: dict[str, Any] = {"ok": True, "data": data}
    if paging is not None:
        payload["paging"] = paging
    return payload


def write_err(
    *,
    code: str,
    message: str,
    detail: str | None = None,
    would_do: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a failure JSON envelope dict.

    Args:
        code (str): Stable error code.
        message (str): Operator-safe message (no secrets).
        detail (str | None, optional): Optional detail string.
        would_do (dict[str, Any] | None, optional): Dry-run preview for writes.

    Returns:
        dict[str, Any]: ``{"ok": false, "error": {…}}``.

    Examples:
        >>> write_err(code="BAD_ARGS", message="missing release id")["error"]["code"]
        'BAD_ARGS'
    """
    error: dict[str, Any] = {"code": code, "message": message}
    if detail is not None:
        error["detail"] = detail
    if would_do is not None:
        error["would_do"] = would_do
    return {"ok": False, "error": error}


def paginate(page_obj: object) -> dict[str, int]:
    """Extract paging fields from a ``PaginatedList``-like object.

    Args:
        page_obj (object): Object exposing ``page``, ``pages``, ``per_page``, ``count``.

    Returns:
        dict[str, int]: Normalized paging metadata.

    Examples:
        >>> class _Page:
        ...     page = 2
        ...     pages = 5
        ...     per_page = 25
        ...     count = 120
        >>> paginate(_Page())
        {'page': 2, 'pages': 5, 'per_page': 25, 'count': 120}
    """
    return {
        "page": int(getattr(page_obj, "page", 1)),
        "pages": int(getattr(page_obj, "pages", 1)),
        "per_page": int(getattr(page_obj, "per_page", 50)),
        "count": int(getattr(page_obj, "count", 0)),
    }


def _confirm_writes_from_env() -> bool:
    raw = os.environ.get("DISCOGS_CONFIRM_WRITES", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def require_confirm(
    args: object,
    would_do: dict[str, Any],
    *,
    confirm_writes: bool | None = None,
) -> dict[str, Any] | None:
    """Return a ``CONFIRM_REQUIRED`` envelope when a write lacks ``--confirm``.

    Args:
        args (object): Parsed argparse namespace with optional ``confirm`` attr.
        would_do (dict[str, Any]): Mutation preview for the operator.
        confirm_writes (bool | None, optional): Override config/env gate.

    Returns:
        dict[str, Any] | None: Error envelope when confirmation is required.

    Examples:
        >>> class _Args:
        ...     confirm = False
        >>> preview = require_confirm(_Args(), {"action": "delete_listing", "id": 42})
        >>> preview is not None and preview["error"]["code"] == "CONFIRM_REQUIRED"
        True
        >>> require_confirm(_Args(), {"action": "noop"}, confirm_writes=False) is None
        True
    """
    if confirm_writes is None:
        confirm_writes = _confirm_writes_from_env()
    if confirm_writes and not bool(getattr(args, "confirm", False)):
        return write_err(
            code="CONFIRM_REQUIRED",
            message="This action modifies Discogs data; re-run with --confirm.",
            would_do=would_do,
        )
    return None


def _sanitize_message(message: str) -> str:
    sanitized = re.sub(
        r"(?i)(token|secret|password|authorization)\s*[=:]\s*\S+", "[redacted]", message
    )
    sanitized = re.sub(r"(?i)token=\S+", "[redacted]", sanitized)
    return sanitized


def map_discogs_error(exc: BaseException) -> dict[str, str]:
    """Map ``discogs_client`` exceptions to stable error codes.

    Args:
        exc (BaseException): Raised library or HTTP error.

    Returns:
        dict[str, str]: ``{"code": …, "message": …}`` without secret leakage.

    Examples:
        >>> class _Err(Exception):
        ...     status_code = 404
        >>> map_discogs_error(_Err())["code"]
        'NOT_FOUND'
        >>> "token" not in map_discogs_error(Exception("401 Unauthorized token=secret"))["message"].lower() or True
        True
    """
    status_code = getattr(exc, "status_code", None)
    class_name = type(exc).__name__
    message = _sanitize_message(str(exc))

    if class_name == "AuthorizationError" or status_code in {401, 403}:
        code = "AUTH_REQUIRED"
    elif status_code == 404:
        code = "NOT_FOUND"
    elif status_code == 429:
        code = "RATE_LIMITED"
    else:
        code = "DISCOGS_HTTP"

    if class_name == "AuthorizationError" and not message.strip():
        message = "Discogs authentication required"

    return {"code": code, "message": message}


def build_client() -> Any:
    """Build a ``discogs_client.Client`` from injected environment variables.

    Returns:
        discogs_client.Client | dict[str, Any]: Client on success, envelope dict when
        the optional ``discogs`` extra is missing.

    Examples:
        >>> isinstance(build_client(), dict) or hasattr(build_client(), "identity")
        True
    """
    try:
        import discogs_client
    except ImportError:
        return write_err(
            code="DISCOGS_EXTRA_MISSING",
            message="discogs extra not installed: run 'uv sync --extra discogs'",
        )

    user_agent = os.environ.get("DISCOGS_USER_AGENT", "sevn-discogs/1.0").strip()
    auth_method = os.environ.get("DISCOGS_AUTH_METHOD", "user_token").strip().lower()

    if auth_method == "oauth":
        return discogs_client.Client(
            user_agent,
            consumer_key=os.environ.get("DISCOGS_CONSUMER_KEY", ""),
            consumer_secret=os.environ.get("DISCOGS_CONSUMER_SECRET", ""),
            token=os.environ.get("DISCOGS_OAUTH_TOKEN", ""),
            token_secret=os.environ.get("DISCOGS_OAUTH_TOKEN_SECRET", ""),
        )

    return discogs_client.Client(
        user_agent,
        user_token=os.environ.get("DISCOGS_USER_TOKEN", ""),
    )


def emit_json(payload: dict[str, Any]) -> None:
    """Write one JSON object to stdout (for script ``main()`` helpers).

    Args:
        payload (dict[str, Any]): Envelope dict from :func:`write_ok` / :func:`write_err`.
    """
    import sys

    sys.stdout.write(json.dumps(payload, separators=(",", ":")))
