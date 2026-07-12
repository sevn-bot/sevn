"""Skill execution failures -> tool envelope codes (``specs/11-tools-registry.md`` §3.1).

Module: sevn.skills.errors
Depends: typing

Exports:
    Classes:
        SkillExecutionError — Domain error with stable ``code`` for adapters.
    Functions:
        failure_envelope — Build minimal ``ok=False`` tool payload fragment.
        success_envelope — Build minimal ``ok=True`` tool payload fragment.

Examples:
    >>> SkillExecutionError("x", code=SKILL_NOT_FOUND).code == SKILL_NOT_FOUND
    True
"""

from __future__ import annotations

from typing import Final

SKILL_NOT_FOUND: Final[str] = "SKILL_NOT_FOUND"
SKILL_IS_ACTUALLY_TOOL: Final[str] = "SKILL_IS_ACTUALLY_TOOL"
SKILL_VALIDATION: Final[str] = "SKILL_VALIDATION"
SKILL_QUARANTINED: Final[str] = "SKILL_QUARANTINED"
QUARANTINE_SECURITY: Final[str] = "QUARANTINE_SECURITY"
SKILL_SCRIPT_NONZERO: Final[str] = "SKILL_SCRIPT_NONZERO"
SKILL_SCRIPT_ARGS: Final[str] = "SKILL_SCRIPT_ARGS"
SKILL_SCRIPT_UNKNOWN: Final[str] = "SKILL_SCRIPT_UNKNOWN"
SKILL_INVALID_JSON: Final[str] = "SKILL_INVALID_JSON"
TOOL_TIMEOUT: Final[str] = "TOOL_TIMEOUT"
SKILL_RUNNABLE_UNSUPPORTED: Final[str] = "SKILL_RUNNABLE_UNSUPPORTED"


class SkillExecutionError(Exception):
    """Raised while parsing manifests or resolving skills (not subprocess JSON errors)."""

    def __init__(self, message: str, *, code: str = SKILL_VALIDATION) -> None:
        """Attach a stable machine ``code``.

        Args:
            message (str): Human-readable reason.
            code (str): Tool-envelope discriminator.

        Examples:
            >>> SkillExecutionError("bad", code=SKILL_VALIDATION).code
            'SKILL_VALIDATION'
        """
        super().__init__(message)
        self.code = code


def failure_envelope(
    code: str,
    message: str,
    *,
    data: dict[str, object] | None = None,
) -> dict[str, object]:
    """Tools-spec failure payload (minimal keys).

    Args:
        code (str): Stable code string.
        message (str): Human-readable ``error``.
        data (dict[str, object] | None): Optional structured ``data`` payload.

    Returns:
        dict[str, object]: Serializable envelope fragment.

    Examples:
        >>> failure_envelope("X", "m")["ok"]
        False
    """
    payload: dict[str, object] = {"ok": False, "error": message, "code": code}
    if data:
        payload["data"] = dict(data)
    return payload


def success_envelope(data: dict[str, object], message: str | None = None) -> dict[str, object]:
    """Tools-spec success payload.

    Args:
        data (dict[str, object]): ``data`` object.
        message (str | None): Optional message (often ``None``).

    Returns:
        dict[str, object]: Serializable envelope fragment.

    Examples:
        >>> success_envelope({})["ok"]
        True
    """
    return {"ok": True, "data": data, "message": message}
