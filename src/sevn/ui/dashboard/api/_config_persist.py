"""Shared helpers for persisting Mission Control config edits to ``sevn.json``.

Module: sevn.ui.dashboard.api._config_persist
Depends: fastapi, pydantic, sevn.config, sevn.onboarding

Exports:
    config_error — structured dashboard error envelope.
    config_validation_error — map validation failures to HTTP 422.
    read_config_body — parse a JSON object body or return ``{}``.
    load_workspace_document — read the on-disk ``sevn.json`` document.
    persist_workspace_document — validate, write, promote, and reload ``sevn.json``.
    deep_merge — recursively merge a partial patch into a base mapping.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from fastapi.responses import JSONResponse
from pydantic import ValidationError

from sevn.config.workspace_config import WorkspaceConfig
from sevn.onboarding.draft_store import write_draft
from sevn.onboarding.promote import promote_draft
from sevn.onboarding.validate import validate_workspace_document
from sevn.workspace.layout import WorkspaceLayout

if TYPE_CHECKING:
    from fastapi import Request


def config_error(code: str, message: str, *, status_code: int) -> JSONResponse:
    """Return a structured dashboard error envelope.

    Args:
        code (str): Stable error code.
        message (str): Human-readable message.
        status_code (int): HTTP status.

    Returns:
        JSONResponse: Error body matching the dashboard envelope shape.

    Examples:
        >>> config_error("x", "y", status_code=400).status_code
        400
    """

    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": {}}},
    )


def config_validation_error(exc: Exception) -> JSONResponse:
    """Map a validation/schema failure to a dashboard **422**.

    Args:
        exc (Exception): Validation or schema failure.

    Returns:
        JSONResponse: Structured validation error.

    Examples:
        >>> config_validation_error(ValueError("bad")).status_code
        422
    """

    if isinstance(exc, ValidationError):
        detail = "; ".join(err["msg"] for err in exc.errors()[:8]) or "validation failed"
    else:
        detail = str(exc)
    return config_error("validation_failed", detail, status_code=422)


async def read_config_body(request: Request) -> dict[str, Any]:
    """Parse a JSON object body or return an empty dict.

    Args:
        request (Request): Incoming HTTP request.

    Returns:
        dict[str, Any]: Parsed object body (``{}`` when absent or non-object).

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(read_config_body)
        True
    """

    try:
        body = await request.json()
    except (ValueError, TypeError):
        return {}
    return body if isinstance(body, dict) else {}


def load_workspace_document(request: Request) -> dict[str, Any]:
    """Read the active ``sevn.json`` document as a raw mapping.

    Args:
        request (Request): FastAPI request with ``layout`` on ``app.state``.

    Returns:
        dict[str, Any]: Parsed JSON document.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(load_workspace_document)
        True
    """

    layout: WorkspaceLayout = request.app.state.layout
    raw = json.loads(layout.sevn_json_path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def persist_workspace_document(request: Request, on_disk: dict[str, Any]) -> WorkspaceConfig:
    """Validate, atomically write, promote, and reload a ``sevn.json`` document.

    Args:
        request (Request): FastAPI request with ``layout`` on ``app.state``.
        on_disk (dict[str, Any]): Full workspace document to persist.

    Returns:
        WorkspaceConfig: Reloaded config (also stored on ``app.state.workspace``).

    Examples:
        >>> import inspect
        >>> inspect.isfunction(persist_workspace_document)
        True
    """

    layout: WorkspaceLayout = request.app.state.layout
    sevn_json = layout.sevn_json_path
    validate_workspace_document(on_disk)
    write_draft(sevn_json, on_disk)
    promote_draft(sevn_json, backup_previous=True)
    ws = WorkspaceConfig.model_validate(on_disk)
    request.app.state.workspace = ws
    return ws


def deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``patch`` into a copy of ``base`` (dict values merge).

    Args:
        base (dict[str, Any]): Existing mapping.
        patch (dict[str, Any]): Partial overrides; nested dicts merge by key.

    Returns:
        dict[str, Any]: New merged mapping (inputs are not mutated).

    Examples:
        >>> deep_merge({"a": {"x": 1}}, {"a": {"y": 2}})
        {'a': {'x': 1, 'y': 2}}
    """

    merged = dict(base)
    for key, value in patch.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


__all__ = [
    "config_error",
    "config_validation_error",
    "deep_merge",
    "load_workspace_document",
    "persist_workspace_document",
    "read_config_body",
]
