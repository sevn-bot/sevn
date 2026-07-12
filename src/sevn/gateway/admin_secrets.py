"""Gateway-delegated operator secrets API (`specs/23-cli.md` §8, `specs/06-secrets.md`).

CLI ``sevn secrets`` calls these routes with ``SEVN_GATEWAY_TOKEN``; the gateway
mutates the workspace encrypted store — not a direct proxy admin path
(`specs/07-egress-proxy.md`).

Module: sevn.gateway.admin_secrets
Depends: fastapi, pydantic, sevn.secrets.*, sevn.security.secrets.*

Exports:
    SecretEntryOut — list row without secret values.
    SecretsListResponse — ``GET /api/v1/admin/secrets`` body.
    SecretPutBody — put request body.
    SecretPutResponse — put success body.
    SecretDeleteBody — delete confirmation body.
    SecretDeleteResponse — delete success body.
    register_admin_secrets_routes — mount ``/api/v1/admin/secrets`` on a FastAPI app.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from sevn.secrets.fingerprint import fingerprint_sha256_hex
from sevn.secrets.migrate import encrypted_file_backend_for_workspace
from sevn.security.secrets.errors import SecretsStoreCorruptError
from sevn.workspace.layout import WorkspaceLayout


class SecretEntryOut(BaseModel):
    """One logical secret row for list responses (no values)."""

    alias: str
    fingerprint_sha256_hex: str


class SecretsListResponse(BaseModel):
    """``GET /api/v1/admin/secrets`` body."""

    entries: list[SecretEntryOut]


class SecretPutBody(BaseModel):
    """``PUT /api/v1/admin/secrets/{alias}`` body."""

    plaintext: str = Field(min_length=1)
    confirm_fingerprint: str | None = None


class SecretPutResponse(BaseModel):
    """Put success payload."""

    alias: str
    fingerprint_sha256_hex: str
    overwritten: bool


class SecretDeleteBody(BaseModel):
    """``DELETE /api/v1/admin/secrets/{alias}`` body."""

    confirm_alias: str
    confirm_fingerprint: str


class SecretDeleteResponse(BaseModel):
    """Delete success payload."""

    alias: str
    deleted: bool = True


def _layout(request: Request) -> WorkspaceLayout:
    """Return workspace layout from app state.

    Args:
        request (Request): FastAPI request.

    Returns:
        WorkspaceLayout: Bound layout for the running gateway.

    Raises:
        HTTPException: When layout is not configured.

    Examples:
        >>> _layout.__name__
        '_layout'
    """
    layout = getattr(request.app.state, "layout", None)
    if not isinstance(layout, WorkspaceLayout):
        msg = "gateway layout not configured"
        raise HTTPException(status_code=503, detail=msg)
    return layout


def _workspace(request: Request) -> Any:
    """Return parsed workspace config from app state.

    Args:
        request (Request): FastAPI request.

    Returns:
        Any: Workspace config model.

    Raises:
        HTTPException: When workspace is not configured.

    Examples:
        >>> _workspace.__name__
        '_workspace'
    """
    ws = getattr(request.app.state, "workspace", None)
    if ws is None:
        msg = "gateway workspace not configured"
        raise HTTPException(status_code=503, detail=msg)
    return ws


def register_admin_secrets_routes(
    app: Any,
    *,
    enforce_gateway_auth: Any,
) -> None:
    """Mount operator secrets admin routes on ``app``.

    Args:
        app (Any): FastAPI application.
        enforce_gateway_auth (Any): ``Depends``-able auth guard (``SEVN_GATEWAY_TOKEN``).

    Returns:
        None: Routes are registered on ``app`` in-place.

    Examples:
        >>> register_admin_secrets_routes.__name__
        'register_admin_secrets_routes'
    """
    router = APIRouter(prefix="/api/v1/admin/secrets", tags=["admin-secrets"])

    @router.get("", response_model=SecretsListResponse)
    async def list_secrets(
        request: Request,
        _ok: None = Depends(enforce_gateway_auth),
    ) -> SecretsListResponse:
        layout = _layout(request)
        ws = _workspace(request)
        try:
            backend = encrypted_file_backend_for_workspace(layout.content_root, ws)
            enc_map = await backend.load_decrypted_map()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except SecretsStoreCorruptError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        rows = [
            SecretEntryOut(alias=key, fingerprint_sha256_hex=fingerprint_sha256_hex(enc_map[key]))
            for key in sorted(enc_map)
        ]
        return SecretsListResponse(entries=rows)

    @router.put("/{alias}", response_model=SecretPutResponse)
    async def put_secret(
        alias: str,
        body: SecretPutBody,
        request: Request,
        _ok: None = Depends(enforce_gateway_auth),
    ) -> SecretPutResponse:
        layout = _layout(request)
        ws = _workspace(request)
        try:
            backend = encrypted_file_backend_for_workspace(layout.content_root, ws)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            existing = await backend.get(alias)
        except SecretsStoreCorruptError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if existing is not None:
            want = fingerprint_sha256_hex(existing)
            got = (body.confirm_fingerprint or "").strip().lower()
            if got != want:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error_code": "CONFIRM_FINGERPRINT_REQUIRED",
                        "message": "overwrite blocked: confirm_fingerprint must match existing",
                        "expected_fingerprint_sha256_hex": want,
                    },
                )
        await backend.set(alias, body.plaintext)
        fp = fingerprint_sha256_hex(body.plaintext)
        return SecretPutResponse(
            alias=alias,
            fingerprint_sha256_hex=fp,
            overwritten=existing is not None,
        )

    @router.delete("/{alias}", response_model=SecretDeleteResponse)
    async def delete_secret(
        alias: str,
        body: SecretDeleteBody,
        request: Request,
        _ok: None = Depends(enforce_gateway_auth),
    ) -> SecretDeleteResponse:
        if body.confirm_alias.strip() != alias.strip():
            raise HTTPException(
                status_code=400,
                detail={
                    "error_code": "CONFIRM_ALIAS_MISMATCH",
                    "message": "confirm_alias must exactly match alias",
                },
            )
        layout = _layout(request)
        ws = _workspace(request)
        try:
            backend = encrypted_file_backend_for_workspace(layout.content_root, ws)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            existing = await backend.get(alias)
        except SecretsStoreCorruptError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if existing is None:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "MISSING_ALIAS", "message": f"alias {alias!r} not present"},
            )
        want = fingerprint_sha256_hex(existing)
        got = body.confirm_fingerprint.strip().lower()
        if got != want:
            raise HTTPException(
                status_code=400,
                detail={
                    "error_code": "CONFIRM_FINGERPRINT_MISMATCH",
                    "message": "confirm_fingerprint does not match stored secret",
                    "expected_fingerprint_sha256_hex": want,
                },
            )
        await backend.delete(alias)
        return SecretDeleteResponse(alias=alias)

    app.include_router(router)
