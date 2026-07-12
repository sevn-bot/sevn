"""Normative ``ToolResult`` JSON ``code`` field values (`specs/11-tools-registry.md` §3.1).

Extend this enum rather than scattering string literals across tools and adapters.

Module: sevn.tools.codes
Depends: (none)

Exports:
    ToolResultCode — canonical failure/success adjunct codes.

Examples:
    >>> ToolResultCode.UNKNOWN_TOOL.value
    'UNKNOWN_TOOL'
"""

from __future__ import annotations

from enum import StrEnum


class ToolResultCode(StrEnum):
    """Machine-readable outcome labels for outward JSON envelopes."""

    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    MCP_UNAVAILABLE = "MCP_UNAVAILABLE"
    SKILL_NOT_FOUND = "SKILL_NOT_FOUND"
    SKILL_IS_ACTUALLY_TOOL = "SKILL_IS_ACTUALLY_TOOL"
    DISABLED_TOOL = "DISABLED_TOOL"
    PLAN_HUMAN_GATE = "PLAN_HUMAN_GATE"
    TOOL_ABORTED = "TOOL_ABORTED"
    SKILL_SCRIPT_NONZERO = "SKILL_SCRIPT_NONZERO"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    MERGE_NEEDED = "MERGE_NEEDED"
    PLUGIN_HOOK_RAISED = "PLUGIN_HOOK_RAISED"
    TOOL_NOT_PROVISIONED = "TOOL_NOT_PROVISIONED"
    # Typed, retryable third-party/proxy failure (e.g. `proxy status 404`/5xx) — distinct
    # from INTERNAL_ERROR so callers know the fault is upstream, not a sevn.bot bug
    # (build-plan-from-review/waves/voice-duplex-tts-menu-log-fixes-wave-plan.md W5.3/W5.4).
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
