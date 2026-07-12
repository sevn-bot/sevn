"""``sevn subagents`` — list, kill, and limit controls (`specs/23-cli.md` §3, D13).

Module: sevn.cli.commands.subagents_cmd
Depends: asyncio, json, sqlite3, typer, sevn.agent.subagents, sevn.cli.dashboard_api_client,
    sevn.cli.workspace, sevn.config.sections.subagents

Exports:
    register — attach ``subagents`` Typer subapp to the root CLI.
    show_subagents_config — print limits summary for ``sevn config subagents``.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, NoReturn

import typer

from sevn.agent.subagents.storage import list_recent_subagent_runs
from sevn.cli.errors import CliPreconditionError
from sevn.cli.json_util import emit_json_failure, emit_json_success
from sevn.cli.workspace import load_bound_workspace
from sevn.config.sections.subagents import Role, SubAgentsWorkspaceConfig
from sevn.gateway.mission_subagents_snapshot import _build_limits_payload
from sevn.gateway.workspace_config_io import mutate_sevn_json
from sevn.onboarding.web_app import _get_nested, _set_nested
from sevn.storage.migrate import apply_migrations

_ROLES: tuple[Role, ...] = ("triager", "tier_b", "tier_c", "tier_d")


def _subagents_cfg_from_doc(raw: dict[str, Any]) -> SubAgentsWorkspaceConfig | None:
    """Parse the ``subagents`` subtree from a raw ``sevn.json`` document.

    Args:
        raw (dict[str, Any]): Workspace document.

    Returns:
        SubAgentsWorkspaceConfig | None: Parsed subtree when present.

    Examples:
        >>> _subagents_cfg_from_doc({}) is None
        True
    """
    block = raw.get("subagents")
    if not isinstance(block, dict):
        return None
    return SubAgentsWorkspaceConfig.model_validate(block)


def _open_workspace_db(content_root: Any) -> sqlite3.Connection:
    """Open migrated ``sevn.db`` under the workspace content root.

    Args:
        content_root (Any): Path-like workspace content root.

    Returns:
        sqlite3.Connection: Open connection with migrations applied.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     (root / ".sevn").mkdir()
        ...     conn = _open_workspace_db(root)
        ...     conn.execute("SELECT 1").fetchone()[0] == 1
        True
    """
    db_path = content_root / ".sevn" / "sevn.db"
    conn = sqlite3.connect(str(db_path))
    apply_migrations(conn)
    return conn


def _count_orphaned(conn: sqlite3.Connection) -> int:
    """Return rows marked ``orphaned`` in ``subagent_runs``.

    Args:
        conn (sqlite3.Connection): Open migrated DB handle.

    Returns:
        int: Orphan count.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> _count_orphaned(c)
        0
    """
    row = conn.execute(
        "SELECT COUNT(*) FROM subagent_runs WHERE status = 'orphaned'",
    ).fetchone()
    return int(row[0]) if row else 0


def show_subagents_config(*, json_out: bool) -> None:
    """Print sub-agent limits and enabled flag for ``sevn config subagents``.

    Args:
        json_out (bool): Emit JSON envelope when True.

    Raises:
        typer.Exit: On workspace precondition errors.

    Examples:
        >>> show_subagents_config(json_out=True)  # doctest: +SKIP
    """
    try:
        bound = load_bound_workspace()
    except CliPreconditionError as exc:
        if json_out:
            emit_json_failure(
                command="sevn config subagents",
                error_code="WORKSPACE_PRECONDITION",
                message=str(exc),
                exit_code=4,
            )
        else:
            typer.secho(str(exc), err=True)
        raise typer.Exit(4) from exc
    cfg = bound.config.subagents
    payload = _build_limits_payload(cfg)
    conn = _open_workspace_db(bound.layout.content_root)
    try:
        payload["orphaned_count"] = _count_orphaned(conn)
    finally:
        conn.close()
    if json_out:
        emit_json_success(command="sevn config subagents", data=payload)
        raise typer.Exit(0)
    limits = payload
    lines = [
        "Sub-agents",
        "",
        f"enabled: {limits['enabled']}",
        f"max_level1_default: {limits['max_level1_default']}",
        f"max_level2_default: {limits['max_level2_default']}",
        f"max_override: {limits['max_override']!r}",
        f"timeout_s: {limits['timeout_s']!r}",
        f"orphaned_runs (storage): {payload['orphaned_count']}",
        "",
        "Per-role effective limits:",
    ]
    for role in _ROLES:
        caps = limits["by_role"][role]
        lines.append(f"  {role}: L1={caps['max_level1']} L2={caps['max_level2']}")
    lines.append("")
    lines.append("Edit: `sevn subagents limits` or Telegram /config → Advanced → Sub-agents.")
    typer.echo("\n".join(lines))
    raise typer.Exit(0)


def _cli_fail(
    *,
    command: str,
    message: str,
    json_out: bool,
    exit_code: int = 4,
    error_code: str = "PRECONDITION",
) -> NoReturn:
    """Emit failure output and exit.

    Args:
        command (str): Command label.
        message (str): Human-readable error.
        json_out (bool): JSON envelope when True.
        exit_code (int): Process exit code.
        error_code (str): Stable machine code.

    Returns:
        NoReturn: Always raises ``typer.Exit``.

    Raises:
        typer.Exit: Always.

    Examples:
        >>> import typer
        >>> try:
        ...     _cli_fail(command="t", message="nope", json_out=False)
        ... except typer.Exit as exc:
        ...     exc.exit_code == 4
        ... else:
        ...     False
        True
    """
    if json_out:
        emit_json_failure(
            command=command,
            error_code=error_code,
            message=message,
            exit_code=exit_code,
        )
    else:
        typer.secho(message, err=True)
    raise typer.Exit(exit_code)


def register(app: typer.Typer) -> None:
    """Attach ``sevn subagents`` to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """
    sub = typer.Typer(help="List, kill, and configure level-1/level-2 sub-agent runs (D13).")
    app.add_typer(sub, name="subagents")

    @sub.command("list")
    def subagents_list(
        all_runs: bool = typer.Option(
            False,
            "--all",
            help="Include terminal history from storage (not only in-memory running).",
        ),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON envelope on stdout."),
        limit: int = typer.Option(30, "--limit", help="Max rows for ``--all`` history."),
    ) -> None:
        """List running sub-agents (live) or recent history with ``--all``."""
        command = "sevn subagents list"
        try:
            bound = load_bound_workspace()
        except CliPreconditionError as exc:
            _cli_fail(command=command, message=str(exc), json_out=json_out)
        if all_runs:
            conn = _open_workspace_db(bound.layout.content_root)
            try:
                rows = list_recent_subagent_runs(conn, limit=max(1, limit))
            finally:
                conn.close()
            if json_out:
                emit_json_success(command=command, data={"history": rows})
                return
            if not rows:
                typer.echo("No sub-agent history in storage.")
                return
            for row in rows:
                typer.echo(
                    f"{row.get('id')} L{row.get('level')} {row.get('role')} "
                    f"{row.get('status')} — {row.get('task_summary', '')!r}",
                )
            return
        from sevn.cli.dashboard_api_client import dashboard_api_get

        try:
            body = dashboard_api_get(
                "/api/v1/mission/subagents",
                command=command,
                workspace=bound.config,
                json_out=json_out,
            )
        except typer.Exit:
            raise
        except Exception as exc:
            _cli_fail(
                command=command,
                message=(
                    f"Could not reach gateway sub-agent snapshot ({exc}). "
                    "Start the gateway or use `sevn subagents list --all` for storage history."
                ),
                json_out=json_out,
            )
        running = body.get("running", [])
        if json_out:
            emit_json_success(
                command=command,
                data={
                    "running": running,
                    "counts": body.get("counts"),
                    "limits": body.get("limits"),
                },
            )
            return
        if not running:
            typer.echo("No running sub-agents.")
            return
        for row in running:
            if not isinstance(row, dict):
                continue
            typer.echo(
                f"{row.get('id')} L{row.get('level')} {row.get('role')} "
                f"{row.get('status')} age={row.get('age_s')}s — {row.get('task_summary', '')!r}",
            )

    @sub.command("kill")
    def subagents_kill(
        subagent_id: str | None = typer.Argument(
            None,
            help="Short run id to kill (omit with --all).",
        ),
        kill_all: bool = typer.Option(False, "--all", help="Kill all active level-1 runs."),
        role: str | None = typer.Option(
            None,
            "--role",
            help="When ``--all``, optional triager/tier_b/tier_c/tier_d filter.",
        ),
        force: bool = typer.Option(
            False,
            "--force",
            help="Accepted for CLI parity; supervisor always uses cooperative cancel (D4).",
        ),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON envelope on stdout."),
    ) -> None:
        """Kill one sub-agent or all active runs via the gateway supervisor (D13)."""
        _ = force
        command = "sevn subagents kill"
        if not kill_all and not subagent_id:
            _cli_fail(
                command=command,
                message="Provide a run id or --all.",
                json_out=json_out,
                exit_code=2,
                error_code="USAGE",
            )
        if kill_all and subagent_id:
            _cli_fail(
                command=command,
                message="Use either a run id or --all, not both.",
                json_out=json_out,
                exit_code=2,
                error_code="USAGE",
            )
        try:
            bound = load_bound_workspace()
        except CliPreconditionError as exc:
            _cli_fail(command=command, message=str(exc), json_out=json_out)
        from sevn.cli.dashboard_api_client import dashboard_api_post

        if kill_all:
            path = "/api/v1/mission/subagents/kill_all"
            if role:
                path = f"{path}?role={role.strip()}"
            try:
                body = dashboard_api_post(
                    path,
                    command=command,
                    workspace=bound.config,
                    json_out=json_out,
                )
            except typer.Exit:
                raise
            except Exception as exc:
                _cli_fail(
                    command=command,
                    message=f"Kill-all failed ({exc}). Is the gateway running?",
                    json_out=json_out,
                )
        else:
            if subagent_id is None:
                _cli_fail(
                    command=command,
                    message="subagent id is required",
                    json_out=json_out,
                )
            try:
                body = dashboard_api_post(
                    f"/api/v1/mission/subagents/{subagent_id.strip()}/kill",
                    command=command,
                    workspace=bound.config,
                    json_out=json_out,
                )
            except typer.Exit:
                raise
            except Exception as exc:
                _cli_fail(
                    command=command,
                    message=f"Kill failed ({exc}). Is the gateway running?",
                    json_out=json_out,
                )
        if json_out:
            emit_json_success(command=command, data=body)
            return
        if kill_all:
            typer.echo(f"Killed {body.get('killed', 0)} sub-agent run(s).")
        else:
            typer.echo(
                f"{'Killed' if body.get('killed') else 'Not killed'} "
                f"{body.get('id', subagent_id)} (status={body.get('status')}).",
            )

    @sub.command("limits")
    def subagents_limits(
        role: str | None = typer.Option(
            None,
            "--role",
            help="Level-1 role to update (triager, tier_b, tier_c, tier_d).",
        ),
        max_l1: int | None = typer.Option(None, "--max-l1", help="Per-role max level-1 cap."),
        max_l2: int | None = typer.Option(None, "--max-l2", help="Per-role max level-2 cap."),
        override: int | None = typer.Option(
            None,
            "--override",
            help="Global ceiling override (``subagents.max_override``).",
        ),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON envelope on stdout."),
    ) -> None:
        """Show or update sub-agent concurrency limits in ``sevn.json`` (D2)."""
        command = "sevn subagents limits"
        try:
            bound = load_bound_workspace()
        except CliPreconditionError as exc:
            _cli_fail(command=command, message=str(exc), json_out=json_out)
        has_write = override is not None or max_l1 is not None or max_l2 is not None
        if has_write and role is None and (max_l1 is not None or max_l2 is not None):
            _cli_fail(
                command=command,
                message="--role is required when setting --max-l1 or --max-l2.",
                json_out=json_out,
                exit_code=2,
                error_code="USAGE",
            )
        if role is not None and role.strip() not in _ROLES:
            _cli_fail(
                command=command,
                message=f"unknown role {role!r}; expected one of {', '.join(_ROLES)}",
                json_out=json_out,
                exit_code=2,
                error_code="USAGE",
            )
        if has_write:

            def _apply(doc: dict[str, Any]) -> None:
                if override is not None:
                    _set_nested(doc, "subagents.max_override", override)
                if role is not None and (max_l1 is not None or max_l2 is not None):
                    base = _get_nested(doc, f"subagents.agents.{role}")
                    agents = dict(base) if isinstance(base, dict) else {}
                    if max_l1 is not None:
                        agents["max_level1"] = max_l1
                    if max_l2 is not None:
                        agents["max_level2"] = max_l2
                    _set_nested(doc, f"subagents.agents.{role}", agents)

            mutate_sevn_json(bound.sevn_json_path, _apply)
        cfg = _subagents_cfg_from_doc(json.loads(bound.sevn_json_path.read_text(encoding="utf-8")))
        payload = _build_limits_payload(cfg)
        if json_out:
            emit_json_success(command=command, data=payload)
            return
        show_subagents_config(json_out=False)


__all__ = ["register", "show_subagents_config"]
