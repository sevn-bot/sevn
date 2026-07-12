"""Dashboard spec-kit REST router (`specs/24-dashboard.md` §2.6).

Module: sevn.ui.dashboard.api.spec_kit
Depends: dataclasses, fastapi, sevn.evolution.spec_kit, sevn.evolution.spec_kit_runs,
    sevn.ui.dashboard.api.deps

Exports:
    PutConstitutionBody — ``PUT /spec-kit/constitution`` request body.
    PutSpecKitOptionsBody — ``PUT /spec-kit/options`` request body.
    TestInvokeBody — ``POST /spec-kit/test-invoke`` request body.
    get_constitution — return constitution markdown and metadata.
    get_constitution_template — return bundled reset template.
    put_constitution — persist constitution for owner principal.
    get_spec_kit_options — read MC-facing options snapshot.
    put_spec_kit_options — merge-patch spec-kit workspace keys.
    get_spec_kit_runs — cursor-paginated audit log.
    post_test_invoke — dry-run one allowlisted spec-kit command.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from sevn.config.workspace_config import WorkspaceConfig
from sevn.evolution import spec_kit, spec_kit_runs
from sevn.ui.dashboard.api.deps import require_dashboard_csrf, require_dashboard_owner
from sevn.ui.dashboard.services.auth import DashboardClaims
from sevn.workspace.layout import WorkspaceLayout

router = APIRouter(prefix="/spec-kit", tags=["dashboard-spec-kit"])


class PutConstitutionBody(BaseModel):
    """``PUT /spec-kit/constitution`` request body."""

    text: str = Field(min_length=0)


class PutSpecKitOptionsBody(BaseModel):
    """``PUT /spec-kit/options`` request body."""

    model_config = {"extra": "allow"}


class TestInvokeBody(BaseModel):
    """``POST /spec-kit/test-invoke`` request body."""

    command: str = Field(min_length=1)
    argv: list[str] = Field(default_factory=list)
    issue_id: str | None = None
    job_id: str | None = None
    dry_run: bool | None = None


def _layout(request: Request) -> WorkspaceLayout:
    """Return workspace layout from app state.

    Args:
        request (Request): FastAPI request.

    Returns:
        WorkspaceLayout: Resolved layout.

    Examples:
        >>> _layout.__name__
        '_layout'
    """
    layout: WorkspaceLayout = request.app.state.layout
    return layout


def _workspace(request: Request) -> WorkspaceConfig:
    """Return parsed workspace config from app state.

    Args:
        request (Request): FastAPI request.

    Returns:
        WorkspaceConfig: Parsed workspace.

    Examples:
        >>> _workspace.__name__
        '_workspace'
    """
    ws: WorkspaceConfig = request.app.state.workspace
    return ws


def _constitution_dict(payload: spec_kit.ConstitutionPayload) -> dict[str, object]:
    """Serialise one constitution payload for JSON.

    Args:
        payload (spec_kit.ConstitutionPayload): Loaded or saved body.

    Returns:
        dict[str, object]: JSON-safe mapping.

    Examples:
        >>> row = _constitution_dict(
        ...     spec_kit.ConstitutionPayload("hi", "/p", True, "repo"),
        ... )
        >>> row["text"] == "hi"
        True
    """
    return {
        "text": payload.text,
        "path": payload.path,
        "writable": payload.writable,
        "source": payload.source,
        "banner": payload.banner,
    }


def _run_result_dict(result: spec_kit.SpecKitRunResult) -> dict[str, object]:
    """Serialise one spec-kit run result for JSON.

    Args:
        result (spec_kit.SpecKitRunResult): Subprocess outcome.

    Returns:
        dict[str, object]: JSON-safe mapping.

    Examples:
        >>> _run_result_dict.__name__
        '_run_result_dict'
    """
    return asdict(result)


@router.get("/constitution")
async def get_constitution(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return constitution markdown and persistence metadata.

    Args:
        request (Request): FastAPI request with app state.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Constitution body and metadata.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(get_constitution)
        True
    """
    ws = _workspace(request)
    layout = _layout(request)
    return _constitution_dict(spec_kit.load_constitution(ws, layout))


