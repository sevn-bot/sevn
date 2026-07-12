"""Configuration subpackage: workspace file, defaults, process env.

Module: sevn.config
Depends: sevn.config.defaults, sevn.config.errors, sevn.config.loader, sevn.config.settings, sevn.config.workspace_config

Exports:
    SUPPORTED_SCHEMA_VERSIONS — accepted ``schema_version`` integers.
    DashboardWorkspaceConfig — typed Mission Control config subtree.
    PROCESS_SETTINGS_ENV_VAR_NAMES — env names parsed into ``ProcessSettings``.
    ProcessSettings — ``SEVN_*`` allowlist via pydantic-settings.
    WorkspaceConfig — typed ``sevn.json`` root (extras preserved).
    WorkspaceLayout — re-export from ``sevn.workspace`` for convenience.
    find_sevn_json — parent walk discovery.
    load_workspace — parse + validate + layout.
    parse_workspace_config — validate a dict.
    SevnConfigError — base error.
    SevnJsonNotFoundError — missing file.
    UnsupportedSchemaVersionError — bad schema version.

Examples:
    >>> from sevn.config import SUPPORTED_SCHEMA_VERSIONS
    >>> {1, 2} <= SUPPORTED_SCHEMA_VERSIONS
    True
"""

from __future__ import annotations

from sevn.config.defaults import SUPPORTED_SCHEMA_VERSIONS
from sevn.config.errors import (
    SevnConfigError,
    SevnJsonNotFoundError,
    UnsupportedSchemaVersionError,
)
from sevn.config.loader import (
    ensure_schema_supported,
    find_sevn_json,
    load_workspace,
)
from sevn.config.settings import PROCESS_SETTINGS_ENV_VAR_NAMES, ProcessSettings
from sevn.config.workspace_config import (
    DashboardWorkspaceConfig,
    GatewayConfig,
    SecretsBackendSectionConfig,
    TraceSinkEntry,
    TracingConfig,
    WorkspaceConfig,
    parse_workspace_config,
    tier_b_skill_cap,
)
from sevn.workspace.layout import WorkspaceLayout

__all__ = [
    "PROCESS_SETTINGS_ENV_VAR_NAMES",
    "SUPPORTED_SCHEMA_VERSIONS",
    "DashboardWorkspaceConfig",
    "GatewayConfig",
    "ProcessSettings",
    "SecretsBackendSectionConfig",
    "SevnConfigError",
    "SevnJsonNotFoundError",
    "TraceSinkEntry",
    "TracingConfig",
    "UnsupportedSchemaVersionError",
    "WorkspaceConfig",
    "WorkspaceLayout",
    "ensure_schema_supported",
    "find_sevn_json",
    "load_workspace",
    "parse_workspace_config",
    "tier_b_skill_cap",
]
