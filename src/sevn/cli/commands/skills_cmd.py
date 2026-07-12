"""``sevn skills`` — workspace skills inventory helpers (`PROBLEMS.md` §Priority 1.a).

Module: sevn.cli.commands.skills_cmd
Depends: pathlib, typer, sevn.data.skills_index, sevn.skills.security_scan, sevn.workspace.layout

Subcommands:
    sync           refresh the workspace ``skills/INDEX.md`` against the shipped starter
    security-scan  SkillSpector static scan of workspace user/generated skills

Exports:
    register — attach ``skills`` Typer subapp to the root CLI.
"""

from __future__ import annotations

from pathlib import Path

import typer

from sevn.data.skills_index import REPO_STARTER_INDEX, read_skills_index
from sevn.skills.security_scan import (
    DEFAULT_FAIL_SEVERITIES,
    normalize_skill_path,
    resolve_skillspector_command,
    scan_skill_path,
    write_workspace_scan_summary,
)


def _resolve_workspace_index(workspace: Path | None) -> Path:
    """Return the path to ``<workspace>/skills/INDEX.md``.

    Args:
        workspace (Path | None): Workspace content root. ``None`` raises.

    Returns:
        Path: Path under the workspace; the file may not yet exist.

    Examples:
        >>> isinstance(_resolve_workspace_index(Path('/tmp')), Path)
        True
    """
    if workspace is None:
        msg = "workspace path required (pass --workspace or set SEVN_WORKSPACE)"
        raise typer.BadParameter(msg)
    return workspace / "skills" / "INDEX.md"


def _sync_additive(workspace_index: Path) -> tuple[int, int]:
    """Append starter rows the workspace INDEX is missing; never overwrite.

    Args:
        workspace_index (Path): Path to the workspace ``skills/INDEX.md``.

    Returns:
        tuple[int, int]: ``(added, total_starter)``.

    Examples:
        >>> from tempfile import TemporaryDirectory
        >>> with TemporaryDirectory() as td:
        ...     out = Path(td) / "skills" / "INDEX.md"
        ...     out.parent.mkdir(parents=True)
        ...     _ = out.write_text("| name | description |\\n|---|---|\\n", encoding="utf-8")
        ...     added, total = _sync_additive(out)
        ...     added > 0 and added == total
        True
    """
    starter = read_skills_index(workspace_root=None)  # reads REPO_STARTER_INDEX
    if not workspace_index.is_file():
        if not REPO_STARTER_INDEX.is_file():
            return 0, 0
        workspace_index.parent.mkdir(parents=True, exist_ok=True)
        workspace_index.write_bytes(REPO_STARTER_INDEX.read_bytes())
        return len(starter), len(starter)
    workspace = read_skills_index(workspace_root=workspace_index.parent.parent)
    missing = [name for name in starter if name not in workspace]
    if not missing:
        return 0, len(starter)
    text = workspace_index.read_text(encoding="utf-8")
    if not text.endswith("\n"):
        text += "\n"
    appended = "".join(
        f"| {name} | {starter[name].replace('|', chr(92) + '|')} |\n" for name in missing
    )
    workspace_index.write_text(text + appended, encoding="utf-8")
    return len(missing), len(starter)


def _collect_security_scan_paths(
    workspace: Path,
    *,
    scan_path: Path | None,
    all_user: bool,
    all_generated: bool,
) -> list[Path]:
    """Resolve workspace skill directories to scan.

    Args:
        workspace (Path): Workspace content root.
        scan_path (Path | None): Explicit skill directory under the workspace.
        all_user (bool): Scan every ``skills/user/*/`` directory.
        all_generated (bool): Scan every ``skills/generated/*/`` directory.

    Returns:
        list[Path]: Existing directories to scan.

    Raises:
        typer.BadParameter: When no scan scope is selected or paths are invalid.

    Examples:
        >>> from tempfile import TemporaryDirectory
        >>> with TemporaryDirectory() as td:
        ...     ws = Path(td)
        ...     skill = ws / "skills" / "user" / "demo"
        ...     skill.mkdir(parents=True)
        ...     paths = _collect_security_scan_paths(ws, scan_path=skill, all_user=False, all_generated=False)
        ...     paths[0].name
        'demo'
    """
    if scan_path is not None:
        target = scan_path if scan_path.is_absolute() else workspace / scan_path
        if not target.is_dir():
            msg = f"scan path is not a directory: {target}"
            raise typer.BadParameter(msg)
        return [target.resolve()]
    paths: list[Path] = []
    skills_root = workspace / "skills"
    if all_user:
        user_root = skills_root / "user"
        if user_root.is_dir():
            paths.extend(sorted(p for p in user_root.iterdir() if p.is_dir()))
    if all_generated:
        gen_root = skills_root / "generated"
        if gen_root.is_dir():
            paths.extend(sorted(p for p in gen_root.iterdir() if p.is_dir()))
    if not paths:
        msg = "pass --path, --all-user, and/or --all-generated"
        raise typer.BadParameter(msg)
    return paths


