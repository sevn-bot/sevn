"""Mission Control guarded workspace file API (MC W1).

Module: sevn.ui.dashboard.api.files
Depends: asyncio, shutil, fastapi, sevn.ui.dashboard.api.deps,
    sevn.ui.dashboard.services.mission_audit, sevn.ui.dashboard.services.workspace_fs

Exports:
    FileContentPutBody — PUT /files/content body schema.
    FileCreateBody — POST /files body schema.
    FileRenameBody — POST /files/rename body schema.
    files_tree — confined directory listing.
    files_content_get — read text file with redaction.
    files_content_put — write text file (owner+csrf).
    files_create — create file (owner+csrf).
    files_rename — rename file (owner+csrf).
    files_delete — soft-trash delete (owner+csrf).
"""

from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from sevn.config.workspace_config import WorkspaceConfig
from sevn.tools.paths import filter_visible_entries
from sevn.ui.dashboard.api.deps import require_dashboard_csrf, require_dashboard_owner
from sevn.ui.dashboard.services.auth import DashboardClaims
from sevn.ui.dashboard.services.mission_audit import emit_mission_audit
from sevn.ui.dashboard.services.workspace_fs import (
    ALLOWED_ROOT_KEYS,
    MAX_FILE_BYTES,
    content_has_secret_refs,
    is_editable_extension,
    is_excluded_path,
    resolve_confined,
    resolve_root_base,
    soft_trash_destination,
    validate_utf8_text,
    workspace_relative_posix,
)
from sevn.workspace.layout import WorkspaceLayout

router = APIRouter(prefix="/files", tags=["dashboard-files"])

_SECRET_REF_SUB = re.compile(r"\$\{SECRET:[^}]+\}")


class FileContentPutBody(BaseModel):
    """Body for ``PUT /files/content``."""

    path: str = Field(min_length=1)
    content: str = ""
    create_parents: bool = False


class FileCreateBody(BaseModel):
    """Body for ``POST /files``."""

    path: str = Field(min_length=1)
    content: str = ""


class FileRenameBody(BaseModel):
    """Body for ``POST /files/rename``."""

    model_config = ConfigDict(populate_by_name=True)

    from_path: str = Field(alias="from", min_length=1)
    to: str = Field(min_length=1)


def _forbidden() -> HTTPException:
    """Return a standard path confinement HTTP 403.

    Returns:
        HTTPException: Forbidden response.

    Examples:
        >>> _forbidden().status_code
        403
    """
    return HTTPException(status_code=403, detail="path_forbidden")


def _resolve_content_path(
    path: str,
    layout: WorkspaceLayout,
    workspace: WorkspaceConfig,
    *,
    for_write: bool,
) -> Path:
    """Resolve and validate a workspace-relative path for read or write.

    Args:
        path (str): Workspace-relative path.
        layout (WorkspaceLayout): Workspace layout.
        workspace (WorkspaceConfig): Parsed config.
        for_write (bool): Apply write guards when ``True``.

    Returns:
        Path: Resolved absolute path.

    Raises:
        HTTPException: ``403`` when confinement fails.

    Examples:
        >>> import inspect
        >>> _resolve_content_path.__name__
        '_resolve_content_path'
    """
    candidate = resolve_confined(path, layout, workspace, for_write=for_write)
    if candidate is None:
        raise _forbidden()
    return candidate


