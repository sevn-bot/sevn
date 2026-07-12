"""Cursor Cloud Agent integration for bundled ``cursor_cloud`` skill.

Module: sevn.integrations.cursor_cloud
Depends: sevn.integrations.cursor_cloud.client, sevn.integrations.cursor_cloud.jobs

Exports:
    create_cloud_agent — launch agent via proxy.
    refresh_job_status — poll agent + run and update SQLite row.
    list_workspace_jobs — list persisted jobs.
"""

from __future__ import annotations

from sevn.integrations.cursor_cloud.client import (
    artifact_download_url,
    create_cloud_agent,
    get_agent,
    get_run,
    list_artifacts,
    refresh_job_status,
)
from sevn.integrations.cursor_cloud.jobs import list_workspace_jobs

__all__ = [
    "artifact_download_url",
    "create_cloud_agent",
    "get_agent",
    "get_run",
    "list_artifacts",
    "list_workspace_jobs",
    "refresh_job_status",
]
