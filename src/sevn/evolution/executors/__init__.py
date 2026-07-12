"""Evolution executor modules (`specs/35-bot-evolution.md` FL-4A).

Module: sevn.evolution.executors
Exports:
    dispatch_local_implement — tier-B worktree executor.
"""

from __future__ import annotations

from sevn.evolution.executors.local import dispatch_local_implement

__all__ = ["dispatch_local_implement"]
