"""Witchcraft semantic search tool (`plan/tools-skills-full-inventory-wave-plan.md` Wave 7).

Bridges to :mod:`sevn.second_brain.witchcraft_bridge` when ``witchcraft_enabled`` is
true **and** the ``witchcraft`` binary is present on PATH with a fresh index (< 5 min).
Falls back silently to lexical-only when the indexer is unavailable.

Module: sevn.tools.semantic_search
Depends: sevn.config.workspace_config, sevn.second_brain.witchcraft_bridge, sevn.tools.base,
    sevn.tools.context, sevn.tools.decorator

Exports:
    semantic_search_tool — semantic search via Witchcraft bridge (requires binary + fresh index).
    register_semantic_search_tool — register only when enabled **and** indexer available.
    witchcraft_tool_enabled — config gate helper.
    run_semantic_search — testable bridge dispatch helper.

Examples:
    >>> from sevn.config.workspace_config import WorkspaceConfig
    >>> witchcraft_tool_enabled(
    ...     WorkspaceConfig.model_validate({
    ...         "schema_version": 1,
    ...         "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    ...         "witchcraft_enabled": True,
    ...     }),
    ... )
    True
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

from sevn.config.loader import find_sevn_json, load_workspace
from sevn.second_brain.witchcraft_bridge import (
    WitchcraftConfig,
    index_age_seconds,
    maybe_semantic_scores,
    semantic_mode_allowed,
    witchcraft_indexer_available,
)
from sevn.tools.base import enveloped_failure, enveloped_success
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.decorator import sevn_tool, tool_from_decorated

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.tools.base import ToolExecutor

SemanticMode = Literal["semantic", "bm25", "hybrid"]
SemanticSource = Literal["all", "summaries", "memory", "workspace", "messages"]
DEFAULT_SEMANTIC_SEARCH_LIMIT: Final[int] = 10
MAX_SEMANTIC_SEARCH_LIMIT: Final[int] = 50


def witchcraft_tool_enabled(workspace_config: WorkspaceConfig | None) -> bool:
    """Return whether ``semantic_search`` should register.

    Args:
        workspace_config (WorkspaceConfig | None): Parsed workspace config or mapping.

    Returns:
        bool: ``True`` when root ``witchcraft_enabled`` is truthy.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> witchcraft_tool_enabled(
        ...     WorkspaceConfig.model_validate({
        ...         "schema_version": 1,
        ...         "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        ...         "witchcraft_enabled": True,
        ...     }),
        ... )
        True
        >>> witchcraft_tool_enabled(WorkspaceConfig.minimal())
        False
    """
    if workspace_config is None:
        return False
    extra = workspace_config.model_extra or {}
    return bool(extra.get("witchcraft_enabled"))


def _wiki_root(workspace_path: Path) -> Path:
    """Return the default user wiki directory under ``workspace_path``.

    Args:
        workspace_path (Path): Workspace content root.

    Returns:
        Path: ``wiki/`` directory path.

    Examples:
        >>> from pathlib import Path
        >>> _wiki_root(Path("/tmp/w")) == Path("/tmp/w/wiki")
        True
    """
    return workspace_path / "wiki"


def run_semantic_search(
    workspace_path: Path,
    *,
    query: str,
    limit: int,
    mode: SemanticMode,
    source: SemanticSource,
    witchcraft_cfg: WitchcraftConfig | None = None,
) -> tuple[list[dict[str, Any]] | None, str | None, float | None]:
    """Execute the Witchcraft bridge search path when available.

    Args:
        workspace_path (Path): Workspace content root.
        query (str): Search query text.
        limit (int): Maximum hits to return.
        mode (SemanticMode): Search mode selector.
        source (SemanticSource): Corpus selector (reserved for indexer wiring).
        witchcraft_cfg (WitchcraftConfig | None): Parsed Witchcraft config for probe.

    Returns:
        tuple[list[dict[str, Any]] | None, str | None, float | None]: Hits, optional
        error message, and index age in seconds (or ``None`` when unavailable).

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> hits, err, age = run_semantic_search(
        ...     td, query="deploy", limit=5, mode="hybrid", source="all",
        ... )
        >>> hits is None and err is not None
        True
    """
    _ = (mode, source)
    age: float | None = None
    if witchcraft_cfg is not None:
        age = index_age_seconds(witchcraft_cfg, workspace_path)
    if not semantic_mode_allowed(witchcraft_cfg, workspace_path):
        return None, "Witchcraft semantic index unavailable or stale", age
    scores = maybe_semantic_scores(
        _wiki_root(workspace_path),
        query=query,
        _shared_wiki=None,
        witchcraft_cfg=witchcraft_cfg,
        workspace_path=workspace_path,
    )
    if scores is None:
        return None, "Witchcraft semantic index unavailable or stale", age
    hits: list[dict[str, Any]] = []
    for (origin, relpath), score in sorted(scores.items(), key=lambda item: item[1], reverse=True):
        hits.append({"origin": origin, "path": relpath, "score": score})
        if len(hits) >= limit:
            break
    return hits, None, age


@sevn_tool(
    name="semantic_search",
    category="memory",
    description=(
        "Semantic search via Witchcraft; requires witchcraft_enabled and a fresh index."
        " Falls back with DISABLED_TOOL when the indexer is unavailable."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Natural-language search query."},
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_SEMANTIC_SEARCH_LIMIT,
                "description": "Maximum hits (default 10).",
            },
            "mode": {
                "type": "string",
                "enum": ["semantic", "bm25", "hybrid"],
                "description": "Witchcraft retrieval mode (default hybrid).",
            },
            "source": {
                "type": "string",
                "enum": ["all", "summaries", "memory", "workspace", "messages"],
                "description": "Corpus selector (default all).",
            },
        },
        "required": ["query"],
    },
    abortable=True,
    see_also=("memory_search", "second_brain_query"),
)
async def semantic_search_tool(
    ctx: ToolContext,
    query: str,
    limit: int = DEFAULT_SEMANTIC_SEARCH_LIMIT,
    mode: SemanticMode = "hybrid",
    source: SemanticSource = "all",
) -> str:
    """Search via the Witchcraft bridge when the integration reports a fresh index.

    Args:
        ctx (ToolContext): Invocation context with ``workspace_path``.
        query (str): Natural-language query.
        limit (int): Maximum number of hits.
        mode (SemanticMode): Retrieval mode selector.
        source (SemanticSource): Corpus selector.

    Returns:
        str: §3.1 JSON envelope string.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(semantic_search_tool)
        True
    """
    needle = query.strip()
    if not needle:
        return enveloped_failure("query must be non-empty", code=ToolResultCode.VALIDATION_ERROR)
    if mode not in ("semantic", "bm25", "hybrid"):
        return enveloped_failure(
            f"unsupported mode {mode!r}",
            code=ToolResultCode.VALIDATION_ERROR,
        )
    if source not in ("all", "summaries", "memory", "workspace", "messages"):
        return enveloped_failure(
            f"unsupported source {source!r}",
            code=ToolResultCode.VALIDATION_ERROR,
        )
    hit_limit = max(1, min(int(limit), MAX_SEMANTIC_SEARCH_LIMIT))
    sj = find_sevn_json(ctx.workspace_path)
    wc_cfg: WitchcraftConfig | None = None
    if sj is not None:
        _cfg, _ = load_workspace(sevn_json=sj)
        wc_cfg = WitchcraftConfig.from_workspace_config(_cfg)
    hits, err, index_age = run_semantic_search(
        ctx.workspace_path,
        query=needle,
        limit=hit_limit,
        mode=mode,
        source=source,
        witchcraft_cfg=wc_cfg,
    )
    if err is not None:
        return enveloped_failure(
            err,
            code=ToolResultCode.DISABLED_TOOL,
            data={
                "witchcraft_enabled": True,
                "witchcraft.index_age_s": index_age,
                "semantic_requested": False,
            },
        )
    return enveloped_success(
        {
            "query": needle,
            "mode": mode,
            "source": source,
            "hits": hits or [],
            "count": len(hits or []),
            "witchcraft.index_age_s": index_age,
        },
    )


def register_semantic_search_tool(
    executor: ToolExecutor,
    workspace_config: WorkspaceConfig | None = None,
) -> None:
    """Register ``semantic_search`` only when enabled **and** the indexer is wired.

    Gated on both the ``witchcraft_enabled`` config flag **and**
    :func:`~sevn.second_brain.witchcraft_bridge.witchcraft_indexer_available` so a
    deployment without the Witchcraft indexer never advertises a tool that can only
    return ``DISABLED_TOOL`` (quarantine; `specs/27-second-brain.md` §11). In the
    current stub build the indexer is unavailable, so registration is skipped even
    when the flag is set.

    Args:
        executor (ToolExecutor): Registry under construction.
        workspace_config (WorkspaceConfig | None): Parsed workspace config gate.

    Returns:
        None

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.tools.base import ToolExecutor
        >>> from sevn.tools.semantic_search import register_semantic_search_tool
        >>> exe = ToolExecutor()
        >>> cfg = WorkspaceConfig.model_validate({
        ...     "schema_version": 1,
        ...     "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        ...     "witchcraft_enabled": True,
        ... })
        >>> register_semantic_search_tool(exe, cfg)
        >>> "semantic_search" in {d.name for d in exe.definitions()}  # indexer stub → skipped
        False
    """
    if not witchcraft_tool_enabled(workspace_config):
        return
    wc_cfg = WitchcraftConfig.from_workspace_config(workspace_config)
    if not witchcraft_indexer_available(wc_cfg):
        return
    executor.register(tool_from_decorated(semantic_search_tool))


__all__ = [
    "DEFAULT_SEMANTIC_SEARCH_LIMIT",
    "MAX_SEMANTIC_SEARCH_LIMIT",
    "register_semantic_search_tool",
    "run_semantic_search",
    "semantic_search_tool",
    "witchcraft_tool_enabled",
]
