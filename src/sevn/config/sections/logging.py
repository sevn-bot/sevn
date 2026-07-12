"""Logging subtree models for ``sevn.json``.

Module: sevn.config.sections.logging
Depends: pydantic, sevn.config.defaults

Exports:
    LoggingCloudProviderConfig — ``logging.cloud.{r2,gcs}`` bucket ref.
    LoggingCloudConfig — ``logging.cloud`` subtree.
    LoggingWorkspaceConfig — ``logging`` retention/archive subtree.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sevn.config.defaults import (
    DEFAULT_LOG_ARCHIVE_DESTINATION,
    DEFAULT_LOG_RETENTION_DAYS,
    DEFAULT_TOOL_DEBUG_RESULT_MAX_CHARS,
)


class LoggingCloudProviderConfig(BaseModel):
    """Cloud bucket ref for one logging archive provider."""

    model_config = ConfigDict(extra="forbid")

    bucket_ref: str | None = None
    prefix: str = "sevn-logs/"


class LoggingCloudConfig(BaseModel):
    """``logging.cloud`` subtree for r2/gcs archive modes."""

    model_config = ConfigDict(extra="forbid")

    r2: LoggingCloudProviderConfig | None = None
    gcs: LoggingCloudProviderConfig | None = None


class LoggingWorkspaceConfig(BaseModel):
    """``logging`` subtree for rotated service log retention (`specs/02` §2.4)."""

    model_config = ConfigDict(extra="allow")

    retention_days: int = Field(default=DEFAULT_LOG_RETENTION_DAYS, ge=0)
    archive_mode: Literal["delete", "copy", "r2", "gcs"] = "copy"
    archive_destination: str = DEFAULT_LOG_ARCHIVE_DESTINATION
    cloud: LoggingCloudConfig | None = None
    pii_mode: Literal["secrets_only", "strict"] = "secrets_only"
    tool_debug_result_max_chars: int | None = Field(
        default=DEFAULT_TOOL_DEBUG_RESULT_MAX_CHARS,
        ge=1,
    )
    gateway_stream_debug: bool = False

    @model_validator(mode="after")
    def _archive_mode_requires_cloud_bucket(self) -> Self:
        """Require cloud bucket refs when ``archive_mode`` is ``r2`` or ``gcs``.

        Args:
            self (LoggingWorkspaceConfig): Validated logging subtree.

        Returns:
            LoggingWorkspaceConfig: Unchanged ``self`` when validation passes.

        Raises:
            ValueError: When a cloud archive mode lacks the matching bucket ref.

        Examples:
            >>> LoggingWorkspaceConfig(
            ...     archive_mode="copy",
            ... ).archive_mode
            'copy'
        """
        if self.archive_mode == "r2":
            bucket = (
                None if self.cloud is None or self.cloud.r2 is None else self.cloud.r2.bucket_ref
            )
            if not (bucket or "").strip():
                msg = "logging.cloud.r2.bucket_ref is required when logging.archive_mode is r2"
                raise ValueError(msg)
        elif self.archive_mode == "gcs":
            bucket = (
                None if self.cloud is None or self.cloud.gcs is None else self.cloud.gcs.bucket_ref
            )
            if not (bucket or "").strip():
                msg = "logging.cloud.gcs.bucket_ref is required when logging.archive_mode is gcs"
                raise ValueError(msg)
        return self
