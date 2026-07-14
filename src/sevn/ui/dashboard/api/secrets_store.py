"""Mission Control encrypted secrets store CRUD (MC W1 §2b).

Module: sevn.ui.dashboard.api.secrets_store
Depends: fastapi, pydantic, sevn.gateway.admin.admin_secrets, sevn.secrets.migrate,
    sevn.ui.dashboard.api.deps, sevn.ui.dashboard.services.mission_audit

Exports:
    SecretRevealResponse — reveal response schema.
    SecretsStoreStatusResponse — store status schema.
    SecretsEntriesResponse — list entries schema.
    secrets_store_status — store health summary.
    secrets_store_entries_list — list aliases + fingerprints.
    secrets_store_entry_reveal — reveal plaintext (owner audit).
    secrets_store_entry_put — put secret (owner+csrf).
    secrets_store_entry_delete — delete secret (owner+csrf).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from sevn.gateway.admin.admin_secrets import (
    SecretDeleteBody,
    SecretDeleteResponse,
    SecretEntryOut,
    SecretPutBody,
    SecretPutResponse,
)
from sevn.secrets.fingerprint import fingerprint_sha256_hex
from sevn.secrets.migrate import encrypted_file_backend_for_workspace
from sevn.security.secrets.backends.encrypted_file import EncryptedFileBackend
from sevn.security.secrets.errors import SecretsStoreCorruptError
from sevn.security.secrets.factory import resolve_primary_encrypted_store_path
from sevn.ui.dashboard.api.deps import require_dashboard_csrf, require_dashboard_owner
from sevn.ui.dashboard.services.auth import DashboardClaims
from sevn.ui.dashboard.services.mission_audit import emit_mission_audit
from sevn.workspace.layout import WorkspaceLayout

router = APIRouter(tags=["dashboard-secrets-store"])


class SecretRevealResponse(BaseModel):
    """Reveal response for one logical secret."""

    alias: str
    plaintext: str


class SecretsStoreStatusResponse(BaseModel):
    """Store status for the Secrets tab."""

    backend: str
    store_path: str
    healthy: bool
    entry_count: int


class SecretsEntriesResponse(BaseModel):
    """List response without secret values."""

    entries: list[SecretEntryOut]


async def _backend_for_request(request: Request) -> EncryptedFileBackend:
    """Load encrypted-file backend from workspace app state.

    Args:
        request (Request): FastAPI request with layout and workspace.

    Returns:
        EncryptedFileBackend: Writable secrets backend.

    Raises:
        HTTPException: When backend env or config is invalid.

    Examples:
        >>> _backend_for_request.__name__
        '_backend_for_request'
    """
    layout: WorkspaceLayout = request.app.state.layout
    ws = request.app.state.workspace
    try:
        return encrypted_file_backend_for_workspace(layout.content_root, ws)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/secrets/store", response_model=SecretsStoreStatusResponse)
async def secrets_store_status(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> SecretsStoreStatusResponse:
    """Return encrypted store status (no secret values).

    Args:
        request (Request): FastAPI request with layout.
        _claims (DashboardClaims): Verified dashboard owner.

    Returns:
        SecretsStoreStatusResponse: Backend type, path, health, entry count.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(secrets_store_status)
        True
    """
    layout: WorkspaceLayout = request.app.state.layout
    ws = request.app.state.workspace
    store_path = resolve_primary_encrypted_store_path(layout.content_root, ws.secrets_backend)
    rel = store_path.relative_to(layout.content_root.resolve()).as_posix()
    healthy = False
    count = 0
    try:
        backend = await _backend_for_request(request)
        enc_map = await backend.load_decrypted_map()
        healthy = True
        count = len(enc_map)
    except SecretsStoreCorruptError:
        healthy = False
    except (ValueError, HTTPException):
        healthy = False
    return SecretsStoreStatusResponse(
        backend="encrypted_file",
        store_path=rel,
        healthy=healthy,
        entry_count=count,
    )


@router.get("/secrets/store/entries", response_model=SecretsEntriesResponse)
async def secrets_store_entries_list(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> SecretsEntriesResponse:
    """List logical secrets with fingerprints only.

    Args:
        request (Request): FastAPI request.
        _claims (DashboardClaims): Verified dashboard owner.

    Returns:
        SecretsEntriesResponse: Sorted alias rows.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(secrets_store_entries_list)
        True
    """
    backend = await _backend_for_request(request)
    try:
        enc_map = await backend.load_decrypted_map()
    except SecretsStoreCorruptError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    rows = [
        SecretEntryOut(alias=key, fingerprint_sha256_hex=fingerprint_sha256_hex(enc_map[key]))
        for key in sorted(enc_map)
    ]
    return SecretsEntriesResponse(entries=rows)


@router.get("/secrets/store/entries/{alias}", response_model=SecretRevealResponse)
async def secrets_store_entry_reveal(
    alias: str,
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> SecretRevealResponse:
    """Reveal one logical secret for the owner session.

    Args:
        alias (str): Logical secret key.
        request (Request): FastAPI request.
        _claims (DashboardClaims): Verified dashboard owner.

    Returns:
        SecretRevealResponse: Alias and plaintext.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(secrets_store_entry_reveal)
        True
    """
    backend = await _backend_for_request(request)
    try:
        value = await backend.get(alias)
    except SecretsStoreCorruptError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if value is None:
        raise HTTPException(status_code=404, detail=f"alias {alias!r} not present")
    await emit_mission_audit(
        request,
        kind="mission.secrets.read",
        alias=alias,
        hub_type="mission.secrets.changed",
    )
    return SecretRevealResponse(alias=alias, plaintext=value)


@router.put("/secrets/store/entries/{alias}", response_model=SecretPutResponse)
async def secrets_store_entry_put(
    alias: str,
    body: SecretPutBody,
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> SecretPutResponse:
    """Create or overwrite a logical secret (owner+csrf).

    Args:
        alias (str): Logical secret key.
        body (SecretPutBody): Plaintext and optional fingerprint confirm.
        request (Request): FastAPI request.
        _claims (DashboardClaims): Verified dashboard owner.
        _csrf (None): CSRF guard.

    Returns:
        SecretPutResponse: Put result with fingerprint.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(secrets_store_entry_put)
        True
    """
    backend = await _backend_for_request(request)
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
    await emit_mission_audit(
        request,
        kind="mission.secrets.write",
        alias=alias,
        hub_type="mission.secrets.changed",
        extra={"overwritten": existing is not None},
    )
    return SecretPutResponse(
        alias=alias, fingerprint_sha256_hex=fp, overwritten=existing is not None
    )


@router.delete("/secrets/store/entries/{alias}", response_model=SecretDeleteResponse)
async def secrets_store_entry_delete(
    alias: str,
    body: SecretDeleteBody,
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> SecretDeleteResponse:
    """Delete one logical secret after confirm (owner+csrf).

    Args:
        alias (str): Logical secret key.
        body (SecretDeleteBody): Confirm alias + fingerprint.
        request (Request): FastAPI request.
        _claims (DashboardClaims): Verified dashboard owner.
        _csrf (None): CSRF guard.

    Returns:
        SecretDeleteResponse: Delete acknowledgement.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(secrets_store_entry_delete)
        True
    """
    if body.confirm_alias.strip() != alias.strip():
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "CONFIRM_ALIAS_MISMATCH",
                "message": "confirm_alias must exactly match alias",
            },
        )
    backend = await _backend_for_request(request)
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
    await emit_mission_audit(
        request,
        kind="mission.secrets.delete",
        alias=alias,
        hub_type="mission.secrets.changed",
    )
    return SecretDeleteResponse(alias=alias)


__all__ = [
    "router",
    "secrets_store_entries_list",
    "secrets_store_entry_delete",
    "secrets_store_entry_put",
    "secrets_store_entry_reveal",
    "secrets_store_status",
]
