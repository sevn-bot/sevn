"""Mission Control Knowledge group REST router (`specs/24-dashboard.md` MC-8).

Module: sevn.ui.dashboard.api.knowledge
Depends: asyncio, json, re, sqlite3, fastapi, sevn.cli.repo_sync, sevn.code_understanding.bootstrap,
    sevn.code_understanding.effective_settings, sevn.code_understanding.graphify,
    sevn.config.defaults, sevn.memory.user_model.store, sevn.second_brain.paths,
    sevn.tools.file_ops.list_glob, sevn.tools.paths, sevn.ui.dashboard.api.deps

Exports:
    memory_overview — SQLite memory rows, MEMORY.md preview, user model summary.
    second_brain_overview — vault layout, wiki index, scope listing.
    workspace_files_list — redacted directory listing (``list_dir`` semantics).
    code_understanding_index — MYCODE / Graphify / layer toggles + doctor warnings.
    knowledge_graph — read-only graphify nodes/edges payload.
"""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from sevn.cli.repo_sync import resolve_sevn_repo_root
from sevn.code_understanding.bootstrap import (
    code_orientation_doctor_checks,
    mycode_needs_refresh,
)
from sevn.code_understanding.effective_settings import (
    effective_code_understanding,
    effective_graphify_settings,
    graphify_enabled_for_checkout,
)
from sevn.code_understanding.graphify import graph_json_path, graph_report_path, resolve_profiles
from sevn.config.defaults import DEFAULT_SECOND_BRAIN_ENABLED
from sevn.config.workspace_config import WorkspaceConfig
from sevn.memory.user_model.store import UserModelStore
from sevn.second_brain.paths import (
    display_scope_root_relative,
    effective_scope,
    resolve_scope_root,
    vault_root,
    wiki_dir_for_scope,
)
from sevn.tools.file_ops.list_glob import MAX_LISTING_RESULTS, _entry_metadata
from sevn.tools.paths import (
    WorkspacePathError,
    filter_visible_entries,
    resolve_workspace_relative_path,
)
from sevn.ui.dashboard.api.deps import require_dashboard_owner
from sevn.ui.dashboard.services.auth import DashboardClaims
from sevn.ui.dashboard.services.workspace_fs import graph_json_for_workspace
from sevn.workspace.layout import WorkspaceLayout

router = APIRouter(prefix="/knowledge", tags=["dashboard-knowledge"])

_SENSITIVE_KEY_RE = re.compile(r"(token|secret|password|api[_-]?key|credential|jwt)", re.IGNORECASE)
_SENSITIVE_NAME_RE = re.compile(
    r"(\.env($|\.)|id_rsa|\.pem$|credentials|secrets?\.(json|ya?ml)|\.key$)",
    re.IGNORECASE,
)
_MEMORY_PREVIEW_CHARS = 240
_MEMORY_MD_PREVIEW_CHARS = 4000
_WIKI_PAGE_LIMIT = 200
_MEMORY_ROW_LIMIT = 100


def _error_response(
    code: str,
    message: str,
    *,
    status_code: int,
) -> JSONResponse:
    """Return a structured dashboard error envelope.

    Args:
        code (str): Stable error code.
        message (str): Human-readable message.
        status_code (int): HTTP status.

    Returns:
        JSONResponse: Error body.

    Examples:
        >>> _error_response("x", "y", status_code=400).status_code
        400
    """

    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": {}}},
    )


def _redact_text(value: str, *, key_hint: str = "") -> str:
    """Truncate and redact sensitive memory or markdown snippets.

    Args:
        value (str): Raw text.
        key_hint (str): Optional memory key for sensitivity heuristics.

    Returns:
        str: Safe preview for Mission Control.

    Examples:
        >>> _redact_text("hello", key_hint="note")
        'hello'
        >>> _redact_text("x" * 300, key_hint="api_key")
        '<redacted>'
    """

    if _SENSITIVE_KEY_RE.search(key_hint):
        return "<redacted>"
    trimmed = value.strip()
    if len(trimmed) > _MEMORY_PREVIEW_CHARS:
        trimmed = trimmed[:_MEMORY_PREVIEW_CHARS] + "…"
    if _SENSITIVE_KEY_RE.search(trimmed):
        return "<redacted>"
    return trimmed


