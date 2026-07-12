"""Security, deployment, and sandbox subtree models for ``sevn.json``.

Module: sevn.config.sections.security
Depends: pydantic, sevn.config.defaults

Exports:
    DeploymentConfig — ``deployment.profile`` (``specs/08-sandbox.md`` production gate).
    SandboxConfig — ``sandbox.*`` overrides (``specs/08-sandbox.md`` §5.2).
    SecuritySandboxSubConfig — ``security.sandbox`` subtree (§08 §5).
    SecurityReplSubConfig — ``security.repl`` subtree (§08 §4.6).
    SecurityScannerSubConfig — ``security.scanner`` (``specs/09-security-scanner.md`` §5).
    SecurityLlmignoreRetentionSubConfig — ``security.llmignore.retention_days`` (§09).
    SecurityLlmignoreSubConfig — ``security.llmignore`` subtree (§09).
    SecurityAuditSubConfig — ``security.audit`` subtree (§09).
    SecurityWorkspaceConfig — ``security.*`` subtree (sandbox, repl, scanner, llmignore, audit).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sevn.config.defaults import (
    DEFAULT_LLMIGNORE_REL_PATH,
    DEFAULT_LLMIGNORE_RETENTION_BLOCKED_DAYS,
    DEFAULT_LLMIGNORE_RETENTION_INCIDENTS_DAYS,
    DEFAULT_LLMIGNORE_RETENTION_QUARANTINE_DAYS,
    DEFAULT_SCANNER_MAX_INBOUND_BYTES,
    DEFAULT_SCANNER_PROVIDERS,
    DEFAULT_SCANNER_TOXICITY_THRESHOLD,
    SANDBOX_SNAPSHOT_RETENTION_COUNT_DEFAULT,
)


class DeploymentConfig(BaseModel):
    """Deployment profile (``specs/08-sandbox.md`` §4.3 production gate)."""

    model_config = ConfigDict(extra="allow")

    profile: str | None = None


class SandboxConfig(BaseModel):
    """Sandbox resource + snapshot overrides (``specs/08-sandbox.md`` §5.2)."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    max_cpu: float | int | None = None
    max_mem_mb: int | None = None
    max_disk_mb: int | None = None
    max_pids: int | None = None
    max_lifetime: int | None = None
    snapshot_interval_minutes: int | None = None
    snapshot_retention_count: int = Field(
        default=SANDBOX_SNAPSHOT_RETENTION_COUNT_DEFAULT,
        ge=0,
    )


class SecuritySandboxSubConfig(BaseModel):
    """``security.sandbox`` subtree."""

    model_config = ConfigDict(extra="allow")

    allow_subprocess_fallback: bool = False


class SecurityReplSubConfig(BaseModel):
    """``security.repl`` subtree (``specs/08-sandbox.md`` §4.6)."""

    model_config = ConfigDict(extra="allow")

    scan_tool_results: Literal["raw", "llm_guard"] = "raw"


class SecurityScannerSubConfig(BaseModel):
    """``security.scanner`` subtree (``specs/09-security-scanner.md`` §5)."""

    model_config = ConfigDict(extra="allow")

    providers: list[str] = Field(default_factory=lambda: list(DEFAULT_SCANNER_PROVIDERS))
    bypass_owner: bool = True
    image_ocr: bool = False
    scan_voice: bool = True
    toxicity_threshold: float = Field(
        default=DEFAULT_SCANNER_TOXICITY_THRESHOLD,
        ge=0.0,
        le=1.0,
    )
    ban_topics: list[str] = Field(default_factory=list)
    feedback_tier: str | None = None
    heuristic_only: bool = False
    model: str | None = None
    max_inbound_bytes: int = Field(
        default=DEFAULT_SCANNER_MAX_INBOUND_BYTES,
        ge=1024,
        le=16_777_216,
    )


class SecurityLlmignoreRetentionSubConfig(BaseModel):
    """``security.llmignore.retention_days`` (``specs/09-security-scanner.md`` §3.2)."""

    model_config = ConfigDict(extra="allow")

    blocked: int = Field(default=DEFAULT_LLMIGNORE_RETENTION_BLOCKED_DAYS, ge=1)
    quarantine: int = Field(default=DEFAULT_LLMIGNORE_RETENTION_QUARANTINE_DAYS, ge=1)
    incidents: int = Field(default=DEFAULT_LLMIGNORE_RETENTION_INCIDENTS_DAYS, ge=1)


class SecurityLlmignoreSubConfig(BaseModel):
    """``security.llmignore`` subtree (``specs/09-security-scanner.md`` §5)."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    path: str = Field(default=DEFAULT_LLMIGNORE_REL_PATH, min_length=1)
    retention_days: SecurityLlmignoreRetentionSubConfig | None = None

    @field_validator("path", mode="before")
    @classmethod
    def _reject_path_traversal(cls, v: object) -> object:
        """Disallow absolute paths and ``..`` segments under the workspace root.

        Args:
            cls (type): Model class.
            v (object): Raw ``path`` value.

        Returns:
            object: Unchanged string-like value.

        Raises:
            ValueError: When the path can escape the workspace.

        Examples:
            >>> SecurityLlmignoreSubConfig._reject_path_traversal(None) is None
            True
            >>> SecurityLlmignoreSubConfig._reject_path_traversal(".llmignore") == ".llmignore"
            True
        """
        if v is None:
            return v
        if not isinstance(v, str):
            return v
        s = v.strip().strip("/")
        if not s:
            msg = "security.llmignore.path must be non-empty"
            raise ValueError(msg)
        p = Path(s)
        if p.is_absolute():
            msg = "security.llmignore.path must be relative to the workspace root"
            raise ValueError(msg)
        if ".." in p.parts:
            msg = "security.llmignore.path must not contain parent segments"
            raise ValueError(msg)
        return v


class SecurityAuditSubConfig(BaseModel):
    """``security.audit`` subtree (``specs/09-security-scanner.md`` §5)."""

    model_config = ConfigDict(extra="allow")

    incident_reads: bool = False


class SecurityWorkspaceConfig(BaseModel):
    """Security-related workspace keys (sandbox + repl + scanner + llmignore)."""

    model_config = ConfigDict(extra="allow")

    sandbox: SecuritySandboxSubConfig | None = None
    repl: SecurityReplSubConfig | None = None
    scanner: SecurityScannerSubConfig | None = None
    llmignore: SecurityLlmignoreSubConfig | None = None
    audit: SecurityAuditSubConfig | None = None
