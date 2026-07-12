"""``sevn about-docs`` — public prd/specs pipeline CLI (about-docs-system).

Module: sevn.cli.commands.about_docs_cmd
Depends: json, pathlib, typer, sevn.cli.repo_sync, sevn.docs.about.check, sevn.docs.about.extract,
    sevn.docs.about.generate, sevn.docs.about.index, sevn.docs.about.loader, sevn.docs.about.model,
    sevn.docs.about.registry, sevn.docs.readme.providers

Exports:
    register — attach ``about-docs`` Typer subapp to the root CLI.

Examples:
    >>> register(typer.Typer()) is None  # doctest: +SKIP
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from sevn.cli.repo_sync import RepoSyncError, resolve_sevn_repo_root
from sevn.docs.about.check import check_about_docs
from sevn.docs.about.extract import extract_fields
from sevn.docs.about.generate import generate_body
from sevn.docs.about.index import index_path, render_index
from sevn.docs.about.loader import dump_doc, load_doc
from sevn.docs.about.migrate import migrate_all
from sevn.docs.about.model import AboutDoc, export_json_schema
from sevn.docs.about.registry import find_doc_path, load_manifest_entries
from sevn.docs.readme.providers import ReadmeProviderConfig, build_provider

_DEFAULT_SCHEMA_PATH = Path("about-sevn.bot/_docsys/about-docs.schema.json")


def _resolve_repo_root(repo: Path | None) -> Path:
    """Resolve sevn.bot checkout root for about-docs commands.

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


def _schema_output_path(repo_root: Path) -> Path:
    """Return the checked-in JSON Schema path under ``repo_root``.

    Args:
        repo_root (Path): Repository root.

    Returns:
        Path: Absolute schema output path.

    Examples:
        >>> p = _schema_output_path(Path("."))
        >>> p.as_posix().endswith("about-docs.schema.json")
        True
    """
    return (repo_root / _DEFAULT_SCHEMA_PATH).resolve()


def _load_all_docs(repo_root: Path) -> list[AboutDoc]:
    """Load every about-doc under ``about-sevn.bot/{prd,specs}/``.

    Args:
        repo_root (Path): Repository root.

    Returns:
        list[AboutDoc]: Loaded frontmatter models.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> _load_all_docs(td)
        []
    """
    docs: list[AboutDoc] = []
    for subdir in ("prd", "specs"):
        directory = repo_root / "about-sevn.bot" / subdir
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            if path.name == "README.md":
                continue
            doc, _body = load_doc(path)
            docs.append(doc)
    return docs


def _resolve_doc_id(repo_root: Path, doc_id: str) -> tuple[Path, AboutDoc, str]:
    """Load one about-doc by stable ``id``.

    Args:
        repo_root (Path): Repository root.
        doc_id (str): Document id.

    Returns:
        tuple[Path, AboutDoc, str]: Path, frontmatter, and markdown body.

    Raises:
        typer.Exit: When the id cannot be resolved or loaded.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> docs = td / "about-sevn.bot" / "specs"
        >>> docs.mkdir(parents=True)
        >>> p = docs / "17-gateway.md"
        >>> _ = p.write_text(
        ...     "---\\n"
        ...     "id: spec-17-gateway\\n"
        ...     "kind: spec\\n"
        ...     "title: Gateway\\n"
        ...     "status: done\\n"
        ...     "owner: Alex\\n"
        ...     "summary: Turn spine.\\n"
        ...     "last_updated: 2026-06-19\\n"
        ...     "parent_prd: prd-01-main\\n"
        ...     "sources:\\n  - src/sevn/gateway/**\\n"
        ...     "---\\n\\n## Body\\n",
        ...     encoding="utf-8",
        ... )
        >>> path, doc, body = _resolve_doc_id(td, "spec-17-gateway")
        >>> doc.id == "spec-17-gateway" and body.strip().startswith("## Body")
        True
    """
    path = find_doc_path(repo_root, doc_id)
    if path is None:
        typer.secho(f"unknown about-doc id: {doc_id}", err=True)
        raise typer.Exit(2)
    if not path.is_file():
        typer.secho(f"about-doc file missing for id {doc_id}: {path}", err=True)
        raise typer.Exit(2)
    try:
        doc, body = load_doc(path)
    except (OSError, ValueError) as exc:
        typer.secho(f"{path}: {exc}", err=True)
        raise typer.Exit(1) from exc
    if doc.id != doc_id:
        typer.secho(f"{path}: frontmatter id {doc.id!r} != requested {doc_id!r}", err=True)
        raise typer.Exit(1)
    return path, doc, body


