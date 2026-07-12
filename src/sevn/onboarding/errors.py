"""Onboarding-specific errors (`specs/22-onboarding.md` §6).

Module: sevn.onboarding.errors
Depends: sevn.config.errors

Exports:
    OnboardingDraftLockError — concurrent draft writer (exit code 4 in CLI).
"""

from __future__ import annotations

from sevn.config.errors import SevnConfigError


class OnboardingDraftLockError(SevnConfigError):
    """Raised when another process holds the draft advisory lock."""