def _file_metadata(path: Path) -> dict[str, Any]:
    """Return size and mtime metadata for one path.

    Args:
        path (Path): Existing file path.

    Returns:
        dict[str, Any]: Size bytes and ``mtime_ns``.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> p = Path(tempfile.mkdtemp()) / "a.txt"
        >>> _ = p.write_text("x", encoding="utf-8")
        >>> "size" in _file_metadata(p)
        True
    """
    stat = path.stat()
    return {
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _list_tree(
    layout: WorkspaceLayout,
    workspace: WorkspaceConfig,
    root_key: str,
    rel_dir: str,
) -> dict[str, Any]:
    """Build a confined directory listing for one root key.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        workspace (WorkspaceConfig): Parsed config.
        root_key (str): Tree root key.
        rel_dir (str): Directory relative to root base.

    Returns:
        dict[str, Any]: Tree payload with entry rows.

    Raises:
        ValueError: When ``rel_dir`` is not a directory.

    Examples:
        >>> import inspect
        >>> _list_tree.__name__
        '_list_tree'
    """
    base = resolve_root_base(root_key, layout, workspace)
    if base is None:
        msg = f"invalid root: {root_key}"
        raise ValueError(msg)
    if root_key == "graphify":
        entries: list[dict[str, Any]] = []
        if base.is_dir():
            for child in sorted(base.iterdir(), key=lambda p: p.name.lower()):
                if child.name.startswith("."):
                    continue
                kind = "dir" if child.is_dir() else "file"
                meta = _file_metadata(child) if child.is_file() else {"size": 0, "mtime_ns": 0}
                entries.append(
                    {
                        "name": child.name,
                        "kind": kind,
                        "size": meta["size"],
                        "mtime_ns": meta["mtime_ns"],
                    },
                )
        return {"root": root_key, "path": rel_dir or ".", "entries": entries}

    if rel_dir in (".", ""):
        target = base
    else:
        resolved = resolve_confined(rel_dir, layout, workspace, root_key=root_key)
        if resolved is None or not resolved.is_dir():
            msg = f"not a directory: {rel_dir}"
            raise ValueError(msg)
        target = resolved

    content_root = layout.content_root.resolve()
    children = filter_visible_entries(content_root, target)
    entries = []
    for child in children:
        if is_excluded_path(child, content_root):
            continue
        kind = "dir" if child.is_dir() else "file"
        stat = child.stat()
        entries.append(
            {
                "name": child.name,
                "kind": kind,
                "size": stat.st_size if child.is_file() else 0,
                "mtime_ns": stat.st_mtime_ns,
            },
        )
    display = "."
    if target != base:
        try:
            display = target.relative_to(base).as_posix() or "."
        except ValueError:
            display = rel_dir
    return {"root": root_key, "path": display, "entries": entries}


def _read_file(path: Path, content_root: Path) -> dict[str, Any]:
    """Read one UTF-8 text file with size and redaction metadata.

    Args:
        path (Path): Resolved file path.
        content_root (Path): Workspace content root.

    Returns:
        dict[str, Any]: File body and metadata for JSON responses.

    Raises:
        ValueError: When path is not a file or encoding is invalid.
        OSError: When file exceeds size cap.

    Examples:
        >>> import inspect
        >>> _read_file.__name__
        '_read_file'
    """
    if not path.is_file():
        raise ValueError("not a file")
    raw = path.read_bytes()
    if len(raw) > MAX_FILE_BYTES:
        msg = f"file exceeds {MAX_FILE_BYTES} byte limit"
        raise OSError(msg)
    text = validate_utf8_text(raw)
    if text is None:
        msg = "invalid_encoding: binary or non-UTF-8 content"
        raise ValueError(msg)
    redacted = content_has_secret_refs(text)
    display = text
    if redacted:
        display = _SECRET_REF_SUB.sub("<redacted-secret-ref>", text)
    rel = workspace_relative_posix(path, content_root)
    meta = _file_metadata(path)
    return {
        "path": rel,
        "size": meta["size"],
        "mtime_ns": meta["mtime_ns"],
        "encoding": "utf-8",
        "content": display,
        "redacted": redacted,
    }


def _write_file(
    path: Path,
    content: str,
    *,
    create_parents: bool,
    content_root: Path,
) -> dict[str, Any]:
    """Write UTF-8 text to ``path`` with editor extension checks.

    Args:
        path (Path): Target file path.
        content (str): UTF-8 text body.
        create_parents (bool): Create parent directories when ``True``.
        content_root (Path): Workspace content root for relative paths.

    Returns:
        dict[str, Any]: Written file metadata.

    Raises:
        ValueError: When extension or parent dir checks fail.
        OSError: When content exceeds size cap.

    Examples:
        >>> import inspect
        >>> _write_file.__name__
        '_write_file'
    """
    if not is_editable_extension(path):
        msg = "extension not allowed for text editor"
        raise ValueError(msg)
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_FILE_BYTES:
        msg = f"content exceeds {MAX_FILE_BYTES} byte limit"
        raise OSError(msg)
    if create_parents:
        path.parent.mkdir(parents=True, exist_ok=True)
    elif not path.parent.is_dir():
        msg = "parent directory missing"
        raise ValueError(msg)
    path.write_text(content, encoding="utf-8")
    rel = workspace_relative_posix(path, content_root)
    meta = _file_metadata(path)
    return {"path": rel, "size": meta["size"], "mtime_ns": meta["mtime_ns"]}


@router.get("/tree")
async def files_tree(
    request: Request,
    root: str = Query(default="workspace"),
    path: str = Query(default="."),
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return a confined directory tree for the selected root key.

    Args:
        request (Request): FastAPI request with layout.
        root (str): Root key from :data:`ALLOWED_ROOT_KEYS`.
        path (str): Directory path relative to root base.
        _claims (DashboardClaims): Verified dashboard owner.

    Returns:
        dict[str, object]: Tree metadata without file bodies.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(files_tree)
        True
    """
    layout: WorkspaceLayout = request.app.state.layout
    workspace: WorkspaceConfig = request.app.state.workspace
    key = root.strip().lower()
    if key not in ALLOWED_ROOT_KEYS:
        raise HTTPException(status_code=422, detail=f"invalid root: {root}")
    try:
        body = await asyncio.to_thread(_list_tree, layout, workspace, key, path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return body


@router.get("/content")
async def files_content_get(
    request: Request,
    path: str = Query(min_length=1),
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Read one confined text file (secrets redacted in body).

    Args:
        request (Request): FastAPI request with layout.
        path (str): Workspace-relative file path.
        _claims (DashboardClaims): Verified dashboard owner.

    Returns:
        dict[str, object]: File metadata and UTF-8 content.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(files_content_get)
        True
    """
    layout: WorkspaceLayout = request.app.state.layout
    workspace: WorkspaceConfig = request.app.state.workspace
    abs_path = _resolve_content_path(path, layout, workspace, for_write=False)
    if abs_path.is_dir():
        raise HTTPException(status_code=422, detail="path is a directory")
    try:
        body = await asyncio.to_thread(_read_file, abs_path, layout.content_root.resolve())
    except ValueError as exc:
        if "invalid_encoding" in str(exc):
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    return body


@router.put("/content")
async def files_content_put(
    request: Request,
    body: FileContentPutBody,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> dict[str, object]:
    """Write text to a confined workspace path (owner+csrf).

    Args:
        request (Request): FastAPI request with layout and hub.
        body (FileContentPutBody): Target path and UTF-8 content.
        _claims (DashboardClaims): Verified dashboard owner.
        _csrf (None): CSRF guard.

    Returns:
        dict[str, object]: Updated file metadata.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(files_content_put)
        True
    """
    layout: WorkspaceLayout = request.app.state.layout
    workspace: WorkspaceConfig = request.app.state.workspace
    abs_path = _resolve_content_path(body.path, layout, workspace, for_write=True)
    try:
        result = await asyncio.to_thread(
            _write_file,
            abs_path,
            body.content,
            create_parents=body.create_parents,
            content_root=layout.content_root.resolve(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    await emit_mission_audit(
        request,
        kind="mission.file.write",
        path=str(result["path"]),
        byte_count=int(result["size"]),
        op="write",
    )
    return result


@router.post("")
async def files_create(
    request: Request,
    body: FileCreateBody,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Create a new confined file (owner+csrf).

    Args:
        request (Request): FastAPI request.
        body (FileCreateBody): New file path and optional content.
        _claims (DashboardClaims): Verified dashboard owner.
        _csrf (None): CSRF guard.

    Returns:
        JSONResponse: ``201`` with file metadata.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(files_create)
        True
    """
    layout: WorkspaceLayout = request.app.state.layout
    workspace: WorkspaceConfig = request.app.state.workspace
    abs_path = _resolve_content_path(body.path, layout, workspace, for_write=True)
    if abs_path.exists():
        raise HTTPException(status_code=409, detail="file already exists")
    try:
        result = await asyncio.to_thread(
            _write_file,
            abs_path,
            body.content,
            create_parents=True,
            content_root=layout.content_root.resolve(),
        )
    except (ValueError, OSError) as exc:
        status = 413 if isinstance(exc, OSError) else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    await emit_mission_audit(
        request,
        kind="mission.file.create",
        path=str(result["path"]),
        byte_count=int(result["size"]),
        op="create",
    )
    return JSONResponse(status_code=201, content=result)


@router.post("/rename")
async def files_rename(
    request: Request,
    body: FileRenameBody,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> dict[str, object]:
    """Rename a confined file or directory (owner+csrf).

    Args:
        request (Request): FastAPI request.
        body (FileRenameBody): Source and destination paths.
        _claims (DashboardClaims): Verified dashboard owner.
        _csrf (None): CSRF guard.

    Returns:
        dict[str, object]: Old and new workspace-relative paths.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(files_rename)
        True
    """
    layout: WorkspaceLayout = request.app.state.layout
    workspace: WorkspaceConfig = request.app.state.workspace
    src = _resolve_content_path(body.from_path, layout, workspace, for_write=True)
    dst = _resolve_content_path(body.to, layout, workspace, for_write=True)
    if not src.exists():
        raise HTTPException(status_code=404, detail="source missing")
    if dst.exists():
        raise HTTPException(status_code=409, detail="destination exists")
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    content_root = layout.content_root.resolve()
    dst_rel = workspace_relative_posix(dst, content_root)
    payload: dict[str, object] = {
        "from": body.from_path,
        "to": dst_rel,
    }
    await emit_mission_audit(
        request,
        kind="mission.file.rename",
        path=dst_rel,
        op="rename",
        extra={"from": payload["from"]},
    )
    return payload


@router.delete("")
async def files_delete(
    request: Request,
    path: str = Query(min_length=1),
    soft: bool = Query(default=True),
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> JSONResponse:
    """Soft-trash or hard-delete a confined path (owner+csrf).

    Args:
        request (Request): FastAPI request.
        path (str): Workspace-relative path.
        soft (bool): When ``True`` (default), move to ``.sevn/trash/``.
        _claims (DashboardClaims): Verified dashboard owner.
        _csrf (None): CSRF guard.

    Returns:
        JSONResponse: ``204`` or trash metadata.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(files_delete)
        True
    """
    layout: WorkspaceLayout = request.app.state.layout
    workspace: WorkspaceConfig = request.app.state.workspace
    abs_path = _resolve_content_path(path, layout, workspace, for_write=True)
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail="not found")
    content_root = layout.content_root.resolve()
    rel = workspace_relative_posix(abs_path, content_root)

    def _do_delete() -> dict[str, str] | None:
        if soft:
            trash = soft_trash_destination(content_root, rel)
            trash.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(abs_path), str(trash))
            return {"trashed_path": workspace_relative_posix(trash, content_root)}
        if abs_path.is_dir():
            shutil.rmtree(abs_path)
        else:
            abs_path.unlink()
        return None

    result = await asyncio.to_thread(_do_delete)
    await emit_mission_audit(
        request,
        kind="mission.file.delete",
        path=rel,
        op="delete",
        extra={"soft": soft},
    )
    if result is None:
        return JSONResponse(status_code=204, content=None)
    return JSONResponse(status_code=200, content=result)


__all__ = [
    "files_content_get",
    "files_content_put",
    "files_create",
    "files_delete",
    "files_rename",
    "files_tree",
    "router",
]
