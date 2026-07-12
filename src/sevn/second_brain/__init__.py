"""Second Brain wiki engine + tool registration (`specs/27-second-brain.md` section 2.1-2.2).

Exports:
    register_second_brain_tools — register native tools when ``second_brain.enabled``.
    wiki_search_tool — ``wiki_search`` tool callable.
    wiki_get_tool — ``wiki_get`` tool callable.
    wiki_apply_tool — ``wiki_apply`` tool callable.
    wiki_lint_tool — ``wiki_lint`` tool callable.
    second_brain_query_tool — ``second_brain_query`` tool callable.
    second_brain_ingest_stub_tool — legacy ``second_brain_ingest_stub`` (gated).
    legacy_native_second_brain_ingest_stub_enabled — transitional native stub flag.
"""

from __future__ import annotations

import uuid
from time import time_ns
from typing import Any

from sevn.agent.tracing.sink import TraceEvent
from sevn.config.loader import find_sevn_json, load_workspace
from sevn.config.workspace_config import WorkspaceConfig
from sevn.second_brain.errors import SecondBrainMergeNeededError, SecondBrainPathError
from sevn.second_brain.frontmatter import compose_page, normalise_agent_keys, split_frontmatter
from sevn.second_brain.ingest_stub import run_ingest_stub
from sevn.second_brain.lint_local import issues_to_json, lint_wiki_tree
from sevn.second_brain.paths import (
    display_scope_root_relative,
    effective_scope,
    legacy_shared_vault_root,
    resolve_scope_root,
    resolve_wiki_file,
    shared_wiki_root,
    wiki_dir_for_scope,
)
from sevn.second_brain.query import second_brain_query
from sevn.second_brain.search import wiki_search
from sevn.second_brain.wiki_io import wiki_apply_atomic, wiki_read
from sevn.second_brain.witchcraft_bridge import WitchcraftConfig, schedule_reindex_debounced
from sevn.tools.base import ToolExecutor, enveloped_failure, enveloped_success
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.decorator import sevn_tool, tool_from_decorated


async def _trace_sb(
    ctx: ToolContext,
    *,
    kind: str,
    status: str,
    attrs: dict[str, object],
) -> None:
    """Emit a trace event for Second Brain tool activity when tracing is enabled.

    Args:
        ctx (ToolContext): Tool execution context (trace sink and session ids).
        kind (str): Trace event kind label (e.g. ``second_brain.search``).
        status (str): Event status string (e.g. ``ok`` or ``error``).
        attrs (dict[str, object]): Additional span attributes merged into the event.

    Examples:
        >>> _trace_sb.__name__
        '_trace_sb'
    """
    if ctx.trace is None:
        return
    now = time_ns()
    await ctx.trace.emit(
        TraceEvent(
            kind=kind,
            span_id=uuid.uuid4().hex,
            parent_span_id=None,
            session_id=ctx.session_id,
            turn_id=ctx.turn_id,
            tier=ctx.executor_tier,
            ts_start_ns=now,
            ts_end_ns=now,
            status=status,
            attrs={
                "second_brain.tool": kind,
                **attrs,
            },
        ),
    )


def _load_sb(ctx: ToolContext) -> tuple[Any, Any, Any]:
    """Load workspace config and return Second Brain settings plus content root.

    Args:
        ctx (ToolContext): Tool context whose ``workspace_path`` locates ``sevn.json``.

    Returns:
        tuple[Any, Any, Any]: ``(workspace_cfg, second_brain_cfg, content_root)`` when enabled.

    Examples:
        >>> _load_sb.__name__
        '_load_sb'
    """
    sj = find_sevn_json(ctx.workspace_path)
    if sj is None:
        msg = "sevn.json not found — cannot resolve second_brain config"
        raise RuntimeError(msg)
    cfg, layout = load_workspace(sevn_json=sj)
    sb = cfg.second_brain
    if sb is None or not sb.enabled:
        msg = "second_brain is disabled in sevn.json"
        raise RuntimeError(msg)
    return cfg, sb, layout.content_root


