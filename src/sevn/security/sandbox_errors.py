"""Sandbox execution and policy errors (``specs/08-sandbox.md``).

Module: sevn.security.sandbox_errors
Depends: (none)

Exports:
    SandboxError — base runtime failure.
    SandboxConfigurationError — misconfiguration or missing isolation prereqs.
    SandboxPolicyViolationError — argv / PID self-preservation rejection.

Examples:
    >>> issubclass(SandboxPolicyViolationError, SandboxError)
    True
"""

from __future__ import annotations


class SandboxError(RuntimeError):
    """Base class for sandbox runtime failures."""


class SandboxConfigurationError(SandboxError):
    """Raised when isolation cannot be started (Docker, flags, or policy)."""


class SandboxPolicyViolationError(SandboxError):
    """Raised when argv or PID targeting violates self-preservation rules."""
