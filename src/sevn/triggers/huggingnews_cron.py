"""Reconcile HuggingNews daily cron prompt (#135, D14).

Module: sevn.triggers.huggingnews_cron
Depends: sqlite3, sevn.config.workspace_config, sevn.gateway.boot_registry

Exports:
    reconcile_huggingnews_cron_job — boot hook patching legacy defuddle prompts.
"""

from __future__ import annotations

import sqlite3

from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.boot_registry import register_cron_job

HUGGINGNEWS_CRON_JOB_ID = "daily-huggingnews-10am-amsterdam"

HUGGINGNEWS_CANONICAL_PROMPT = (
    "Daily HuggingNews digest: fetch https://huggingnews.com/ with get_page_content(url=...) "
    "or web_fetch — never defuddle, npm, or other external CLIs. Summarize today's top items "
    "for the operator and deliver the summary."
)


def reconcile_huggingnews_cron_job(conn: sqlite3.Connection, _workspace: WorkspaceConfig) -> None:
    """Patch the operator HuggingNews cron row when it still references defuddle (D14).

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle.
        _workspace (WorkspaceConfig): Active workspace config (unused).

    Returns:
        None: Side-effect only.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.triggers.huggingnews_cron import reconcile_huggingnews_cron_job
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> reconcile_huggingnews_cron_job(c, WorkspaceConfig.minimal())
    """
    row = conn.execute(
        "SELECT payload_template FROM trigger_cron_jobs WHERE job_id = ?",
        (HUGGINGNEWS_CRON_JOB_ID,),
    ).fetchone()
    if row is None:
        return
    current = str(row[0] or "")
    if current == HUGGINGNEWS_CANONICAL_PROMPT:
        return
    lowered = current.lower()
    if "defuddle" in lowered or not current.strip():
        conn.execute(
            """
            UPDATE trigger_cron_jobs
            SET payload_template = ?
            WHERE job_id = ?
            """,
            (HUGGINGNEWS_CANONICAL_PROMPT, HUGGINGNEWS_CRON_JOB_ID),
        )
        conn.commit()


register_cron_job("huggingnews_prompt", reconcile_huggingnews_cron_job, priority=35)


__all__ = [
    "HUGGINGNEWS_CANONICAL_PROMPT",
    "HUGGINGNEWS_CRON_JOB_ID",
    "reconcile_huggingnews_cron_job",
]
