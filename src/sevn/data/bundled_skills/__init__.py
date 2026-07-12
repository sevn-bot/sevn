"""Packaged ``skills/core`` trees shipped with sevn (`specs/12-skills-system.md`, `specs/27-second-brain.md`).

Module: sevn.data.bundled_skills
Depends: pathlib

Exports:
    BUNDLED_SKILLS_ROOT — directory containing ``core/``, ``user/``, … layout mirror.
"""

from __future__ import annotations

from pathlib import Path

BUNDLED_SKILLS_ROOT: Path = Path(__file__).resolve().parent

__all__ = ["BUNDLED_SKILLS_ROOT"]