def register(app: typer.Typer) -> None:
    """Attach ``about-docs`` Typer subapp to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """
    about_docs_app = typer.Typer(
        no_args_is_help=True,
        help="Generate and validate public prd/spec docs under about-sevn.bot/.",
    )
    app.add_typer(about_docs_app, name="about-docs")

    @about_docs_app.command("schema")
    def schema_cmd(
        repo: Path | None = typer.Option(
            None,
            "--repo",
            help="sevn.bot checkout root (default: SEVN_REPO_ROOT or walk up from cwd).",
        ),
        stdout: bool = typer.Option(
            False,
            "--stdout",
            help="Print JSON Schema to stdout instead of writing the checked-in file.",
        ),
    ) -> None:
        """Export Draft 2020-12 JSON Schema for about-doc frontmatter."""
        repo_root = _resolve_repo_root(repo)
        payload = export_json_schema()
        if stdout:
            typer.echo(json.dumps(payload, indent=2, sort_keys=False) + "\n")
            raise typer.Exit(0)
        out_path = _schema_output_path(repo_root)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
        rel = out_path.relative_to(repo_root)
        typer.echo(f"written {rel.as_posix()}")
        raise typer.Exit(0)

    @about_docs_app.command("check")
    def check_cmd(
        repo: Path | None = typer.Option(
            None,
            "--repo",
            help="sevn.bot checkout root (default: SEVN_REPO_ROOT or walk up from cwd).",
        ),
    ) -> None:
        """Validate about-docs (schema, drift, references, index)."""
        repo_root = _resolve_repo_root(repo)
        issues = check_about_docs(repo_root)
        if issues:
            for issue in issues:
                typer.secho(issue, err=True)
            raise typer.Exit(1)
        typer.echo("about-docs check: ok")
        raise typer.Exit(0)

    @about_docs_app.command("extract")
    def extract_cmd(
        doc_id: str = typer.Argument(..., help="Stable doc id (e.g. spec-17-gateway)."),
        repo: Path | None = typer.Option(
            None,
            "--repo",
            help="sevn.bot checkout root (default: SEVN_REPO_ROOT or walk up from cwd).",
        ),
    ) -> None:
        """Extract code-owned frontmatter fields from source."""
        repo_root = _resolve_repo_root(repo)
        path, doc, body = _resolve_doc_id(repo_root, doc_id)
        extracted = extract_fields(repo_root, doc.model_dump(mode="json"))
        updated = doc.model_copy(update=extracted)
        path.write_text(dump_doc(updated, body), encoding="utf-8")
        rel = path.relative_to(repo_root)
        typer.echo(f"extracted {doc_id} -> {rel.as_posix()}")

    @about_docs_app.command("generate")
    def generate_cmd(
        doc_id: str = typer.Argument(..., help="Stable doc id (e.g. spec-17-gateway)."),
        repo: Path | None = typer.Option(
            None,
            "--repo",
            help="sevn.bot checkout root (default: SEVN_REPO_ROOT or walk up from cwd).",
        ),
        offline: bool = typer.Option(
            True,
            "--offline/--online",
            help="Use offline deterministic stub (default) or LLM provider.",
        ),
    ) -> None:
        """Generate LLM prose body (offline stub when --offline)."""
        repo_root = _resolve_repo_root(repo)
        path, doc, _body = _resolve_doc_id(repo_root, doc_id)
        provider = build_provider(ReadmeProviderConfig(offline=offline))
        body = generate_body(doc, provider)
        path.write_text(dump_doc(doc, body), encoding="utf-8")
        rel = path.relative_to(repo_root)
        typer.echo(f"generated {doc_id} -> {rel.as_posix()}")

    @about_docs_app.command("index")
    def index_cmd(
        repo: Path | None = typer.Option(
            None,
            "--repo",
            help="sevn.bot checkout root (default: SEVN_REPO_ROOT or walk up from cwd).",
        ),
    ) -> None:
        """Render prd/spec README index tables."""
        repo_root = _resolve_repo_root(repo)
        docs = _load_all_docs(repo_root)
        for kind in ("prd", "spec"):
            out_path = index_path(repo_root, kind)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(render_index(docs, kind), encoding="utf-8")
            rel = out_path.relative_to(repo_root)
            typer.echo(f"indexed {kind} -> {rel.as_posix()}")

    @about_docs_app.command("migrate")
    def migrate_cmd(
        repo: Path | None = typer.Option(
            None,
            "--repo",
            help="sevn.bot checkout root (default: SEVN_REPO_ROOT or walk up from cwd).",
        ),
        offline: bool = typer.Option(
            True,
            "--offline/--online",
            help="Use offline deterministic body stubs (default).",
        ),
    ) -> None:
        """Migrate legacy root prd/specs seed docs into about-sevn.bot/."""
        repo_root = _resolve_repo_root(repo)
        written = migrate_all(repo_root, offline=offline)
        for rel in written:
            typer.echo(f"migrated -> {rel}")
        typer.echo(f"migrated {len(written)} docs")

    @about_docs_app.command("context")
    def context_cmd(
        doc_id: str = typer.Argument(..., help="Stable doc id (e.g. spec-17-gateway)."),
        repo: Path | None = typer.Option(
            None,
            "--repo",
            help="sevn.bot checkout root (default: SEVN_REPO_ROOT or walk up from cwd).",
        ),
    ) -> None:
        """Emit advisory spec→code context for one doc."""
        repo_root = _resolve_repo_root(repo)
        _path, doc, body = _resolve_doc_id(repo_root, doc_id)
        manifest = load_manifest_entries(repo_root).get(doc_id, {})
        typer.echo(f"# about-doc context: {doc_id}")
        typer.echo("")
        typer.echo("## frontmatter")
        typer.echo(json.dumps(doc.model_dump(mode="json"), indent=2, sort_keys=True))
        if manifest:
            typer.echo("")
            typer.echo("## manifest")
            typer.echo(json.dumps(manifest, indent=2, sort_keys=True))
        typer.echo("")
        typer.echo("## body")
        typer.echo(body.rstrip())
        typer.echo("")