@router.get("/constitution/template")
async def get_constitution_template(
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return the bundled constitution template for **Reset**.

    Args:
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Template markdown body.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(get_constitution_template)
        True
    """
    return {"text": spec_kit.constitution_template_text()}


@router.put("/constitution")
async def put_constitution(
    body: PutConstitutionBody,
    request: Request,
    claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> dict[str, object]:
    """Persist constitution markdown for the owner principal.

    Args:
        body (PutConstitutionBody): Markdown body.
        request (Request): FastAPI request with app state.
        claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        dict[str, object]: Post-save constitution metadata.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(put_constitution)
        True
    """
    ws = _workspace(request)
    layout = _layout(request)
    saved = spec_kit.save_constitution(
        body.text,
        owner_principal=claims.sub,
        ws=ws,
        layout=layout,
    )
    return _constitution_dict(saved)


@router.get("/options")
async def get_spec_kit_options(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, Any]:
    """Return Mission Control spec-kit options snapshot.

    Args:
        request (Request): FastAPI request with app state.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, Any]: Options toggles and nested ``spec_kit`` subtree.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(get_spec_kit_options)
        True
    """
    return spec_kit.load_spec_kit_options(_workspace(request))


@router.put("/options")
async def put_spec_kit_options(
    body: PutSpecKitOptionsBody,
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> dict[str, Any]:
    """Merge-patch spec-kit related workspace keys in ``sevn.json``.

    Args:
        body (PutSpecKitOptionsBody): Partial update from Mission Control.
        request (Request): FastAPI request with app state.
        _claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        dict[str, Any]: Post-save options snapshot.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(put_spec_kit_options)
        True
    """
    layout = _layout(request)
    patch = body.model_dump(exclude_unset=True)
    return spec_kit.save_spec_kit_options(patch, sevn_json_path=layout.sevn_json_path)


@router.get("/runs")
async def get_spec_kit_runs(
    request: Request,
    limit: int | None = None,
    cursor: str | None = None,
    issue_id: str | None = None,
    job_id: str | None = None,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return cursor-paginated spec-kit run audit rows.

    Args:
        request (Request): FastAPI request with app state.
        limit (int | None): Page size (default 50, max 200).
        cursor (str | None): Pagination cursor (run_id).
        issue_id (str | None): Filter to one evolution issue id.
        job_id (str | None): Filter to one self-improve job id.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: ``items`` and optional ``next_cursor``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(get_spec_kit_runs)
        True
    """
    layout = _layout(request)
    cap = 50 if limit is None else max(1, min(int(limit), 200))
    items, next_cursor = spec_kit_runs.list_spec_kit_runs(
        layout.dot_sevn,
        limit=cap,
        cursor=cursor,
        issue_id=issue_id,
        job_id=job_id,
    )
    for row in items:
        row_job_id = row.get("job_id")
        if row_job_id is not None:
            row["improve_job_id"] = row_job_id
    return {"items": items, "next_cursor": next_cursor}


@router.post("/test-invoke")
async def post_test_invoke(
    body: TestInvokeBody,
    request: Request,
    claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> dict[str, object]:
    """Dry-run or invoke one allowlisted spec-kit command.

    Args:
        body (TestInvokeBody): Command, argv, and optional correlation ids.
        request (Request): FastAPI request with app state.
        claims (DashboardClaims): Verified dashboard owner claims.
        _csrf (None): Verified double-submit CSRF token.

    Returns:
        dict[str, object]: Structured subprocess outcome.

    Raises:
        HTTPException: ``400`` when command or argv fail allowlist checks.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(post_test_invoke)
        True
    """
    ws = _workspace(request)
    layout = _layout(request)
    cwd = layout.dot_sevn / "spec-kit" / "test-invoke"
    try:
        result = spec_kit.run_specify_allowlisted(
            body.command,
            body.argv,
            cwd,
            owner_principal=claims.sub,
            ws=ws,
            layout=layout,
            issue_id=body.issue_id,
            job_id=body.job_id,
            dry_run=body.dry_run,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _run_result_dict(result)