def _list_memory_rows(conn: sqlite3.Connection, *, limit: int) -> list[dict[str, Any]]:
    """Return recent short-term memory rows (newest first).

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle.
        limit (int): Maximum rows.

    Returns:
        list[dict[str, Any]]: Redacted row payloads.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> _list_memory_rows(c, limit=5) == []
        True
        >>> c.close()
    """

    cur = conn.execute(
        """
        SELECT id, key, session_id, content, tags, created_at, metadata
        FROM memory
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows: list[dict[str, Any]] = []
    for rid, mem_key, sid, content, tags, created_at, metadata in cur.fetchall():
        key_str = str(mem_key)
        rows.append(
            {
                "id": int(rid),
                "key": key_str,
                "session_id": str(sid),
                "content_preview": _redact_text(str(content), key_hint=key_str),
                "tags": str(tags) if tags is not None else None,
                "created_at": str(created_at),
                "metadata": str(metadata) if metadata is not None else None,
            },
        )
    return rows


def _memory_md_preview(content_root: Path) -> dict[str, Any]:
    """Summarise workspace ``MEMORY.md`` without dumping full long-term memory.

    Args:
        content_root (Path): Workspace content root.

    Returns:
        dict[str, Any]: Presence, size, and redacted preview.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> root = Path(tempfile.mkdtemp())
        >>> body = _memory_md_preview(root)
        >>> body["present"]
        False
    """

    path = content_root / "MEMORY.md"
    if not path.is_file():
        return {
            "present": False,
            "path": "MEMORY.md",
            "size_bytes": 0,
            "line_count": 0,
            "preview": "",
        }
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    preview = text[:_MEMORY_MD_PREVIEW_CHARS]
    if len(text) > _MEMORY_MD_PREVIEW_CHARS:
        preview += "…"
    return {
        "present": True,
        "path": "MEMORY.md",
        "size_bytes": path.stat().st_size,
        "line_count": len(lines),
        "preview": _redact_text(preview),
    }


def _user_model_summary(content_root: Path) -> dict[str, Any]:
    """Return Honcho-style profile metadata (no raw transcript fields).

    Args:
        content_root (Path): Workspace content root.

    Returns:
        dict[str, Any]: Fact counts and topic listing.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> _user_model_summary(Path(tempfile.mkdtemp()))["fact_count"]
        0
    """

    store = UserModelStore()
    profile = store.load(str(content_root))
    active = [f for f in profile.facts if not f.superseded_by_id]
    topics = sorted({f.topic for f in active})
    return {
        "present": bool(active),
        "path": ".sevn/user_model.json",
        "updated_at": profile.updated_at.isoformat(),
        "fact_count": len(active),
        "topics": topics[:50],
    }


def _memory_config_flags(workspace: WorkspaceConfig) -> dict[str, Any]:
    """Expose non-secret ``memory.*`` toggles for the Memory tab.

    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.

    Returns:
        dict[str, Any]: Enabled flags and dreaming/user_model presence.

    Examples:
        >>> _memory_config_flags(WorkspaceConfig.minimal())["section_present"]
        False
    """

    mem = workspace.memory
    if mem is None:
        return {"section_present": False}
    dreaming = mem.dreaming
    user_model = mem.user_model
    return {
        "section_present": True,
        "dreaming_enabled": bool(dreaming.enabled) if dreaming is not None else None,
        "user_model_enabled": bool(user_model.enabled) if user_model is not None else None,
        "lcm_enabled": bool(workspace.lcm.enabled) if workspace.lcm is not None else None,
    }


def _second_brain_enabled(workspace: WorkspaceConfig) -> bool:
    """Return effective ``second_brain.enabled``.

    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.

    Returns:
        bool: Whether Second Brain is on.

    Examples:
        >>> _second_brain_enabled(WorkspaceConfig.minimal()) == DEFAULT_SECOND_BRAIN_ENABLED
        True
    """

    sb = workspace.second_brain
    if sb is None:
        return DEFAULT_SECOND_BRAIN_ENABLED
    return bool(sb.enabled)


def _list_wiki_pages(wiki_root: Path, *, limit: int) -> list[dict[str, Any]]:
    """Collect wiki ``*.md`` paths under ``wiki_root`` (relative POSIX).

    Args:
        wiki_root (Path): Resolved ``wiki/`` directory.
        limit (int): Maximum pages.

    Returns:
        list[dict[str, Any]]: Page metadata rows.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> _list_wiki_pages(Path(tempfile.mkdtemp()) / "missing", limit=5)
        []
    """

    if not wiki_root.is_dir():
        return []
    pages: list[dict[str, Any]] = []
    for path in sorted(wiki_root.rglob("*.md")):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(wiki_root.resolve()).as_posix()
        except ValueError:
            continue
        stat = path.stat()
        pages.append(
            {
                "path": rel,
                "size_bytes": stat.st_size,
                "modified_unix_s": int(stat.st_mtime),
            },
        )
        if len(pages) >= limit:
            break
    return pages


def _second_brain_scopes(vault: Path) -> list[str]:
    """List scope directory names under ``vault/users``.

    Args:
        vault (Path): Resolved vault root.

    Returns:
        list[str]: Scope ids.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.second_brain.paths import vault_root
        >>> v = vault_root(Path(tempfile.mkdtemp()))
        >>> _second_brain_scopes(v)
        []
    """

    users = vault / "users"
    if not users.is_dir():
        return []
    return sorted(
        child.name for child in users.iterdir() if child.is_dir() and child.name not in (".", "..")
    )


def _index_excerpt(wiki_root: Path, *, max_chars: int = 1200) -> str:
    """Return a short ``index.md`` excerpt when present.

    Args:
        wiki_root (Path): Scope ``wiki/`` root.
        max_chars (int): Maximum characters.

    Returns:
        str: Redacted excerpt or empty string.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> _index_excerpt(Path(tempfile.mkdtemp()) / "wiki")
        ''
    """

    index = wiki_root / "index.md"
    if not index.is_file():
        return ""
    text = index.read_text(encoding="utf-8", errors="replace")
    excerpt = text[:max_chars]
    if len(text) > max_chars:
        excerpt += "…"
    return _redact_text(excerpt)


def _workspace_entry_row(
    workspace: Path,
    child: Path,
) -> dict[str, Any]:
    """Build one listing row with redaction flags for sensitive names.

    Args:
        workspace (Path): Workspace content root.
        child (Path): Resolved child path.

    Returns:
        dict[str, Any]: Metadata row for Mission Control.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> ws = Path(tempfile.mkdtemp())
        >>> f = ws / ".env"
        >>> _ = f.write_text("x", encoding="utf-8")
        >>> row = _workspace_entry_row(ws, f.resolve())
        >>> row["redacted"]
        True
    """

    meta = _entry_metadata(workspace, child)
    name = str(meta.get("name") or child.name)
    rel = str(meta.get("path") or name)
    redacted = bool(_SENSITIVE_NAME_RE.search(name) or _SENSITIVE_NAME_RE.search(rel))
    if redacted:
        meta["redacted"] = True
        if meta.get("type") == "file":
            meta["size"] = None
    else:
        meta["redacted"] = False
    return meta


def _list_workspace_directory(
    layout: WorkspaceLayout,
    rel_path: str,
    *,
    limit: int,
) -> dict[str, Any]:
    """List one workspace directory with ``list_dir`` visibility rules.

    Args:
        layout (WorkspaceLayout): Resolved workspace paths.
        rel_path (str): Workspace-relative directory.
        limit (int): Maximum entries.

    Returns:
        dict[str, Any]: Path, entries, and truncation flag.

    Raises:
        WorkspacePathError: When the path is invalid.
        PermissionError: When the path is under ``.llmignore``.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> base = Path(tempfile.mkdtemp())
        >>> cfg = WorkspaceConfig.minimal(workspace_root=".")
        >>> sevn_json = base / "sevn.json"
        >>> _ = sevn_json.write_text('{"schema_version": 1}', encoding="utf-8")
        >>> lay = WorkspaceLayout.from_config(sevn_json, cfg)
        >>> body = _list_workspace_directory(lay, ".", limit=10)
        >>> body["count"] >= 0
        True
    """

    root = layout.content_root
    target = resolve_workspace_relative_path(root, rel_path or ".")
    if not target.is_dir():
        msg = f"not a directory: {rel_path or '.'}"
        raise WorkspacePathError(msg)
    children = filter_visible_entries(root, target)
    truncated = len(children) > limit
    visible = children[:limit]
    entries = [_workspace_entry_row(root, child) for child in visible]
    rel_display = target.relative_to(root.expanduser().resolve()).as_posix() or "."
    return {
        "path": rel_display,
        "entries": entries,
        "count": len(entries),
        "truncated": truncated,
        "limit": limit,
    }


def _code_understanding_payload(workspace: WorkspaceConfig) -> dict[str, Any]:
    """Build read-only code-understanding index for Mission Control.

    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.

    Returns:
        dict[str, Any]: Layer toggles, checkout path, Graphify/MYCODE status.

    Examples:
        >>> body = _code_understanding_payload(WorkspaceConfig.minimal())
        >>> "warnings" in body
        True
    """

    checkout = resolve_sevn_repo_root()
    cu = effective_code_understanding(workspace, checkout)
    graphify = effective_graphify_settings(workspace, checkout)
    mycode = cu.mycode if cu is not None else None
    cgr = cu.code_graph_rag if cu is not None else None
    roam = cu.roam_code if cu is not None else None
    crg = cu.code_review_graph if cu is not None else None
    profiles: list[dict[str, Any]] = []
    if graphify_enabled_for_checkout(workspace, checkout):
        for profile in resolve_profiles(graphify, checkout):
            report = graph_report_path(profile)
            graph_json = graph_json_path(profile)
            profiles.append(
                {
                    "id": profile.id,
                    "root_path": profile.root_path,
                    "output_dir": profile.output_dir,
                    "graph_report_present": report.is_file(),
                    "graph_json_present": graph_json.is_file(),
                    "graph_report_path": str(report),
                },
            )
    mycode_path = (checkout / ".index/mycode/MYCODE.md") if checkout is not None else None
    return {
        "checkout": str(checkout) if checkout is not None else None,
        "warnings": code_orientation_doctor_checks(workspace, checkout),
        "mycode": {
            "enabled": bool(mycode.enabled) if mycode is not None else None,
            "path": str(mycode_path) if mycode_path is not None else None,
            "present": mycode_path.is_file() if mycode_path is not None else False,
            "needs_refresh": mycode_needs_refresh(checkout) if checkout is not None else None,
        },
        "graphify": {
            "enabled": graphify.enabled,
            "profiles": profiles,
        },
        "code_graph_rag": {
            "enabled": bool(cgr.enabled) if cgr is not None else None,
        },
        "roam_code": {
            "enabled": bool(roam.enabled) if roam is not None else None,
        },
        "code_review_graph": {
            "enabled": bool(crg.enabled) if crg is not None else None,
        },
    }


@router.get("/memory")
async def memory_overview(
    request: Request,
    limit: int = Query(default=50, ge=1, le=_MEMORY_ROW_LIMIT),
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return memory store rows, ``MEMORY.md`` preview, and user-model summary.

    Args:
        request (Request): FastAPI request with workspace and sqlite state.
        limit (int): Maximum SQLite memory rows.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Memory overview payload.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(memory_overview)
        True
    """

    workspace: WorkspaceConfig = request.app.state.workspace
    layout: WorkspaceLayout = request.app.state.layout
    conn: sqlite3.Connection = request.app.state.sqlite_conn
    rows = await asyncio.to_thread(_list_memory_rows, conn, limit=limit)
    md = await asyncio.to_thread(_memory_md_preview, layout.content_root)
    profile = await asyncio.to_thread(_user_model_summary, layout.content_root)
    return {
        "generated_at_ns": time.time_ns(),
        "config": _memory_config_flags(workspace),
        "sqlite_rows": rows,
        "sqlite_count": len(rows),
        "memory_md": md,
        "user_model": profile,
    }


@router.get("/second-brain")
async def second_brain_overview(
    request: Request,
    scope: str | None = Query(default=None),
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return Second Brain vault layout (wraps gateway ``/api/second_brain`` semantics).

    Args:
        request (Request): FastAPI request with workspace layout.
        scope (str | None): Optional scope override.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Vault paths, wiki pages, and gateway fetch hint.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(second_brain_overview)
        True
    """

    workspace: WorkspaceConfig = request.app.state.workspace
    layout: WorkspaceLayout = request.app.state.layout
    enabled = _second_brain_enabled(workspace)
    sb_cfg = workspace.second_brain
    scope_name = effective_scope(scope, sb_cfg)
    scope_root = resolve_scope_root(layout.content_root, sb_cfg, scope_name)
    wiki = wiki_dir_for_scope(scope_root)
    legacy_vault = vault_root(layout.content_root)

    def _build() -> dict[str, object]:
        pages = _list_wiki_pages(wiki, limit=_WIKI_PAGE_LIMIT)
        return {
            "enabled": enabled,
            "vault_path": str(scope_root),
            "vault_relative": display_scope_root_relative(layout.content_root, scope_root),
            "scope": scope_name,
            "scopes": _second_brain_scopes(legacy_vault),
            "wiki_path": str(wiki),
            "wiki_page_count": len(pages),
            "wiki_pages": pages,
            "index_excerpt": _index_excerpt(wiki),
            "gateway_fetch": "/api/second_brain/fetch",
        }

    body = await asyncio.to_thread(_build)
    body["generated_at_ns"] = time.time_ns()
    return body


@router.get("/workspace-files")
async def workspace_files_list(
    request: Request,
    path: str = Query(default="."),
    limit: int = Query(default=200, ge=1, le=MAX_LISTING_RESULTS),
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """List workspace files with ``list_dir`` visibility and name redaction.

    Args:
        request (Request): FastAPI request with layout.
        path (str): Workspace-relative directory.
        limit (int): Maximum entries.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Directory listing metadata (no file bodies).

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(workspace_files_list)
        True
    """

    layout: WorkspaceLayout = request.app.state.layout
    try:
        body = await asyncio.to_thread(
            _list_workspace_directory,
            layout,
            path,
            limit=limit,
        )
    except WorkspacePathError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    body["generated_at_ns"] = time.time_ns()
    return body


@router.get("/code-understanding")
async def code_understanding_index(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return code-understanding layer index and doctor warnings.

    Args:
        request (Request): FastAPI request with workspace config.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Layer toggles and artefact presence.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(code_understanding_index)
        True
    """

    workspace: WorkspaceConfig = request.app.state.workspace
    body = await asyncio.to_thread(_code_understanding_payload, workspace)
    body["generated_at_ns"] = time.time_ns()
    return body


def _load_graph_payload(layout: WorkspaceLayout, workspace: WorkspaceConfig) -> dict[str, Any]:
    """Load graphify nodes/edges when ``graph.json`` exists.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        workspace (WorkspaceConfig): Parsed config.

    Returns:
        dict[str, Any]: Graph payload or empty-state hint.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> cfg = WorkspaceConfig.minimal(workspace_root=".")
        >>> lay = WorkspaceLayout(Path("/tmp/w/sevn.json"), Path("/tmp/w"))
        >>> body = _load_graph_payload(lay, cfg)
        >>> "present" in body
        True
    """
    graph_path = graph_json_for_workspace(layout, workspace)
    if graph_path is None:
        return {
            "present": False,
            "hint": "Run `graphify update .` from the sevn checkout to build graphify-out/graph.json",
            "nodes": [],
            "edges": [],
        }
    try:
        doc = json.loads(graph_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "present": False,
            "hint": f"graph.json unreadable: {exc}",
            "nodes": [],
            "edges": [],
        }
    nodes = doc.get("nodes") if isinstance(doc.get("nodes"), list) else []
    edges = doc.get("edges") if isinstance(doc.get("edges"), list) else []
    return {
        "present": True,
        "path": str(graph_path),
        "nodes": nodes,
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
    }


@router.get("/graph")
async def knowledge_graph(
    request: Request,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, object]:
    """Return read-only graphify graph nodes/edges for MC visualization.

    Args:
        request (Request): FastAPI request with layout.
        _claims (DashboardClaims): Verified dashboard owner claims.

    Returns:
        dict[str, object]: Nodes, edges, or empty-state hint.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(knowledge_graph)
        True
    """
    layout: WorkspaceLayout = request.app.state.layout
    workspace: WorkspaceConfig = request.app.state.workspace
    body = await asyncio.to_thread(_load_graph_payload, layout, workspace)
    body["generated_at_ns"] = time.time_ns()
    return body


__all__ = [
    "code_understanding_index",
    "knowledge_graph",
    "memory_overview",
    "router",
    "second_brain_overview",
    "workspace_files_list",
]
