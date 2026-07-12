"""Patch author safety gates (`specs/33-self-improvement.md` §4.1).

Module: sevn.self_improve.proposer
Depends: re, sevn.self_improve.proposer.patch_author

Exports:
    reject_patch_diff — return a reason string when diff text fails static policy.
"""

from __future__ import annotations

import re

_SECRET_ASSIGN = re.compile(r"(?im)^\+.*\bSECRET\s*=")
_CREDENTIAL_MARKERS = (
    "BEGIN RSA PRIVATE KEY",
    "BEGIN OPENSSH PRIVATE KEY",
    "AWS_SECRET_ACCESS_KEY",
    "PRIVATE KEY-----",
)


def reject_patch_diff(diff: str) -> str | None:
    """Reject obviously sensitive unified diffs before LLM Guard.

    Args:
    diff (str): Unified diff text produced by ``patch_author``.

    Returns:
        str | None: Human-readable rejection reason, or ``None`` when allowed.

    Examples:
        >>> reject_patch_diff("+plain\\n") is None
        True
        >>> isinstance(reject_patch_diff("+SECRET=foo"), str)
        True
    """
    if _SECRET_ASSIGN.search(diff):
        return "patch_rejected_security: secret assignment in added line"
    for marker in _CREDENTIAL_MARKERS:
        if marker in diff:
            return f"patch_rejected_security: blocked marker {marker!r}"
    if re.search(r"(?i)\bid_rsa\b", diff) and diff.strip().startswith("+"):
        return "patch_rejected_security: credential filename in added line"
    return None


from sevn.self_improve.proposer.patch_author import (  # noqa: E402 — after reject_patch_diff
    author_patch_from_shortlist,
    preset_requires_proposer,
    reject_patch_policy,
    write_patch_artefacts,
)

__all__ = [
    "author_patch_from_shortlist",
    "preset_requires_proposer",
    "reject_patch_diff",
    "reject_patch_policy",
    "write_patch_artefacts",
]
