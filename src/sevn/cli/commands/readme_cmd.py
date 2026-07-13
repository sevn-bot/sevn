"""``sevn readme`` — README pipeline CLI (`plan/readme-system` Wave 3).

Module: sevn.cli.commands.readme_cmd
Depends: asyncio, pathlib, typer, sevn.cli.asyncio_util, sevn.cli.gateway_client,
    sevn.cli.repo_sync, sevn.cli.workspace, sevn.docs.readme.check, sevn.docs.readme.manifest,
    sevn.docs.readme.render, sevn.docs.readme.scaffold, sevn.docs.readme.settings

Exports:
    register — attach ``readme`` Typer subapp to the root CLI.
"""

from __future__ import annotations

from pathlib import Path

import typer

from sevn.cli.asyncio_util import run_sync_coro
from sevn.cli.gateway_client import resolve_proxy_base_url
from sevn.cli.repo_sync import RepoSyncError, resolve_sevn_repo_root
from sevn.cli.workspace import load_bound_workspace
from sevn.docs.readme.check import check_readme_tree
from sevn.docs.readme.fingerprint import (
    default_fingerprints_path,
    stamp_entry,
)
from sevn.docs.readme.manifest import ReadmeEntry, ReadmeManifest, get_entry, load_manifest
from sevn.docs.readme.providers import ReadmeProviderConfig
from sevn.docs.readme.render import write_readme
from sevn.docs.readme.scaffold import scaffold_readme_tree
from sevn.docs.readme.settings import (
    ReadmePipelineSettings,
    default_offline_mode,
    provider_config_from_settings,
    resolve_readme_settings,
)


def _resolve_repo_root(repo: Path | None) -> Path:
    """Resolve sevn.bot checkout root for readme commands.

    Args:
        repo (Path | None): Explicit ``--repo`` override.

    Returns:
        Path: Absolute repository root.

    Raises:
        typer.Exit: When checkout cannot be resolved.

    Examples:
        >>> isinstance(_resolve_repo_root(Path(".")), Path)
        True
    """
    try:
        return resolve_sevn_repo_root(repo)
    except RepoSyncError as exc:
        typer.secho(str(exc), err=True)
        raise typer.Exit(exc.exit_code) from exc


def _load_workspace_settings(repo_root: Path) -> tuple[object | None, ReadmePipelineSettings]:
    """Load optional workspace config and readme pipeline settings.

    Args:
        repo_root (Path): Repository root (unused; bound workspace is operator home).

    Returns:
        tuple[object | None, object]: ``(workspace_config, readme_settings)``.

    Examples:
        >>> ws, settings = _load_workspace_settings(Path("."))
        >>> settings.manifest_path.endswith("manifest.toml")
        True
    """
    _ = repo_root
    try:
        bound = load_bound_workspace()
        workspace = bound.config
    except Exception:
        workspace = None
    proxy_url = None
    if workspace is not None:
        proxy_url = resolve_proxy_base_url(workspace=workspace)
    settings = resolve_readme_settings(workspace, proxy_base_url=proxy_url)
    return workspace, settings


def _manifest_path(repo_root: Path, settings: ReadmePipelineSettings) -> Path:
    """Resolve manifest path from settings relative to repo root.

    Args:
        repo_root (Path): Repository root.
        settings (object): :class:`ReadmePipelineSettings` instance.

    Returns:
        Path: Absolute manifest path.

    Examples:
        >>> from sevn.docs.readme.settings import resolve_readme_settings
        >>> p = _manifest_path(Path("."), resolve_readme_settings(None))
        >>> p.name == "manifest.toml"
        True
    """
    rel = str(settings.manifest_path).strip()
    path = Path(rel)
    if path.is_absolute():
        return path.resolve()
    return (repo_root / path).resolve()


def _resolve_slug(manifest: ReadmeManifest, slug_or_path: str) -> str:
    """Map a slug or output path to a manifest slug.

    Args:
        manifest (ReadmeManifest): Loaded manifest.
        slug_or_path (str): Slug or repo-relative README path.

    Returns:
        str: Manifest slug.

    Raises:
        typer.Exit: When no matching entry exists.

    Examples:
        >>> from pathlib import Path as _P
        >>> m = load_manifest(_P("docs/readmes/manifest.toml"))
        >>> _resolve_slug(m, "gateway") == "gateway"
        True
    """
    token = slug_or_path.strip().replace("\\", "/")
    if "/" not in token and not token.endswith(".md"):
        return token
    normalized = token.lstrip("/")
    for entry in manifest.entries:
        out = entry.output.replace("\\", "/").lstrip("/")
        if out == normalized or out.endswith(f"/{normalized}"):
            return entry.slug
    typer.secho(f"no manifest entry for path or slug: {slug_or_path!r}", err=True)
    raise typer.Exit(2)


