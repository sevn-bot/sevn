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

import typer

from sevn.cli.errors import CliPreconditionError
from sevn.cli.workspace import load_bound_workspace
from sevn.config.sections.features import _normalise_vault_path
from sevn.gateway.workspace_config_io import load_raw_sevn_json, mutate_sevn_json
from sevn.onboarding.web_app import _set_nested
from sevn.second_brain.bootstrap import ensure_second_brain_scope_layout
from sevn.second_brain.paths import display_scope_root_relative, effective_scope, resolve_scope_root


def _layout_status(scope_root: Path) -> tuple[bool, list[str]]:
    """Return whether the standard layout is complete and missing relative paths.

    Args:
        scope_root (Path): Resolved scope directory.

    Returns:
        tuple[bool, list[str]]: Complete flag and missing relative paths.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     ok, missing = _layout_status(root)
        ...     ok is False and "wiki/index.md" in missing
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
    return not missing, missing


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
        no_model: bool = typer.Option(False, "--no-model", help="Skip copying MODEL.md stub."),
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

        def _apply(doc: dict[str, object]) -> None:
            _set_nested(doc, "second_brain.enabled", True)
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
        scope = effective_scope(None, sb_cfg)
        scope_root = resolve_scope_root(content_root, sb_cfg, scope)
        created = ensure_second_brain_scope_layout(scope_root, copy_model=not no_model)
        rel = display_scope_root_relative(content_root, scope_root)
        typer.echo(f"Second Brain enabled for scope {scope!r}")
        typer.echo(f"Vault: {rel}")
        typer.echo(f"Absolute: {scope_root}")
        if created:
            typer.echo(f"Created: {', '.join(created)}")
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
    complete, missing = _layout_status(scope_root)
    raw_doc = load_raw_sevn_json(bw.layout.sevn_json_path)
    sb_raw = raw_doc.get("second_brain")
    sb_dict = sb_raw if isinstance(sb_raw, dict) else {}
    paths_raw = sb_dict.get("paths")
    paths_dict = paths_raw if isinstance(paths_raw, dict) else {}
    wiki_alias = bool(paths_dict.get("wiki")) and not paths_dict.get("vault")
    payload = {
        "enabled": bool(sb_cfg.enabled),
        "paths_vault": sb_cfg.paths.vault,
        "scope": scope,
        "scope_root_relative": display_scope_root_relative(content_root, scope_root),
        "scope_root_absolute": str(scope_root),
        "layout_complete": complete,
        "layout_missing": missing,
        "paths_wiki_alias": wiki_alias,
    }
    if json_out:
        emit_json_success(command="sevn config second-brain", data=payload)
    else:
        typer.echo(f"Enabled: {'on' if sb_cfg.enabled else 'off'}")
        vault_line = sb_cfg.paths.vault or "(default second_brain/users/<scope>)"
        typer.echo(f"paths.vault: {vault_line}")
        typer.echo(f"Scope: {scope}")
        typer.echo(f"Resolved vault: {payload['scope_root_relative']}")
        typer.echo(f"Layout complete: {'yes' if complete else 'no'}")
        if missing:
            typer.echo(f"Missing: {', '.join(missing)}")
        if wiki_alias:
            typer.echo(
                "Warning: legacy second_brain.paths.wiki alias detected — run setup to normalize."
            )
    raise typer.Exit(0)


__all__ = ["register", "show_second_brain_config"]
