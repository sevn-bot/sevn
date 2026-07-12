"""Resolve Second Brain wiki paths and trigger Witchcraft reindex.

Module: sevn.second_brain.witchcraft_reindex
Depends: pathlib, sevn.config.workspace_config, sevn.second_brain.paths,
    sevn.second_brain.witchcraft_bridge

Exports:
    resolve_index_wiki_paths — user + optional shared wiki dirs for indexing.
    reindex_workspace_wiki — synchronous Witchcraft index build for the workspace.
    maybe_reindex_workspace_on_startup — startup hook using resolved paths.
"""

from __future__ import annotations

from pathlib import Path

from sevn.config.workspace_config import WorkspaceConfig
from sevn.second_brain.paths import (
    effective_scope,
    legacy_shared_vault_root,
    resolve_scope_root,
    shared_wiki_root,
    wiki_dir_for_scope,
)
from sevn.second_brain.witchcraft_bridge import (
    WitchcraftConfig,
    build_wiki_index,
    maybe_reindex_on_startup,
)


def resolve_index_wiki_paths(
    *,
    config: WorkspaceConfig,
    content_root: Path,
    scope: str | None = None,
) -> tuple[Path, Path | None] | None:
    """Return ``(user_wiki, shared_wiki)`` when Second Brain is enabled.

    Args:
        config (WorkspaceConfig): Parsed workspace config.
        content_root (Path): Workspace content root.
        scope (str | None): Optional scope override.

    Returns:
        tuple[Path, Path | None] | None: Wiki roots for Witchcraft indexing, or ``None``.

    Examples:
        >>> resolve_index_wiki_paths.__name__
        'resolve_index_wiki_paths'
    """
    sb = config.second_brain
    if sb is None or not sb.enabled:
        return None
    sc = effective_scope(scope, sb)
    scope_root = resolve_scope_root(content_root, sb, sc)
    user_wiki = wiki_dir_for_scope(scope_root)
    shared: Path | None = None
    if sb.topology == "shared_core_overlay":
        shared = shared_wiki_root(legacy_shared_vault_root(content_root))
    return user_wiki, shared


def reindex_workspace_wiki(
    *,
    config: WorkspaceConfig,
    content_root: Path,
    scope: str | None = None,
) -> bool:
    """Build or refresh the Witchcraft wiki index for the resolved vault.

    Args:
        config (WorkspaceConfig): Parsed workspace config.
        content_root (Path): Workspace content root.
        scope (str | None): Optional scope override.

    Returns:
        bool: ``True`` when the Witchcraft binary exits 0; ``False`` when disabled,
        paths are unavailable, or indexing fails.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> reindex_workspace_wiki(config=WorkspaceConfig.minimal(), content_root=Path("."))
        False
    """
    wc_cfg = WitchcraftConfig.from_workspace_config(config)
    if wc_cfg is None:
        return False
    paths = resolve_index_wiki_paths(config=config, content_root=content_root, scope=scope)
    if paths is None:
        return False
    user_wiki, shared = paths
    user_wiki.mkdir(parents=True, exist_ok=True)
    return build_wiki_index(
        user_wiki,
        witchcraft_cfg=wc_cfg,
        workspace_path=content_root,
        shared_wiki=shared,
    )


def maybe_reindex_workspace_on_startup(
    *,
    config: WorkspaceConfig,
    content_root: Path,
) -> None:
    """Run startup reindex when ``witchcraft.reindex_on_startup`` is enabled.

    Args:
        config (WorkspaceConfig): Parsed workspace config.
        content_root (Path): Workspace content root.

    Returns:
        None

    Examples:
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> maybe_reindex_workspace_on_startup(
        ...     config=WorkspaceConfig.minimal(),
        ...     content_root=Path("."),
        ... )
    """
    wc_cfg = WitchcraftConfig.from_workspace_config(config)
    paths = resolve_index_wiki_paths(config=config, content_root=content_root)
    if wc_cfg is None or paths is None:
        return
    user_wiki, shared = paths
    maybe_reindex_on_startup(
        wc_cfg,
        user_wiki,
        workspace_path=content_root,
        shared_wiki=shared,
    )


__all__ = [
    "maybe_reindex_workspace_on_startup",
    "reindex_workspace_wiki",
    "resolve_index_wiki_paths",
]