def _generation_order(manifest: ReadmeManifest, slug: str | None) -> list[ReadmeEntry]:
    """Return manifest entries to generate in dependency-safe order.

    Args:
        manifest (ReadmeManifest): Loaded manifest.
        slug (str | None): Single slug when not generating all.

    Returns:
        list[ReadmeEntry]: Entries to write (index last when generating all).

    Examples:
        >>> from pathlib import Path as _P
        >>> m = load_manifest(_P("docs/readmes/manifest.toml"))
        >>> entries = _generation_order(m, None)
        >>> entries[-1].slug == "index"
        True
    """
    if slug is not None:
        return [get_entry(manifest, slug)]
    non_index = [e for e in manifest.entries if e.slug != "index"]
    index_entries = [e for e in manifest.entries if e.slug == "index"]
    return [*non_index, *index_entries]


async def _write_entries(
    *,
    repo_root: Path,
    manifest: ReadmeManifest,
    entries: list[ReadmeEntry],
    provider_config: ReadmeProviderConfig,
    fingerprints_path: Path,
) -> list[Path]:
    """Write one or more README files.

    Args:
        repo_root (Path): Repository root.
        manifest (ReadmeManifest): Loaded manifest.
        entries (list[ReadmeEntry]): Rows to render.
        provider_config (object): :class:`ReadmeProviderConfig` instance.
        fingerprints_path (Path): Fingerprint store path.

    Returns:
        list[Path]: Written README paths.

    Examples:
        >>> import asyncio
        >>> import tempfile
        >>> from pathlib import Path as _P
        >>> from sevn.docs.readme.settings import provider_config_from_settings, resolve_readme_settings
        >>> td = _P(tempfile.mkdtemp())
        >>> (td / "src/sevn/storage").mkdir(parents=True)
        >>> _ = (td / "src/sevn/storage/a.py").write_text("x=1\\n", encoding="utf-8")
        >>> m = load_manifest(_P("docs/readmes/manifest.toml"))
        >>> e = get_entry(m, "storage")
        >>> cfg = provider_config_from_settings(resolve_readme_settings(None), offline=True)
        >>> paths = asyncio.run(
        ...     _write_entries(
        ...         repo_root=td,
        ...         manifest=m,
        ...         entries=[e],
        ...         provider_config=cfg,
        ...         fingerprints_path=default_fingerprints_path(td),
        ...     )
        ... )
        >>> paths[0].is_file()
        True
    """
    written: list[Path] = []
    for entry in entries:
        if entry.curated:
            stamp_entry(
                repo_root,
                slug=entry.slug,
                source_globs=entry.source_globs,
                fingerprints_path=fingerprints_path,
            )
            typer.echo(f"skipped {entry.slug} (curated)")
            continue
        path = await write_readme(
            repo_root=repo_root,
            entry=entry,
            config=provider_config,
            fingerprints_path=fingerprints_path,
            manifest=manifest,
        )
        written.append(path)
    return written