def register(app: typer.Typer) -> None:
    """Attach ``skills`` Typer subapp to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """
    skills_app = typer.Typer(no_args_is_help=True, help="Workspace skills inventory helpers.")
    app.add_typer(skills_app, name="skills")

    @skills_app.command("sync")
    def sync(
        additive: bool = typer.Option(
            False,
            "--additive",
            help=(
                "Append rows present in the shipped starter but missing from the workspace "
                "INDEX. Never overwrites existing rows."
            ),
        ),
        workspace: Path = typer.Option(
            ...,
            "--workspace",
            envvar="SEVN_WORKSPACE",
            help="Workspace content root (or set SEVN_WORKSPACE).",
        ),
    ) -> None:
        """Refresh the workspace ``skills/INDEX.md`` from the shipped starter."""
        if not additive:
            typer.secho(
                "Refusing to overwrite workspace INDEX. Pass --additive to append "
                "rows the workspace is missing (the workspace is authoritative for "
                "user edits, see PROBLEMS.md §Priority 1.a).",
                err=True,
            )
            raise typer.Exit(2)
        target = _resolve_workspace_index(workspace)
        added, total = _sync_additive(target)
        rel = target.relative_to(workspace) if workspace in target.parents else target
        typer.echo(f"skills sync: appended {added} row(s); starter has {total} (target: {rel})")
        raise typer.Exit(0)

    @skills_app.command("security-scan")
    def security_scan(
        workspace: Path = typer.Option(
            ...,
            "--workspace",
            envvar="SEVN_WORKSPACE",
            help="Workspace content root (or set SEVN_WORKSPACE).",
        ),
        scan_path: Path | None = typer.Option(
            None,
            "--path",
            help="Single skill directory (e.g. skills/user/my-skill).",
        ),
        all_user: bool = typer.Option(
            False, "--all-user", help="Scan all skills/user/*/ directories."
        ),
        all_generated: bool = typer.Option(
            False,
            "--all-generated",
            help="Scan all skills/generated/*/ directories.",
        ),
    ) -> None:
        """Run SkillSpector static scan on workspace skill directories."""
        if resolve_skillspector_command() is None:
            typer.secho(
                "SkillSpector CLI not found — install with: uv sync --extra skillspector",
                err=True,
            )
            raise typer.Exit(1)
        targets = _collect_security_scan_paths(
            workspace,
            scan_path=scan_path,
            all_user=all_user,
            all_generated=all_generated,
        )
        total_findings = 0
        high_critical = 0
        rel_paths: list[str] = []
        exit_code = 0
        for target in targets:
            result = scan_skill_path(target, fail_severities=DEFAULT_FAIL_SEVERITIES)
            rel = normalize_skill_path(target, repo_root=workspace)
            rel_paths.append(rel)
            if result.error:
                typer.secho(f"{rel}: scan error — {result.error}", err=True)
                exit_code = 1
                continue
            total_findings += len(result.issues)
            high_critical += len(result.issues_at_or_above(DEFAULT_FAIL_SEVERITIES))
            if result.issues:
                typer.secho(f"{rel}: {len(result.issues)} HIGH/CRITICAL finding(s)", err=True)
                for issue in result.issues:
                    loc = f" ({issue.file})" if issue.file else ""
                    typer.secho(f"  - {issue.severity} {issue.rule_id}{loc}", err=True)
                exit_code = 1
            else:
                typer.echo(f"{rel}: ok")
        write_workspace_scan_summary(
            workspace,
            scanned_paths=rel_paths,
            total_findings=total_findings,
            high_critical=high_critical,
        )
        raise typer.Exit(exit_code)

    @skills_app.command("list")
    def skills_list(
        json_out: bool = typer.Option(False, "--json", help="Emit JSON envelope on stdout."),
    ) -> None:
        """List workspace skills from the gateway inventory API."""
        from sevn.cli.dashboard_api_client import dashboard_api_get
        from sevn.cli.errors import CliPreconditionError
        from sevn.cli.json_util import emit_json_failure, emit_json_success
        from sevn.cli.workspace import load_bound_workspace

        command = "sevn skills list"
        try:
            bound = load_bound_workspace()
        except CliPreconditionError as exc:
            if json_out:
                emit_json_failure(
                    command=command,
                    error_code="PRECONDITION",
                    message=str(exc),
                    exit_code=exc.exit_code,
                )
            else:
                typer.secho(str(exc), err=True)
            raise typer.Exit(exc.exit_code) from exc
        body = dashboard_api_get(
            "/api/v1/agent/skills",
            command=command,
            workspace=bound.config,
            json_out=json_out,
        )
        if json_out:
            emit_json_success(command=command, data=body)
            return
        skills = body.get("skills")
        count = body.get("count", 0)
        typer.echo(f"skills: {count}")
        if isinstance(skills, list):
            for row in skills[:50]:
                if isinstance(row, dict):
                    name = row.get("name") or row.get("skill_name") or "?"
                    typer.echo(f"  {name}")
