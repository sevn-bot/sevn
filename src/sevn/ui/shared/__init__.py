"""Shared operator UI scripts (theme, etc.) served at ``/shared/*``.

Module: sevn.ui.shared
Depends: pathlib, fastapi

Exports:
    serve_shared_ui_asset — path-safe handler for ``/shared/{path}``.
    register_shared_ui_routes — mount ``/shared`` and ``/style`` on a FastAPI app.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi.responses import FileResponse, JSONResponse, Response

from sevn.ui.style import serve_style_asset

if TYPE_CHECKING:
    from fastapi import FastAPI

SHARED_UI_ROOT: Path = Path(__file__).resolve().parent

_MIME: dict[str, str] = {
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
}


def serve_shared_ui_asset(asset_path: str) -> Response:
    """Serve a file from ``sevn.ui.shared`` with path traversal protection.

    Args:
        asset_path (str): Relative path under the shared UI root.

    Returns:
        Response: ``FileResponse`` or 404 JSON.

    Examples:
        >>> isinstance(serve_shared_ui_asset("theme.js"), Response)
        True
    """
    rel = asset_path.lstrip("/")
    if not rel:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    root = SHARED_UI_ROOT.resolve()
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    if not candidate.is_file():
        return JSONResponse(status_code=404, content={"error": "not_found"})
    media = _MIME.get(candidate.suffix.lower(), "application/octet-stream")
    return FileResponse(candidate, media_type=media)


def register_shared_ui_routes(app: FastAPI) -> None:
    """Register ``/style/*`` and ``/shared/*`` for all operator web surfaces.

    Args:
        app (FastAPI): Gateway or onboarding app.

    Returns:
        None: Routes are added in-place (idempotent if already present).

    Examples:
        >>> from fastapi import FastAPI
        >>> a = FastAPI()
        >>> register_shared_ui_routes(a)
        >>> any(getattr(r, "path", "") == "/style/{asset_path:path}" for r in a.routes)
        True
    """
    paths = {getattr(r, "path", "") for r in app.routes}

    if "/style/{asset_path:path}" not in paths:

        @app.get("/style/{asset_path:path}")
        async def shared_style(asset_path: str) -> Response:
            return serve_style_asset(asset_path)

    if "/shared/{asset_path:path}" not in paths:

        @app.get("/shared/{asset_path:path}")
        async def shared_ui(asset_path: str) -> Response:
            return serve_shared_ui_asset(asset_path)


__all__ = [
    "SHARED_UI_ROOT",
    "register_shared_ui_routes",
    "serve_shared_ui_asset",
]
