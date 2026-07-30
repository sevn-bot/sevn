"""Config backup archive settings for ``sevn.json`` versioned backups.

Module: sevn.config.sections.config_archive
Depends: pydantic, sevn.config.defaults

Exports:
    ConfigArchiveWorkspaceConfig — ``config_archive`` retention subtree.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from sevn.config.defaults import (
    DEFAULT_CONFIG_ARCHIVE_KEEP_COUNT,
    DEFAULT_CONFIG_ARCHIVE_RETENTION_DAYS,
)


class ConfigArchiveWorkspaceConfig(BaseModel):
    """``config_archive`` subtree for ``sevn.json.v*`` backup retention (`specs/02` §2)."""

    model_config = ConfigDict(extra="allow")

    keep_count: int = Field(default=DEFAULT_CONFIG_ARCHIVE_KEEP_COUNT, ge=0)
    retention_days: int = Field(default=DEFAULT_CONFIG_ARCHIVE_RETENTION_DAYS, ge=0)
