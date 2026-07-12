"""Bot evolution pillar (`specs/35-bot-evolution.md`).

Module: sevn.evolution
Depends: sevn.evolution.spec_kit, sevn.evolution.spec_kit_runs

Exports:
    run_specify_allowlisted — allowlisted spec-kit subprocess façade.
    load_constitution — read constitution for planning stages.
    load_spec_kit_options — Mission Control options snapshot.
    resolve_executor — bug/feature executor routing (local or cursor_cloud).
"""

from __future__ import annotations

from sevn.evolution.router import resolve_executor
from sevn.evolution.spec_kit import (
    load_constitution,
    load_spec_kit_options,
    run_specify_allowlisted,
    save_spec_kit_options,
)

__all__ = [
    "load_constitution",
    "load_spec_kit_options",
    "resolve_executor",
    "run_specify_allowlisted",
    "save_spec_kit_options",
]