def _shared_optional(sb: Any, content_root: Any) -> Any:
    """Return shared wiki root when topology uses shared overlay; else ``None``.

    Args:
        sb (Any): Parsed ``second_brain`` config (expects ``topology``).
        content_root (Any): Workspace content root used to resolve the vault.

    Returns:
        Any: Shared wiki :class:`~pathlib.Path` when ``topology`` is ``shared_core_overlay``;
        otherwise ``None``.

    Examples:
        >>> _shared_optional.__name__
        '_shared_optional'
    """
    if sb.topology == "shared_core_overlay":
        return shared_wiki_root(legacy_shared_vault_root(content_root))
    return None


@sevn_tool(
    name="wiki_search",
    category="second_brain",
    description="Search wiki pages by substring/TF rank; optional semantic when indexer fresh.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "scope": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            "mode": {
                "type": "string",
                "description": 'use "semantic" only when Witchcraft is fresh',
            },
        },
        "required": ["query"],
    },
    see_also=("second_brain",),
)
async def wiki_search_tool(
    ctx: ToolContext,
    query: str,
    scope: str | None = None,
    limit: int = 20,
    mode: str | None = None,
) -> str:
    """Search the wiki and return an enveloped JSON result string.

    Args:
        ctx (ToolContext): Tool execution context (workspace, tracing, ids).
        query (str): Substring / ranking query text.
        scope (str | None): Scope id (e.g. ``owner``); defaults from config when omitted.
        limit (int): Maximum hits (clamped by the implementation).
        mode (str | None): Pass ``semantic`` only when Witchcraft index is fresh.

    Returns:
        str: Enveloped success or failure JSON for the gateway.

    Examples:
        >>> wiki_search_tool.__name__
        'wiki_search_tool'
    """
    cfg, sb, root = _load_sb(ctx)
    sc = effective_scope(scope, sb)
    scope_path = resolve_scope_root(root, sb, sc)
    wiki = wiki_dir_for_scope(scope_path)
    shared = _shared_optional(sb, root)
    wc_cfg = WitchcraftConfig.from_workspace_config(cfg)
    await _trace_sb(
        ctx,
        kind="second_brain.search",
        status="ok",
        attrs={"second_brain.scope": sc, "second_brain.paths_touched": []},
    )
    rows = wiki_search(
        query=query,
        user_wiki=wiki,
        shared_wiki=shared,
        limit=limit,
        mode=mode,
        use_witchcraft=(mode or "").lower() == "semantic",
        witchcraft_cfg=wc_cfg,
        workspace_path=root,
    )
    return enveloped_success({"results": rows})


@sevn_tool(
    name="wiki_get",
    category="second_brain",
    description="Read one wiki page (path relative to wiki/) with frontmatter.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string"}, "scope": {"type": "string"}},
        "required": ["path"],
    },
    see_also=("second_brain",),
)
async def wiki_get_tool(ctx: ToolContext, path: str, scope: str | None = None) -> str:
    """Read one wiki page (path under ``wiki/``) and return enveloped JSON.

    Args:
        ctx (ToolContext): Tool execution context.
        path (str): Wiki-relative path to the markdown file.
        scope (str | None): Scope id; defaults from config when omitted.

    Returns:
        str: Enveloped JSON with body and frontmatter, or a validation error.

    Examples:
        >>> wiki_get_tool.__name__
        'wiki_get_tool'
    """
    _cfg, sb, root = _load_sb(ctx)
    sc = effective_scope(scope, sb)
    scope_path = resolve_scope_root(root, sb, sc)
    wiki = wiki_dir_for_scope(scope_path)
    try:
        target = resolve_wiki_file(wiki_root=wiki, workspace_root=root, rel_path=path)
    except SecondBrainPathError as exc:
        return enveloped_failure(str(exc), code=ToolResultCode.VALIDATION_ERROR)
    if not target.is_file():
        return enveloped_failure(f"not found: {path}", code=ToolResultCode.VALIDATION_ERROR)
    _, fm, body = wiki_read(target)
    await _trace_sb(
        ctx,
        kind="second_brain.query",
        status="ok",
        attrs={
            "second_brain.scope": sc,
            "second_brain.paths_touched": [str(target.relative_to(root))],
        },
    )
    return enveloped_success({"path": path, "body": body, "frontmatter": fm})


