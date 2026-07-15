"""``sevn second-brain`` setup helpers (`specs/23-cli.md` §3).

Module: sevn.cli.commands.second_brain_cmd
Depends: pathlib, typer, sevn.cli.workspace, sevn.config.sections.features,
    sevn.second_brain.bootstrap, sevn.second_brain.paths

Exports:
    register — attach ``second-brain`` Typer subapp to the root CLI.
    show_second_brain_config — print resolved vault paths for ``sevn config second-brain``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import typer

from sevn.cli.errors import CliPreconditionError
from sevn.cli.workspace import load_bound_workspace
from sevn.config.sections.features import SecondBrainParaConfig, _normalise_vault_path
from sevn.config.workspace_config import SecondBrainWorkspaceConfig, WorkspaceConfig
from sevn.gateway.config_io.workspace_config_io import load_raw_sevn_json, mutate_sevn_json
from sevn.onboarding.web_app import _set_nested
from sevn.second_brain.bootstrap import detect_layout, ensure_second_brain_scope_layout
from sevn.second_brain.layout_probe import _missing_layout_paths
from sevn.second_brain.paths import (
    LayoutRole,
    VaultLayout,
    display_scope_root_relative,
    effective_scope,
    resolve_scope_root,
)
from sevn.second_brain.witchcraft_bridge import WitchcraftConfig, witchcraft_indexer_available
from sevn.second_brain.witchcraft_reindex import reindex_workspace_wiki, resolve_index_wiki_paths

_LAYOUT_ROLES: tuple[LayoutRole, ...] = (
    "capture",
    "projects",
    "areas",
    "curated",
    "archive",
    "templates",
    "sources",
    "outputs",
    "index_note",
    "log_note",
)


def _role_path_relative(content_root: Path, path: Path) -> str:
    """Return *path* as a workspace-relative POSIX string for operator display.

    Args:
        content_root (Path): Workspace content root.
        path (Path): Resolved role path (directory or note file).

    Returns:
        str: Display path relative to *content_root*.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> ws = Path(tempfile.mkdtemp())
        >>> note = ws / "obsidian" / "x" / "index.md"
        >>> _ = note.parent.mkdir(parents=True)
        >>> _role_path_relative(ws, note)
        'obsidian/x/index.md'
    """
    return display_scope_root_relative(content_root, path)


def _resolved_roles_map(
    content_root: Path,
    sb_cfg: SecondBrainWorkspaceConfig,
    scope: str,
) -> dict[str, str]:
    """Build a map of layout role names to workspace-relative paths.

    Args:
        content_root (Path): Workspace content root.
        sb_cfg (SecondBrainWorkspaceConfig): Parsed ``second_brain`` workspace slice.
        scope (str): Active scope id.

    Returns:
        dict[str, str]: Role name → workspace-relative path.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import SecondBrainWorkspaceConfig
        >>> ws = Path(tempfile.mkdtemp())
        >>> roles = _resolved_roles_map(ws, SecondBrainWorkspaceConfig(), "owner")
        >>> roles["curated"].endswith("wiki")
        True
    """
    layout = VaultLayout(content_root, sb_cfg, scope)
    return {
        role: _role_path_relative(content_root, layout.role_dir(role)) for role in _LAYOUT_ROLES
    }


def _content_roots_relative(
    content_root: Path,
    sb_cfg: SecondBrainWorkspaceConfig,
    scope: str,
) -> list[str]:
    """Return workspace-relative paths for layout content roots.

    Args:
        content_root (Path): Workspace content root.
        sb_cfg (SecondBrainWorkspaceConfig): Parsed ``second_brain`` workspace slice.
        scope (str): Active scope id.

    Returns:
        list[str]: Content root paths for search/index/lint.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import SecondBrainWorkspaceConfig
        >>> ws = Path(tempfile.mkdtemp())
        >>> roots = _content_roots_relative(ws, SecondBrainWorkspaceConfig(), "owner")
        >>> len(roots)
        1
    """
    layout = VaultLayout(content_root, sb_cfg, scope)
    return [_role_path_relative(content_root, root) for root in layout.content_roots()]


def _resolve_setup_layout(
    choice: Literal["auto", "legacy", "para"],
    *,
    content_root: Path,
    vault_norm: str | None,
) -> Literal["legacy", "para"]:
    """Resolve ``--layout auto`` to ``legacy`` or ``para`` using on-disk detection.

    Args:
        choice (Literal["auto", "legacy", "para"]): CLI layout flag value.
        content_root (Path): Workspace content root.
        vault_norm (str | None): Normalised ``paths.vault`` when ``--vault`` was passed.

    Returns:
        Literal["legacy", "para"]: Layout to persist in ``sevn.json``.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> ws = Path(tempfile.mkdtemp())
        >>> _resolve_setup_layout("legacy", content_root=ws, vault_norm=None)
        'legacy'
    """
    if choice != "auto":
        return choice
    if vault_norm is None:
        return "legacy"
    detected = detect_layout((content_root / vault_norm).resolve())
    return detected if detected is not None else "legacy"


def _layout_status(
    scope_root: Path,
    *,
    content_root: Path,
    sb_cfg: SecondBrainWorkspaceConfig,
    scope: str,
) -> tuple[bool, list[str]]:
    """Return whether the active layout is complete and missing relative paths.

    Args:
        scope_root (Path): Resolved scope directory.
        content_root (Path): Workspace content root.
        sb_cfg (SecondBrainWorkspaceConfig): Parsed ``second_brain`` workspace slice.
        scope (str): Active scope id.

    Returns:
        tuple[bool, list[str]]: Complete flag and missing relative paths.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import SecondBrainWorkspaceConfig
        >>> from sevn.second_brain.paths import resolve_scope_root
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     cfg = SecondBrainWorkspaceConfig()
        ...     scope_root = resolve_scope_root(root, cfg, "owner")
        ...     ok, missing = _layout_status(
        ...         scope_root, content_root=root, sb_cfg=cfg, scope="owner"
        ...     )
        ...     ok is False and "wiki/index.md" in missing
        True
    """
    missing = list(
        _missing_layout_paths(
            scope_root,
            content_root=content_root,
            cfg=sb_cfg,
            scope=scope,
        ),
    )
    return not missing, missing


def _run_reindex(config: WorkspaceConfig, content_root: Path) -> None:
    """Build Witchcraft index for the resolved wiki vault.

    Args:
        config (WorkspaceConfig): Parsed workspace config.
        content_root (Path): Workspace content root.

    Raises:
        CliPreconditionError: When Witchcraft is disabled or indexing fails.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> try:
        ...     _run_reindex(WorkspaceConfig.minimal(), Path(tempfile.mkdtemp()))
        ... except Exception:
        ...     pass
    """
    wc_cfg = WitchcraftConfig.from_workspace_config(config)
    if wc_cfg is None:
        raise CliPreconditionError(
            "witchcraft_enabled is false — set witchcraft_enabled: true in sevn.json first"
        )
    paths = resolve_index_wiki_paths(config=config, content_root=content_root)
    if paths is None:
        raise CliPreconditionError("second_brain is disabled")
    user_wiki, _shared = paths
    ok = reindex_workspace_wiki(config=config, content_root=content_root)
    if not ok:
        raise CliPreconditionError(
            "witchcraft reindex failed — install the witchcraft binary and ensure vault has content"
        )
    typer.echo(f"Witchcraft index built for vault content roots (primary: {user_wiki})")


def register(app: typer.Typer) -> None:
    """Attach ``second-brain`` Typer subapp to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """

    sb = typer.Typer(no_args_is_help=True, help="Second Brain vault setup and layout.")
    app.add_typer(sb, name="second-brain")

    @sb.command("setup")
    def setup_cmd(
        vault: str | None = typer.Option(
            None,
            "--vault",
            help="Workspace-relative Obsidian vault folder (e.g. obsidian/alex_AI).",
        ),
        layout: Literal["auto", "legacy", "para"] = typer.Option(
            "auto",
            "--layout",
            help="Vault layout: auto (detect), legacy (wiki/raw/outputs), or para (Obsidian PARA).",
        ),
        no_model: bool = typer.Option(False, "--no-model", help="Skip copying MODEL.md stub."),
        reindex: bool = typer.Option(
            False,
            "--reindex",
            help="Build Witchcraft semantic index when witchcraft_enabled is true.",
        ),
    ) -> None:
        """Enable Second Brain, optionally set ``paths.vault``, and bootstrap layout."""
        bw = load_bound_workspace()
        content_root = bw.layout.content_root
        vault_norm: str | None = None
        if vault is not None:
            try:
                vault_norm = _normalise_vault_path(vault)
            except ValueError as exc:
                raise CliPreconditionError(str(exc)) from exc

        resolved_layout = _resolve_setup_layout(
            layout,
            content_root=content_root,
            vault_norm=vault_norm,
        )

        def _apply(doc: dict[str, object]) -> None:
            _set_nested(doc, "second_brain.enabled", True)
            _set_nested(doc, "second_brain.layout", resolved_layout)
            if resolved_layout == "para":
                sb_obj = doc.setdefault("second_brain", {})
                if isinstance(sb_obj, dict) and "para" not in sb_obj:
                    sb_obj["para"] = SecondBrainParaConfig().model_dump()
            if vault_norm is not None:
                paths = doc.setdefault("second_brain", {})
                if isinstance(paths, dict):
                    path_obj = paths.setdefault("paths", {})
                    if isinstance(path_obj, dict):
                        path_obj["vault"] = vault_norm
                        path_obj.pop("wiki", None)

        mutate_sevn_json(bw.layout.sevn_json_path, _apply)
        bw = load_bound_workspace()
        sb_cfg = bw.config.second_brain
        if sb_cfg is None:
            raise CliPreconditionError("second_brain config missing after setup")
        scope = effective_scope(None, sb_cfg)
        scope_root = resolve_scope_root(content_root, sb_cfg, scope)
        created = ensure_second_brain_scope_layout(
            scope_root,
            cfg=bw.config,
            copy_model=not no_model,
        )
        rel = display_scope_root_relative(content_root, scope_root)
        roles = _resolved_roles_map(content_root, sb_cfg, scope)
        content_roots = _content_roots_relative(content_root, sb_cfg, scope)
        typer.echo(f"Second Brain enabled for scope {scope!r}")
        typer.echo(f"Layout: {sb_cfg.layout}")
        typer.echo(f"Vault: {rel}")
        typer.echo(f"Absolute: {scope_root}")
        for role in _LAYOUT_ROLES:
            typer.echo(f"  {role}: {roles[role]}")
        typer.echo(f"Content roots: {', '.join(content_roots)}")
        if created:
            typer.echo(f"Created: {', '.join(created)}")
        if reindex:
            _run_reindex(bw.config, content_root)
        raise typer.Exit(0)

    @sb.command("reindex")
    def reindex_cmd() -> None:
        """Build or refresh the Witchcraft semantic index for the resolved vault."""
        bw = load_bound_workspace()
        _run_reindex(bw.config, bw.layout.content_root)
        raise typer.Exit(0)


def show_second_brain_config(*, json_out: bool = False) -> None:
    """Print resolved Second Brain paths for ``sevn config second-brain``.

    Args:
        json_out (bool): Emit JSON envelope when True.

    Raises:
        typer.Exit: After printing output.

    Examples:
        >>> show_second_brain_config(json_out=False)  # doctest: +SKIP
    """
    from sevn.cli.json_util import emit_json_success

    bw = load_bound_workspace()
    sb_cfg = bw.config.second_brain
    if sb_cfg is None:
        raise CliPreconditionError("second_brain config missing")
    content_root = bw.layout.content_root
    scope = effective_scope(None, sb_cfg)
    scope_root = resolve_scope_root(content_root, sb_cfg, scope)
    complete, missing = _layout_status(
        scope_root,
        content_root=content_root,
        sb_cfg=sb_cfg,
        scope=scope,
    )
    roles = _resolved_roles_map(content_root, sb_cfg, scope)
    content_roots = _content_roots_relative(content_root, sb_cfg, scope)
    raw_doc = load_raw_sevn_json(bw.layout.sevn_json_path)
    sb_raw = raw_doc.get("second_brain")
    sb_dict = sb_raw if isinstance(sb_raw, dict) else {}
    paths_raw = sb_dict.get("paths")
    paths_dict = paths_raw if isinstance(paths_raw, dict) else {}
    wiki_alias = bool(paths_dict.get("wiki")) and not paths_dict.get("vault")
    wc_cfg = WitchcraftConfig.from_workspace_config(bw.config)
    wiki_paths = resolve_index_wiki_paths(config=bw.config, content_root=content_root)
    wiki_index_path = str(wiki_paths[0]) if wiki_paths is not None else None
    witchcraft_ready = (
        witchcraft_indexer_available(wc_cfg, workspace_path=content_root) if wc_cfg else False
    )
    payload = {
        "enabled": bool(sb_cfg.enabled),
        "layout": sb_cfg.layout,
        "paths_vault": sb_cfg.paths.vault,
        "scope": scope,
        "scope_root_relative": display_scope_root_relative(content_root, scope_root),
        "scope_root_absolute": str(scope_root),
        "roles": roles,
        "content_roots": content_roots,
        "layout_complete": complete,
        "layout_missing": missing,
        "paths_wiki_alias": wiki_alias,
        "witchcraft_enabled": wc_cfg is not None,
        "witchcraft_index_ready": witchcraft_ready,
        "wiki_index_path": wiki_index_path,
    }
    if json_out:
        emit_json_success(command="sevn config second-brain", data=payload)
    else:
        typer.echo(f"Enabled: {'on' if sb_cfg.enabled else 'off'}")
        typer.echo(f"Layout: {sb_cfg.layout}")
        vault_line = sb_cfg.paths.vault or "(default second_brain/users/<scope>)"
        typer.echo(f"paths.vault: {vault_line}")
        typer.echo(f"Scope: {scope}")
        typer.echo(f"Resolved vault: {payload['scope_root_relative']}")
        for role in _LAYOUT_ROLES:
            typer.echo(f"  {role}: {roles[role]}")
        typer.echo(f"Content roots: {', '.join(content_roots)}")
        typer.echo(f"Layout complete: {'yes' if complete else 'no'}")
        if missing:
            typer.echo(f"Missing: {', '.join(missing)}")
        if wiki_alias:
            typer.echo(
                "Warning: legacy second_brain.paths.wiki alias detected — run setup to normalize."
            )
        if wc_cfg is not None:
            typer.echo(f"Witchcraft: enabled (index ready: {'yes' if witchcraft_ready else 'no'})")
            if wiki_index_path:
                typer.echo(f"Vault index path: {wiki_index_path}")
            typer.echo("Run `sevn second-brain reindex` to build or refresh the semantic index.")
    raise typer.Exit(0)


__all__ = ["register", "show_second_brain_config"]
