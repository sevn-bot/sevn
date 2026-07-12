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

from sevn.config.workspace_config import WorkspaceConfig
from sevn.second_brain.bootstrap import ensure_second_brain_scope_layout
from sevn.second_brain.paths import display_scope_root_relative, effective_scope, resolve_scope_root


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


def _missing_layout_paths(scope_root: Path) -> tuple[str, ...]:
    """Return missing standard layout paths under *scope_root*.

    Args:
        scope_root (Path): Resolved scope directory.

    Returns:
        tuple[str, ...]: Missing relative paths.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as td:
        ...     missing = _missing_layout_paths(Path(td))
        ...     "wiki/index.md" in missing
        True
    """
    required = (
        "raw",
        "wiki",
        "wiki/ingests",
        "outputs",
        "wiki/index.md",
        "wiki/log.md",
    )
    missing: list[str] = []
    for rel in required:
        target = scope_root / rel
        if rel.endswith(".md"):
            if not target.is_file():
                missing.append(rel)
        elif not target.is_dir():
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
    missing = _missing_layout_paths(scope_root)
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
    scope_root = resolve_scope_root(content_root, sb_cfg, effective_scope(None, sb_cfg))
    return ensure_second_brain_scope_layout(scope_root)


__all__ = [
    "SecondBrainLayoutProbe",
    "fix_second_brain_layout",
    "probe_second_brain_vault_layout",
]