@sevn_tool(
    name="wiki_apply",
    category="second_brain",
    description="Atomic wiki write; full-file patch string; rejects on base_hash mismatch.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "patch": {"type": "string"},
            "base_hash": {"type": "string"},
            "scope": {"type": "string"},
        },
        "required": ["path", "patch", "base_hash"],
    },
    see_also=("second_brain",),
)
async def wiki_apply_tool(
    ctx: ToolContext,
    path: str,
    patch: str,
    base_hash: str,
    scope: str | None = None,
) -> str:
    """Apply a full-file wiki patch atomically; return enveloped JSON.

    Args:
        ctx (ToolContext): Tool execution context.
        path (str): Wiki-relative path to write.
        patch (str): Complete new file text including frontmatter fence.
        base_hash (str): Expected SHA-256 hex of current on-disk bytes.
        scope (str | None): Scope id; defaults from config when omitted.

    Returns:
        str: Enveloped success, merge-needed, or validation JSON.

    Examples:
        >>> wiki_apply_tool.__name__
        'wiki_apply_tool'
    """
    cfg, sb, root = _load_sb(ctx)
    sc = effective_scope(scope, sb)
    scope_path = resolve_scope_root(root, sb, sc)
    wiki = wiki_dir_for_scope(scope_path)
    try:
        target = resolve_wiki_file(wiki_root=wiki, workspace_root=root, rel_path=path)
    except SecondBrainPathError as exc:
        return enveloped_failure(str(exc), code=ToolResultCode.VALIDATION_ERROR)
    fm_in, body_in, _ = split_frontmatter(patch)
    merged_fm = normalise_agent_keys(fm_in)
    composed = compose_page(merged_fm, body_in)
    try:
        wiki_apply_atomic(path=target, patch=composed, base_hash=base_hash, workspace_root=root)
    except SecondBrainMergeNeededError as exc:
        await _trace_sb(
            ctx,
            kind="second_brain.merge_needed",
            status="error",
            attrs={
                "second_brain.scope": sc,
                "second_brain.merge_needed": True,
                "second_brain.paths_touched": [str(target.relative_to(root))],
            },
        )
        return enveloped_failure(
            str(exc),
            code=ToolResultCode.MERGE_NEEDED,
            data={"merge_needed": True, "path": path},
        )
    except SecondBrainPathError as exc:
        return enveloped_failure(str(exc), code=ToolResultCode.VALIDATION_ERROR)
    await _trace_sb(
        ctx,
        kind="second_brain.ingest",
        status="ok",
        attrs={
            "second_brain.scope": sc,
            "second_brain.paths_touched": [str(target.relative_to(root))],
        },
    )
    wc_cfg = WitchcraftConfig.from_workspace_config(cfg)
    shared = _shared_optional(sb, root)
    await schedule_reindex_debounced(
        wiki, witchcraft_cfg=wc_cfg, workspace_path=root, shared_wiki=shared
    )
    return enveloped_success({"path": path, "written": True})


