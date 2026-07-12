"""Stable error codes for Cursor cloud integration.

Module: sevn.integrations.cursor_cloud.errors
Depends: (none)

Exports:
    CURSOR_NOT_CONFIGURED — proxy or API key missing.
    CURSOR_API_ERROR — upstream failure.
    CURSOR_JOB_NOT_FOUND — local job row missing.
    CURSOR_VALIDATION_ERROR — bad CLI args.
"""

from __future__ import annotations

CURSOR_NOT_CONFIGURED: str = "CURSOR_NOT_CONFIGURED"
CURSOR_API_ERROR: str = "CURSOR_API_ERROR"
CURSOR_JOB_NOT_FOUND: str = "CURSOR_JOB_NOT_FOUND"
CURSOR_VALIDATION_ERROR: str = "CURSOR_VALIDATION_ERROR"