def register(app: typer.Typer) -> None:
    """Attach ``readme`` Typer subapp to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """
    readme_app = typer.Typer(
        no_args_is_help=True,
        help="Generate and validate the README pipeline (`docs/readmes/`).",
    )
    app.add_typer(readme_app, name="readme")

    @readme_app.command("generate")
    def generate(
        all_entries: bool = typer.Option(
            False,
            "--all",
            help="Regenerate every README listed in manifest.toml.",
        ),
        slug: str | None = typer.Option(
            None,
            "--slug",
            help="Generate one manifest slug (mutually exclusive with --all).",
        ),
        offline: bool = typer.Option(
            False,
            "--offline",
            help="Force offline/template mode (no LLM).",
        ),
        llm: bool = typer.Option(
            False,
            "--llm",
            help="Use LLM section polish via egress proxy (opt-in).",
        ),
        model: str | None = typer.Option(
            None,
            "--model",
            help="Override docs.readme.model for this run.",
        ),
        repo: Path | None = typer.Option(
            None,
            "--repo",
            help="sevn.bot checkout root (default: SEVN_REPO_ROOT or walk up from cwd).",
        ),
    ) -> None:
        """Generate README markdown from manifest.toml (offline by default in CI)."""
        if all_entries and slug:
            typer.secho("pass only one of --all or --slug", err=True)
            raise typer.Exit(2)
        if not all_entries and not slug:
            typer.secho("pass --all or --slug", err=True)
            raise typer.Exit(2)
        if offline and llm:
            typer.secho("pass only one of --offline or --llm", err=True)
            raise typer.Exit(2)

        repo_root = _resolve_repo_root(repo)
        _, settings = _load_workspace_settings(repo_root)
        if not settings.enabled:
            typer.echo("docs.readme.enabled is false — skipping generate")
            raise typer.Exit(0)

        manifest_path = _manifest_path(repo_root, settings)
        manifest = load_manifest(manifest_path)
        fingerprints_path = default_fingerprints_path(repo_root)

        use_offline = offline or (not llm and default_offline_mode(settings))
        provider_config = provider_config_from_settings(
            settings,
            offline=use_offline,
            model=model,
        )

        target_slug = None if all_entries else slug
        entries = _generation_order(manifest, target_slug)

        written = run_sync_coro(
            _write_entries(
                repo_root=repo_root,
                manifest=manifest,
                entries=entries,
                provider_config=provider_config,
                fingerprints_path=fingerprints_path,
            )
        )
        for path in written:
            rel = path.relative_to(repo_root)
            typer.echo(f"written {rel.as_posix()}")
        raise typer.Exit(0)

    @readme_app.command("fingerprint")
    def fingerprint_cmd(
        slug_or_path: str | None = typer.Argument(
            None,
            help="Manifest slug or README output path.",
        ),
        all_entries: bool = typer.Option(
            False,
            "--all",
            help="Stamp fingerprints for every manifest slug.",
        ),
        repo: Path | None = typer.Option(
            None,
            "--repo",
            help="sevn.bot checkout root (default: SEVN_REPO_ROOT or walk up from cwd).",
        ),
    ) -> None:
        """Recompute source fingerprints without rewriting README bodies."""
        if all_entries and slug_or_path:
            typer.secho("pass only one of slug argument or --all", err=True)
            raise typer.Exit(2)
        if not all_entries and not slug_or_path:
            typer.secho("pass a slug or --all", err=True)
            raise typer.Exit(2)

        repo_root = _resolve_repo_root(repo)
        _, settings = _load_workspace_settings(repo_root)
        if not settings.enabled:
            typer.echo("docs.readme.enabled is false — skipping fingerprint")
            raise typer.Exit(0)

        manifest_path = _manifest_path(repo_root, settings)
        manifest = load_manifest(manifest_path)
        fingerprints_path = default_fingerprints_path(repo_root)

        if all_entries:
            slugs = [entry.slug for entry in manifest.entries]
        elif slug_or_path is not None:
            slugs = [_resolve_slug(manifest, slug_or_path)]
        else:
            raise typer.Exit(2)

        for slug in slugs:
            entry = get_entry(manifest, slug)
            stamp_entry(
                repo_root,
                slug=slug,
                source_globs=entry.source_globs,
                fingerprints_path=fingerprints_path,
            )
            typer.echo(f"stamped {slug}")
        raise typer.Exit(0)

    @readme_app.command("update")
    def update(
        slug_or_path: str = typer.Argument(..., help="Manifest slug or README output path."),
        force: bool = typer.Option(
            False,
            "--force",
            help="Allow regenerating curated README bodies.",
        ),
        offline: bool = typer.Option(
            False,
            "--offline",
            help="Force offline/template mode (no LLM).",
        ),
        llm: bool = typer.Option(
            False,
            "--llm",
            help="Use LLM section polish via egress proxy (opt-in).",
        ),
        model: str | None = typer.Option(
            None,
            "--model",
            help="Override docs.readme.model for this run.",
        ),
        repo: Path | None = typer.Option(
            None,
            "--repo",
            help="sevn.bot checkout root (default: SEVN_REPO_ROOT or walk up from cwd).",
        ),
    ) -> None:
        """Regenerate one README and refresh its source fingerprint."""
        if offline and llm:
            typer.secho("pass only one of --offline or --llm", err=True)
            raise typer.Exit(2)

        repo_root = _resolve_repo_root(repo)
        _, settings = _load_workspace_settings(repo_root)
        if not settings.enabled:
            typer.echo("docs.readme.enabled is false — skipping update")
            raise typer.Exit(0)

        manifest_path = _manifest_path(repo_root, settings)
        manifest = load_manifest(manifest_path)
        slug = _resolve_slug(manifest, slug_or_path)
        entry = get_entry(manifest, slug)
        if entry.curated and not force:
            typer.secho(
                f"{slug} is curated — hand-authored body is protected. "
                f"Review the README, then run `sevn readme fingerprint {slug}` "
                f"to refresh the fingerprint, or pass --force to regenerate the body.",
                err=True,
            )
            raise typer.Exit(2)
        fingerprints_path = default_fingerprints_path(repo_root)

        use_offline = offline or (not llm and default_offline_mode(settings))
        provider_config = provider_config_from_settings(
            settings,
            offline=use_offline,
            model=model,
        )

        path = run_sync_coro(
            write_readme(
                repo_root=repo_root,
                entry=entry,
                config=provider_config,
                fingerprints_path=fingerprints_path,
                manifest=manifest,
            )
        )
        rel = path.relative_to(repo_root)
        typer.echo(f"updated {rel.as_posix()}")
        raise typer.Exit(0)

    @readme_app.command("check")
    def check(
        repo: Path | None = typer.Option(
            None,
            "--repo",
            help="sevn.bot checkout root (default: SEVN_REPO_ROOT or walk up from cwd).",
        ),
    ) -> None:
        """Validate README structure and staleness (exit non-zero on failure)."""
        repo_root = _resolve_repo_root(repo)
        _, settings = _load_workspace_settings(repo_root)
        if not settings.enabled:
            typer.echo("docs.readme.enabled is false — skipping check")
            raise typer.Exit(0)

        manifest_path = _manifest_path(repo_root, settings)
        manifest = load_manifest(manifest_path)
        fingerprints_path = default_fingerprints_path(repo_root)
        result = check_readme_tree(
            repo_root,
            manifest,
            fingerprints_path=fingerprints_path,
        )
        for warning in result.warnings:
            typer.echo(f"warning: {warning}")
        if result.errors:
            for error in result.errors:
                typer.secho(error, err=True)
            raise typer.Exit(1)
        typer.echo("readme check: ok")
        raise typer.Exit(0)

    @readme_app.command("scaffold")
    def scaffold(
        repo: Path | None = typer.Option(
            None,
            "--repo",
            help="sevn.bot checkout root (default: SEVN_REPO_ROOT or walk up from cwd).",
        ),
    ) -> None:
        """Offline regenerate missing/stale READMEs and insert missing section stubs."""
        repo_root = _resolve_repo_root(repo)
        _, settings = _load_workspace_settings(repo_root)
        if not settings.enabled:
            typer.echo("docs.readme.enabled is false — skipping scaffold")
            raise typer.Exit(0)

        manifest_path = _manifest_path(repo_root, settings)
        manifest = load_manifest(manifest_path)
        fingerprints_path = default_fingerprints_path(repo_root)
        provider_config = provider_config_from_settings(settings, offline=True)
        count = scaffold_readme_tree(
            repo_root,
            manifest,
            fingerprints_path=fingerprints_path,
            provider_config=provider_config,
        )
        typer.echo(f"readme scaffold: inserted or regenerated {count} item(s)")
        raise typer.Exit(0)

    @readme_app.command("index")
    def index_cmd(
        offline: bool = typer.Option(
            False,
            "--offline",
            help="Force offline/template mode (no LLM).",
        ),
        llm: bool = typer.Option(
            False,
            "--llm",
            help="Use LLM section polish via egress proxy (opt-in).",
        ),
        repo: Path | None = typer.Option(
            None,
            "--repo",
            help="sevn.bot checkout root (default: SEVN_REPO_ROOT or walk up from cwd).",
        ),
    ) -> None:
        """Regenerate ``docs/readmes/INDEX.md`` from manifest.toml."""
        if offline and llm:
            typer.secho("pass only one of --offline or --llm", err=True)
            raise typer.Exit(2)

        repo_root = _resolve_repo_root(repo)
        _, settings = _load_workspace_settings(repo_root)
        if not settings.enabled:
            typer.echo("docs.readme.enabled is false — skipping index")
            raise typer.Exit(0)

        manifest_path = _manifest_path(repo_root, settings)
        manifest = load_manifest(manifest_path)
        entry = get_entry(manifest, "index")
        fingerprints_path = default_fingerprints_path(repo_root)

        use_offline = offline or (not llm and default_offline_mode(settings))
        provider_config = provider_config_from_settings(settings, offline=use_offline)

        path = run_sync_coro(
            write_readme(
                repo_root=repo_root,
                entry=entry,
                config=provider_config,
                fingerprints_path=fingerprints_path,
                manifest=manifest,
            )
        )
        rel = path.relative_to(repo_root)
        typer.echo(f"written {rel.as_posix()}")
        raise typer.Exit(0)
