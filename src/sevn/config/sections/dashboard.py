"""Dashboard (Mission Control) subtree models for ``sevn.json``.

Module: sevn.config.sections.dashboard
Depends: pydantic, sevn.config.defaults

Exports:
    DashboardPageAgentConfig — ``dashboard.page_agent`` feature flag.
    DashboardWorkspaceConfig — ``dashboard`` subtree (`specs/24-dashboard.md` §5).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from sevn.config.defaults import (
    DEFAULT_DASHBOARD_JWT_TTL_SECONDS,
    DEFAULT_DASHBOARD_PAGE_AGENT_ENABLED,
)


class DashboardPageAgentConfig(BaseModel):
    """``dashboard.page_agent`` feature flag (`specs/24-dashboard.md` §4.3)."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(default=DEFAULT_DASHBOARD_PAGE_AGENT_ENABLED)


class DashboardWorkspaceConfig(BaseModel):
    """Mission Control config subtree (`specs/24-dashboard.md` §5)."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    local_open: bool | None = None
    login_password: str | None = None
    jwt_secret: str | None = None
    jwt_ttl_seconds: int = Field(default=DEFAULT_DASHBOARD_JWT_TTL_SECONDS, ge=1)
    page_agent: DashboardPageAgentConfig | None = None
