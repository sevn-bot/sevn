"""Second Brain vault layout checks for ``sevn doctor``.

Module: sevn.second_brain.layout_probe
Depends: pathlib, sevn.config.workspace_config, sevn.second_brain.paths

Exports:
    probe_second_brain_vault_layout — layout status for doctor and CLI.
    fix_second_brain_layout — bootstrap missing layout paths.
    SecondBrainLayoutProbe — doctor probe result dataclass.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sevn.config.workspace_config import SecondBrainWorkspaceConfig, WorkspaceConfig
from sevn.second_brain.bootstrap import ensure_second_brain_scope_layout
from sevn.second_brain.paths import (
    VaultLayout,
    display_scope_root_relative,
    effective_scope,
    resolve_scope_root,
)


@dataclass(frozen=True)
class SecondBrainLayoutProbe:
    """Outcome of a Second Brain vault layout probe."""

    ok: bool
    detail: str
    hint: str | None
    scope_root_relative: str
    missing: tuple[str, ...]
    wiki_alias: bool
    topology_warning: bool


def _missing_layout_paths(
    scope_root: Path,
    *,
    content_root: Path,
    cfg: SecondBrainWorkspaceConfig,
    scope: str,
) -> tuple[str, ...]:
    """Return missing standard layout paths under *scope_root*.

    Args:
        scope_root (Path): Resolved scope directory.
        content_root (Path): Workspace content root.
        cfg (SecondBrainWorkspaceConfig): Second Brain workspace slice.
        scope (str): Active scope id.

    Returns:
        tuple[str, ...]: Missing relative paths.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import SecondBrainWorkspaceConfig
        >>> from sevn.second_brain.paths import resolve_scope_root
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     cfg = SecondBrainWorkspaceConfig()
        ...     scope_root = resolve_scope_root(root, cfg, "owner")
        ...     missing = _missing_layout_paths(
        ...         scope_root, content_root=root, cfg=cfg, scope="owner"
        ...     )
        ...     "wiki/index.md" in missing
        True
    """
    layout = VaultLayout(content_root, cfg, scope)
    required_dirs: tuple[Path, ...]
    required_files: tuple[Path, ...]
    if cfg.layout == "para":
        required_dirs = (
            layout.role_dir("capture"),
            layout.role_dir("projects"),
            layout.role_dir("areas"),
            layout.role_dir("curated"),
            layout.role_dir("archive"),
            layout.role_dir("templates"),
            layout.role_dir("sources"),
            layout.role_dir("outputs"),
        )
        required_files = (
            layout.role_dir("index_note"),
            layout.role_dir("log_note"),
        )
    else:
        required_dirs = (
            layout.role_dir("sources"),
            layout.role_dir("curated"),
            layout.role_dir("curated") / "ingests",
            layout.role_dir("outputs"),
        )
        required_files = (
            layout.role_dir("index_note"),
            layout.role_dir("log_note"),
        )
    missing: list[str] = []
    root = scope_root.resolve()
    for target in required_dirs:
        rel = target.resolve().relative_to(root).as_posix()
        if not target.is_dir():
            missing.append(rel)
    for target in required_files:
        rel = target.resolve().relative_to(root).as_posix()
        if not target.is_file():
            missing.append(rel)
    return tuple(missing)


def probe_second_brain_vault_layout(
    *,
    config: WorkspaceConfig,
    content_root: Path,
    raw_doc: dict[str, object] | None = None,
) -> SecondBrainLayoutProbe | None:
    """Probe Second Brain vault layout when the subsystem is enabled.

    Args:
        config (WorkspaceConfig): Parsed workspace config.
        content_root (Path): Workspace content root.
        raw_doc (dict[str, object] | None): Raw ``sevn.json`` for alias detection.

    Returns:
        SecondBrainLayoutProbe | None: Probe result, or ``None`` when disabled.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> probe_second_brain_vault_layout(
        ...     config=WorkspaceConfig.minimal(),
        ...     content_root=Path("."),
        ... ) is None
        True
    """
    sb_cfg = config.second_brain
    if sb_cfg is None or not sb_cfg.enabled:
        return None
    scope = effective_scope(None, sb_cfg)
    scope_root = resolve_scope_root(content_root, sb_cfg, scope)
    rel = display_scope_root_relative(content_root, scope_root)
    missing = _missing_layout_paths(
        scope_root,
        content_root=content_root,
        cfg=sb_cfg,
        scope=scope,
    )
    sb_raw = raw_doc.get("second_brain") if isinstance(raw_doc, dict) else None
    paths_raw = (
        sb_raw.get("paths")
        if isinstance(sb_raw, dict) and isinstance(sb_raw.get("paths"), dict)
        else {}
    )
    wiki_alias = (
        isinstance(paths_raw, dict) and bool(paths_raw.get("wiki")) and not paths_raw.get("vault")
    )
    topology_warning = bool(sb_cfg.paths.vault) and sb_cfg.topology != "single_instance"
    ok = not missing and not topology_warning
    detail = (
        rel if ok else f"{rel}; missing: {', '.join(missing) if missing else 'topology mismatch'}"
    )
    hint = None
    if missing:
        if sb_cfg.layout == "para":
            hint = (
                "Run `sevn second-brain setup --layout para` or `sevn doctor --fix` "
                "to bootstrap PARA layout"
            )
        else:
            hint = "Run `sevn second-brain setup` or `sevn doctor --fix` to bootstrap layout"
    elif wiki_alias:
        hint = "Normalize legacy second_brain.paths.wiki to paths.vault"
    elif topology_warning:
        hint = "Custom paths.vault applies to default_scope only when topology=single_instance"
    if wiki_alias and ok:
        ok = False
        detail = f"{rel}; legacy paths.wiki alias present"
    return SecondBrainLayoutProbe(
        ok=ok,
        detail=detail,
        hint=hint,
        scope_root_relative=rel,
        missing=missing,
        wiki_alias=wiki_alias,
        topology_warning=topology_warning,
    )


def fix_second_brain_layout(*, config: WorkspaceConfig, content_root: Path) -> list[str]:
    """Bootstrap missing Second Brain layout paths.

    Args:
        config (WorkspaceConfig): Parsed workspace config.
        content_root (Path): Workspace content root.

    Returns:
        list[str]: Created relative paths.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> fix_second_brain_layout(config=WorkspaceConfig.minimal(), content_root=Path("."))
        []
    """
    sb_cfg = config.second_brain
    if sb_cfg is None or not sb_cfg.enabled:
        return []
    scope = effective_scope(None, sb_cfg)
    scope_root = resolve_scope_root(content_root, sb_cfg, scope)
    return ensure_second_brain_scope_layout(scope_root, cfg=config)


__all__ = [
    "SecondBrainLayoutProbe",
    "fix_second_brain_layout",
    "probe_second_brain_vault_layout",
]
