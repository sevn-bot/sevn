"""Second Brain failure types (`specs/27-second-brain.md` §6).

Module: sevn.second_brain.errors

Exports:
    SecondBrainError — base class.
    SecondBrainPathError — unsafe or quarantined paths.
    SecondBrainMergeNeededError — wiki_apply hash mismatch.
"""

from __future__ import annotations


class SecondBrainError(Exception):
    """Base for Second Brain subsystem errors."""


class SecondBrainPathError(SecondBrainError):
    """Path escaped vault/wiki root or lies under ``.llmignore/``."""


class SecondBrainMergeNeededError(SecondBrainError):
    """``wiki_apply`` rejected because on-disk content changed (merge-needed)."""


__all__ = [
    "SecondBrainError",
    "SecondBrainMergeNeededError",
    "SecondBrainPathError",
]
