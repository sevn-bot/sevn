"""Gateway channel capability inventory HTTP route (#151).

Module: sevn.gateway.api.capabilities_api
Depends: fastapi, sevn.gateway.capabilities_inventory

Exports:
    build_capabilities_router — ``GET /capabilities`` router factory.
    register_capabilities_routes — mount on a FastAPI app.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from sevn.gateway.capabilities_inventory import build_channel_capabilities_inventory


def build_capabilities_router() -> APIRouter:
    """Return router exposing the channel maturity inventory.

    Returns:
        APIRouter: Single-route router for ``GET /capabilities``.

    Examples:
        >>> build_capabilities_router().routes[0].path
        '/capabilities'
    """
    router = APIRouter(tags=["capabilities"])

    @router.get("/capabilities")
    async def capabilities() -> JSONResponse:
        """Return channel stub vs implemented inventory for integrators."""
        return JSONResponse(build_channel_capabilities_inventory())

    return router


def register_capabilities_routes(app: Any) -> None:
    """Mount capability inventory routes on ``app``.

    Args:
        app (Any): FastAPI application instance.

    Examples:
        >>> register_capabilities_routes.__name__
        'register_capabilities_routes'
    """
    app.include_router(build_capabilities_router())


__all__ = ["build_capabilities_router", "register_capabilities_routes"]
