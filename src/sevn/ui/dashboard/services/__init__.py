"""Shared dashboard services.

Module: sevn.ui.dashboard.services
Depends: sevn.ui.dashboard.services.auth

Exports:
    DASHBOARD_COOKIE_NAME — httpOnly browser cookie name.
    DASHBOARD_CSRF_COOKIE_NAME — double-submit CSRF cookie name.
    DASHBOARD_CSRF_HEADER — CSRF request header name.
    DashboardAuthService — owner auth/session service.
    DashboardClaims — verified dashboard JWT claims.
"""

from __future__ import annotations

from sevn.ui.dashboard.services.auth import (
    DASHBOARD_COOKIE_NAME,
    DASHBOARD_CSRF_COOKIE_NAME,
    DASHBOARD_CSRF_HEADER,
    DashboardAuthService,
    DashboardClaims,
)

__all__ = [
    "DASHBOARD_COOKIE_NAME",
    "DASHBOARD_CSRF_COOKIE_NAME",
    "DASHBOARD_CSRF_HEADER",
    "DashboardAuthService",
    "DashboardClaims",
]