@sevn_tool(
    name="wiki_lint",
    category="second_brain",
    description="Lint wiki for orphan links, missing OKF type, missing sources, stale freshness.",
    parameters={
        "type": "object",
        "properties": {
            "scope_root": {"type": "string", "description": "Scope id (e.g. owner)"},
            "rules": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["scope_root"],
    },
    see_also=("second_brain",),
)
async def wiki_lint_tool(
    ctx: ToolContext,
    scope_root: str,
    rules: list[str] | None = None,
) -> str:
    """Lint wiki files under a scope; return enveloped JSON with issues.

    Args:
        ctx (ToolContext): Tool execution context.
        scope_root (str): Scope id (e.g. ``owner``).
        rules (list[str] | None): Reserved for future rule filters (ignored today).

    Returns:
        str: Enveloped JSON listing lint issues.

    Examples:
        >>> wiki_lint_tool.__name__
        'wiki_lint_tool'
    """
    _ = rules
    _cfg, sb, root = _load_sb(ctx)
    sc = effective_scope(scope_root, sb)
    scope_path = resolve_scope_root(root, sb, sc)
    wiki = wiki_dir_for_scope(scope_path)
    issues = lint_wiki_tree(wiki)
    await _trace_sb(
        ctx,
        kind="second_brain.lint",
        status="ok",
        attrs={
            "second_brain.scope": sc,
            "second_brain.paths_touched": [],
        },
    )
    return enveloped_success({"issues": issues_to_json(issues)})


@sevn_tool(
    name="second_brain_query",
    category="second_brain",
    description="Query wiki: index.md first, then bodies; optional shared union.",
    parameters={
        "type": "object",
        "properties": {
            "q": {"type": "string"},
            "scope": {"type": "string"},
            "include_shared": {"type": "boolean"},
            "use_witchcraft": {"type": "boolean"},
            "limit": {"type": "integer"},
        },
        "required": ["q", "scope"],
    },
    see_also=("second_brain",),
)
async def second_brain_query_tool(
    ctx: ToolContext,
    q: str,
    scope: str,
    include_shared: bool = True,
    use_witchcraft: bool = False,
    limit: int = 20,
) -> str:
    """Query wiki (index-first, then ranked search); return enveloped JSON.

    Args:
        ctx (ToolContext): Tool execution context.
        q (str): Query text.
        scope (str): Scope id for the user wiki root.
        include_shared (bool): Whether to union shared wiki hits when configured.
        use_witchcraft (bool): Whether to request semantic ranking when allowed.
        limit (int): Maximum rows returned (clamped by the implementation).

    Returns:
        str: Enveloped JSON with ``results`` rows.

    Examples:
        >>> second_brain_query_tool.__name__
        'second_brain_query_tool'
    """
    cfg, sb, root = _load_sb(ctx)
    sc = effective_scope(scope, sb)
    scope_path = resolve_scope_root(root, sb, sc)
    wiki = wiki_dir_for_scope(scope_path)
    shared = _shared_optional(sb, root) if include_shared else None
    wc_cfg = WitchcraftConfig.from_workspace_config(cfg)
    rows = second_brain_query(
        q=q,
        user_wiki=wiki,
        shared_wiki=shared,
        include_shared=include_shared,
        use_witchcraft=use_witchcraft,
        limit=limit,
        witchcraft_cfg=wc_cfg,
        workspace_path=root,
    )
    await _trace_sb(
        ctx,
        kind="second_brain.query",
        status="ok",
        attrs={"second_brain.scope": sc, "second_brain.paths_touched": []},
    )
    return enveloped_success({"results": rows})


@sevn_tool(
    name="second_brain_ingest_stub",
    category="second_brain",
    description="Idempotent stub page under wiki/ingests from a raw/ relative path.",
    parameters={
        "type": "object",
        "properties": {
            "raw_relpath": {"type": "string"},
            "scope": {"type": "string"},
        },
        "required": ["raw_relpath", "scope"],
    },
    see_also=("second_brain",),
)
async def second_brain_ingest_stub_tool(
    ctx: ToolContext,
    raw_relpath: str,
    scope: str,
) -> str:
    """Run idempotent stub ingest from ``raw/``; return enveloped JSON.

    Args:
        ctx (ToolContext): Tool execution context (session ids label provenance).
        raw_relpath (str): Path relative to the scope ``raw/`` directory.
        scope (str): Scope id for vault resolution.

    Returns:
        str: Enveloped JSON with ingest metadata or a validation error.

    Examples:
        >>> second_brain_ingest_stub_tool.__name__
        'second_brain_ingest_stub_tool'
    """
    _cfg, sb, root = _load_sb(ctx)
    sc = effective_scope(scope, sb)
    scope_path = resolve_scope_root(root, sb, sc)
    sevn_src = f"session:{ctx.session_id}:{ctx.turn_id}"
    try:
        out = run_ingest_stub(
            workspace_root=root,
            vault_users_scope=scope_path,
            raw_relpath=raw_relpath,
            sevn_source=sevn_src,
        )
    except (SecondBrainPathError, OSError, FileNotFoundError) as exc:
        return enveloped_failure(str(exc), code=ToolResultCode.VALIDATION_ERROR)
    await _trace_sb(
        ctx,
        kind="second_brain.ingest",
        status="ok",
        attrs={
            "second_brain.scope": sc,
            "second_brain.paths_touched": [
                f"{display_scope_root_relative(root, scope_path)}/wiki/{out['path']}"
            ],
        },
    )
    return enveloped_success(out)


_SECOND_BRAIN_TOOLS: tuple[Any, ...] = (
    wiki_search_tool,
    wiki_get_tool,
    wiki_apply_tool,
    wiki_lint_tool,
    second_brain_query_tool,
    second_brain_ingest_stub_tool,
)


def legacy_native_second_brain_ingest_stub_enabled(
    workspace_config: WorkspaceConfig | None,
) -> bool:
    """Return whether transitional native ``second_brain_ingest_stub`` should register.

    The bundled ``second_brain`` skill ``ingest`` script owns ingest in v1. Native
    ``second_brain_ingest_stub`` registers only when
    ``tools.legacy_native.second_brain_ingest_stub.enabled`` is true (default **false**).

    Args:
        workspace_config (WorkspaceConfig | None): Parsed workspace config.

    Returns:
        bool: ``True`` when the legacy ingest stub native tool should register.

    Examples:
        >>> from sevn.config.workspace_config import parse_workspace_config
        >>> cfg = parse_workspace_config({"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}})
        >>> legacy_native_second_brain_ingest_stub_enabled(cfg)
        False
        >>> cfg2 = parse_workspace_config({
        ...     "schema_version": 1,
        ...     "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        ...     "tools": {"legacy_native": {"second_brain_ingest_stub": {"enabled": True}}},
        ... })
        >>> legacy_native_second_brain_ingest_stub_enabled(cfg2)
        True
    """
    if workspace_config is None or workspace_config.tools is None:
        return False
    legacy = workspace_config.tools.get("legacy_native")
    if not isinstance(legacy, dict):
        return False
    stub = legacy.get("second_brain_ingest_stub")
    if not isinstance(stub, dict):
        return False
    return bool(stub.get("enabled", False))


def register_second_brain_tools(
    executor: ToolExecutor,
    workspace_config: WorkspaceConfig | None,
) -> None:
    """Register Second Brain native tools when ``second_brain.enabled`` (`specs/27` §2.1).

    Args:
        executor (ToolExecutor): Registry to append ``FunctionTool`` rows into.
        workspace_config (WorkspaceConfig | None): Parsed workspace; ``None`` skips registration.

    Examples:
        >>> from sevn.tools.base import ToolExecutor
        >>> register_second_brain_tools(ToolExecutor(default_timeout_seconds=None), None)
    """

    sb = workspace_config.second_brain if workspace_config else None
    if sb is None or not sb.enabled:
        return
    tools = _SECOND_BRAIN_TOOLS
    if not legacy_native_second_brain_ingest_stub_enabled(workspace_config):
        tools = tuple(t for t in _SECOND_BRAIN_TOOLS if t is not second_brain_ingest_stub_tool)
    for fn in tools:
        executor.register(tool_from_decorated(fn))


__all__ = [
    "legacy_native_second_brain_ingest_stub_enabled",
    "register_second_brain_tools",
    "second_brain_ingest_stub_tool",
    "second_brain_query_tool",
    "wiki_apply_tool",
    "wiki_get_tool",
    "wiki_lint_tool",
    "wiki_search_tool",
]
