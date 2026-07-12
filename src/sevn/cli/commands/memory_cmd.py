"""Memory / Dreaming CLI hooks (`specs/23-cli.md` §2.4, `specs/31-memory-dreaming.md`).

Module: sevn.cli.commands.memory_cmd
Depends: typer, sevn.memory.dreaming, sevn.storage.sqlite

Exports:
    register — attach ``sevn memory`` subtree to the root Typer app.
"""

from __future__ import annotations

import asyncio
import json

import typer

from sevn.agent.tracing.sink import NullTraceSink
from sevn.cli.workspace import load_bound_workspace
from sevn.memory.dreaming.engine import DreamingEngine
from sevn.memory.dreaming.rollback import rollback_last_auto_batch
from sevn.memory.dreaming.scheduler import effective_dreaming, reconcile_dreaming_cron_job
from sevn.storage.sqlite import open_sevn_sqlite


def register(app: typer.Typer) -> None:
    """Attach ``sevn memory`` subtree to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """
    mem = typer.Typer(
        help=(
            "Memory operator hooks for long-context management (LCM) and grounded Dreaming backfill."
        ),
    )
    app.add_typer(mem, name="memory")

    @mem.command("status")
    def memory_status() -> None:
        """Summarize Dreaming toggles from bound ``sevn.json`` (read-only)."""
        bw = load_bound_workspace()
        d = effective_dreaming(bw.config)
        typer.echo(
            json.dumps(
                {
                    "dreaming_enabled": d.enabled,
                    "promotion_mode": d.promotion_mode,
                    "cron": d.cron,
                    "threshold": d.threshold,
                    "max_promotions_per_run": d.max_promotions_per_run,
                },
                indent=2,
            ),
        )

    @mem.command("rem-backfill")
    def memory_rem_backfill(
        rollback: bool = typer.Option(
            False,
            "--rollback",
            help="Undo the last auto Dreaming batch on MEMORY.md (uses promoted manifest).",
        ),
        i_know_the_cost: bool = typer.Option(
            False,
            "--i-know-the-cost",
            help="Acknowledge unbounded / wide backfill windows beyond backfill_days.",
        ),
        date_from: str | None = typer.Option(
            None, "--from", help="Inclusive YYYY-MM-DD lower bound."
        ),
        date_to: str | None = typer.Option(None, "--to", help="Inclusive YYYY-MM-DD upper bound."),
    ) -> None:
        """Replay grounded Dreaming over a date window, or undo the last auto batch."""
        bw = load_bound_workspace()
        root = bw.layout.content_root
        if rollback:
            rollback_last_auto_batch(root)
            typer.echo("rollback complete")
            raise typer.Exit(0)

        trace = NullTraceSink()
        conn = open_sevn_sqlite(bw.layout.dot_sevn)
        try:
            lock = asyncio.Lock()
            eng = DreamingEngine(conn, trace, lock, transport=None)
            result = asyncio.run(
                eng.run_backfill(
                    workspace_root=root,
                    ws=bw.config,
                    date_from=date_from,
                    date_to=date_to,
                    unbounded_acknowledged=i_know_the_cost,
                ),
            )
        finally:
            conn.close()

        typer.echo(
            json.dumps(
                {
                    "run_id": result.run_id,
                    "promoted": len(result.promoted),
                    "skipped": len(result.skipped),
                    "manifest": str(result.promoted_manifest_path),
                },
                indent=2,
            ),
        )

    @mem.command("reconcile-cron")
    def memory_reconcile_cron() -> None:
        """Rewrite ``trigger_cron_jobs`` Dreaming row from config (for operators without gateway)."""
        bw = load_bound_workspace()
        conn = open_sevn_sqlite(bw.layout.dot_sevn)
        try:
            reconcile_dreaming_cron_job(conn, bw.config)
        finally:
            conn.close()
        typer.echo("dreaming cron row reconciled")

    @mem.command("search")
    def memory_search() -> None:
        typer.secho("`sevn memory search` is not implemented yet.", err=True)
        raise typer.Exit(4)

    @mem.command("index")
    def memory_index() -> None:
        typer.secho("`sevn memory index` is not implemented yet.", err=True)
        raise typer.Exit(4)
